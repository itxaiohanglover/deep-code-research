# Copyright (c) Deep Code Research. All rights reserved.
"""
DeepCode 记忆管理 - 基于 mem0ai

设计原则：
1. 继承 ms_agent.memory.base.Memory（标准基类）
2. 直接集成 mem0ai（https://github.com/mem0ai/mem0）
3. user_id = project_id（项目级别共享）
4. agent_id = agent_name（按 Agent 隔离）
5. 支持迭代（iteration）标记
"""

import asyncio
import os
import re
from datetime import datetime
from functools import partial, wraps
from pathlib import Path
from typing import Any, Dict, List, Optional

from ms_agent.llm.utils import Message
from ms_agent.memory.base import Memory
from ms_agent.utils import get_logger

# 兼容不同版本的 ms-agent：
# - 新版本：提供 DEFAULT_OUTPUT_DIR 和 get_service_config
# - 旧版本（你当前安装的 site-packages 版本）：可能没有 get_service_config
try:  # pragma: no cover - 运行时兼容逻辑
    from ms_agent.utils.constants import DEFAULT_OUTPUT_DIR, get_service_config
except ImportError:  # 旧版 ms-agent，手动提供回退实现
    from ms_agent.utils.constants import DEFAULT_OUTPUT_DIR

    class _FallbackServiceConfig:
        """简化版 ServiceConfig，只提供 base_url 字段，满足当前使用场景"""

        def __init__(self, base_url: Optional[str] = None):
            self.base_url = base_url

    def get_service_config(service_name: str) -> "_FallbackServiceConfig":
        """回退实现：
        
        优先从环境变量读取：
        - {SERVICE}_BASE_URL（例如 MODELSCOPE_BASE_URL）
        - LLM_BASE_URL / llm_base_url（与 src.main 中逻辑一致）
        """
        # 优先专用环境变量
        env_key = f"{service_name.upper()}_BASE_URL"
        base_url = os.getenv(env_key)

        # 再尝试通用 LLM_BASE_URL（src.main 已经会注入）
        if not base_url:
            base_url = os.getenv("LLM_BASE_URL") or os.getenv("llm_base_url")

        return _FallbackServiceConfig(base_url=base_url)

from omegaconf import DictConfig, OmegaConf

logger = get_logger()

# 默认记忆存储目录
DEFAULT_MEMORY_DIR = "memory"

# 允许检索记忆的 Agent（与 memory_callback.py 中的 MEMORY_ENABLED_AGENTS 保持一致）
# 只有这些 Agent 会被 reflecting 回退到，需要检索自己的历史记忆
MEMORY_ENABLED_AGENTS = {
    'requirements',  # 回退目标：设计缺陷(phase2)时回退
    'coding',        # 回退目标：实现缺陷(phase3)时回退
    'testing',       # 回退目标：无测试时回退
}


class DeepCodeMemoryManager:
    """DeepCode 记忆管理器（单例模式）
    
    管理项目级共享记忆实例，所有 Agent 共享同一个向量数据库。
    """
    _instance: 'DeepCodeMemory' = None
    _project_id: str = None

    @classmethod
    def get_memory(cls, config: DictConfig) -> 'DeepCodeMemory':
        """获取或创建共享记忆实例"""
        project_id = getattr(config, 'project_id', 'deepcode_project')
        
        if cls._instance is None or cls._project_id != project_id:
            logger.info(f"Creating DeepCodeMemory for project: {project_id}")
            cls._instance = DeepCodeMemory(config)
            cls._project_id = project_id
        
        return cls._instance

    @classmethod
    def clear(cls):
        """清除实例"""
        cls._instance = None
        cls._project_id = None
        logger.info("Cleared DeepCodeMemory instance")


class DeepCodeMemory(Memory):
    """DeepCode 记忆管理
    
    继承自 ms_agent.memory.base.Memory，直接集成 mem0ai。
    
    特点：
    - user_id: 项目 ID（所有 Agent 共享）
    - agent_id: Agent 名称（隔离不同 Agent 的记忆）
    - iteration: 迭代次数（自动从 workflow_manager 获取）
    
    兼容性说明：
    pip 版本的 ms-agent（site-packages）与本地源码版本的 load_memory 行为不同：
    - pip 版本：直接将 YAML 中的单个 memory 配置项（_memory）传给构造函数
    - 本地源码版本：传入整个 self.config
    
    本实现同时兼容两种情况。
    
    Usage:
        memory = DeepCodeMemoryManager.get_memory(config)
        
        # 存储记忆
        memory.add("用户认证使用 JWT", agent_id="coding")
        
        # 搜索记忆
        results = memory.search("认证", agent_id="coding")
    """

    def __init__(self, config: DictConfig):
        """初始化 DeepCode 记忆
        
        Args:
            config: 配置对象，可能是：
                1. 整个 Agent config（本地源码版本）
                2. 单个 memory 配置项（pip 版本）
        """
        super().__init__(config)
        
        # 检测配置类型：pip 版本传入的是单个 memory 配置（有 name 字段）
        # 本地源码版本传入的是整个 config（有 llm 字段）
        self._is_memory_config = hasattr(config, 'name') and not hasattr(config, 'llm')
        
        if self._is_memory_config:
            # pip 版本：config 是单个 memory 配置项
            # 需要从环境变量获取 output_dir 等信息
            self.memory_config = config
            self.project_id = getattr(config, 'project_id', None) or getattr(config, 'user_id', None) or os.getenv('SESSION_ID', 'deepcode_project')
            self.memory_path = self._resolve_memory_path_from_env()
            
            # 为了兼容 pip 版本的 get_shared_memory，需要在 config 中设置 user_id 和 path
            # 这样 SharedMemoryManager 才能正确生成 key
            if not hasattr(config, 'user_id'):
                config.user_id = self.project_id
            if not hasattr(config, 'path'):
                config.path = self.memory_path
        else:
            # 本地源码版本：config 是整个 Agent config
            self.memory_config = getattr(config, 'deepcode_memory', config)
            self.project_id = getattr(config, 'project_id', 'deepcode_project')
            self.memory_path = self._resolve_memory_path(config)
        
        self.base_config = None
        self._lock = asyncio.Lock()
        
        # 初始化 mem0
        self.memory = self._init_memory_obj()
        
        if self.memory:
            logger.info(f'DeepCodeMemory initialized: project_id={self.project_id}, storage={self.memory_path}')
        else:
            logger.warning(f'DeepCodeMemory initialized without mem0 (fallback mode)')
    
    def _resolve_memory_path_from_env(self) -> str:
        """从环境变量解析记忆存储路径（pip 版本兼容）
        
        目标目录：output/{session_id}/memory
        使用 PathManager 确保路径正确包含 session_id
        """
        from src.utils.path_manager import PathManager
        
        session_id = os.getenv('SESSION_ID')
        path_manager = PathManager.from_env(session_id=session_id)
        
        # PathManager.memory_dir 已经包含 session_id（如果有的话）
        path = path_manager.memory_dir
        path.mkdir(parents=True, exist_ok=True)
        
        logger.debug(f'[DeepCodeMemory] 记忆存储路径: {path} (session_id={session_id})')
        return str(path)

    def _resolve_memory_path(self, config: DictConfig) -> str:
        """解析记忆存储路径
        
        目标目录：output/{session_id}/memory
        使用 PathManager 确保路径正确包含 session_id
        """
        # 使用 PathManager 获取正确的 memory 目录路径
        from src.utils.path_manager import PathManager
        
        # 注意：config.output_dir 已经包含 session_id（由 ConfigHandler 设置）
        # 所以不要再传递 session_id，避免路径重复
        path_manager = PathManager.from_config(config, session_id=None)
        
        path = path_manager.memory_dir
        path.mkdir(parents=True, exist_ok=True)
        
        session_id = os.getenv('SESSION_ID')  # 仅用于日志
        logger.debug(f'[DeepCodeMemory] 记忆存储路径: {path} (session_id={session_id})')
        return str(path)

    def _init_memory_obj(self):
        """初始化 mem0 对象
        
        兼容 mem0ai 0.1.x 和 1.0.x 版本
        
        """
        try:
            import mem0
            from mem0 import Memory as Mem0Memory
        except ImportError as e:
            logger.error(
                f'Failed to import mem0: {e}. Please install mem0ai package via `pip install mem0ai`.'
            )
            return None

        # 检查 mem0 版本
        mem0_version = getattr(mem0, '__version__', '0.0.0')
        logger.info(f'mem0ai version: {mem0_version}')
        
        # 0.0.x 版本不支持自定义 base_url
        if mem0_version.startswith('0.0.'):
            logger.warning(
                f'mem0ai {mem0_version} is too old and does not support custom base_url. '
                f'Please upgrade: pip install --upgrade mem0ai'
            )
            return None

        # 禁用遥测（兼容不同版本）
        try:
            if hasattr(mem0.memory.main, 'capture_event'):
                original_capture = mem0.memory.main.capture_event
                @wraps(original_capture)
                def disabled_capture(*args, **kwargs):
                    pass
                mem0.memory.main.capture_event = disabled_capture
        except Exception:
            pass  # 忽略 patch 失败
        

        # 构建 mem0 配置
        mem0_config = self._build_mem0_config()
        
        logger.debug(f'Mem0 config: {mem0_config}')
        
        try:
            memory = Mem0Memory.from_config(mem0_config)
            # 禁用遥测（如果存在）
            if hasattr(memory, '_telemetry_vector_store'):
                memory._telemetry_vector_store = None
            return memory
        except Exception as e:
            error_msg = str(e)
            logger.error(f'Failed to initialize Mem0 memory: {e}')
            
            # 检查是否是 qdrant init_from 错误
            if 'init_from' in error_msg and 'extra_forbidden' in error_msg:
                logger.error(
                    '检测到 qdrant-client 版本兼容性问题。'
                    'mem0ai 1.0.1 与 qdrant-client 1.16.0 不兼容。'
                    '解决方案：'
                    '1. 降级 qdrant-client: pip install qdrant-client==1.7.0'
                    '2. 或使用 chromadb（已自动尝试）'
                )
                # 如果使用的是 qdrant，尝试切换到 chromadb
                vector_store = mem0_config.get('vector_store', {})
                if isinstance(vector_store, dict) and vector_store.get('provider') == 'qdrant':
                    logger.info('尝试切换到 chromadb 作为向量存储...')
                    try:
                        import chromadb
                        # 修改配置使用 chromadb
                        qdrant_config = vector_store.get('config', {})
                        collection_name = qdrant_config.get('collection_name', sanitize_name(f'deepcode_{self.project_id}'))
                        new_vector_store = {
                            'provider': 'chroma',
                            'config': {
                                'path': self.memory_path,
                                'collection_name': collection_name,
                            }
                        }
                        # 如果有 embedding_dims，添加到 chromadb 配置
                        if 'embedding_model_dims' in qdrant_config:
                            dims = qdrant_config['embedding_model_dims']
                            new_vector_store['config']['embedding_dim'] = dims
                        mem0_config['vector_store'] = new_vector_store
                        
                        logger.info('使用 chromadb 重新初始化...')
                        memory = Mem0Memory.from_config(mem0_config)
                        if hasattr(memory, '_telemetry_vector_store'):
                            memory._telemetry_vector_store = None
                        logger.info('✅ 使用 chromadb 初始化成功')
                        return memory
                    except Exception as chroma_error:
                        logger.error(f'切换到 chromadb 也失败: {chroma_error}')
            
            import traceback
            logger.debug(traceback.format_exc())
            return None

    def _build_mem0_config(self) -> dict:
        """构建 mem0 配置"""
        
        def sanitize_name(ori_name: str, default_name: str = 'default') -> str:
            """清理名称以符合数据库要求"""
            if not ori_name or not isinstance(ori_name, str):
                return default_name
            sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', ori_name)
            sanitized = re.sub(r'_+', '_', sanitized)
            sanitized = sanitized.strip('_')
            if not sanitized:
                return default_name
            if sanitized[0].isdigit():
                sanitized = f'col_{sanitized}'
            return sanitized

        def get_api_key(config_obj, service: str) -> Optional[str]:
            """从配置中获取 API key"""
            # 尝试多种字段名
            key = getattr(config_obj, f'{service}_api_key', None)
            if key:
                return key
            key = getattr(config_obj, 'api_key', None)
            if key:
                return key
            # 从环境变量获取
            return os.getenv(f'{service.upper()}_API_KEY')

        def get_base_url(config_obj, service: str) -> Optional[str]:
            """从配置中获取 base URL"""
            # 尝试多种字段名
            url = getattr(config_obj, f'{service}_base_url', None)
            if url:
                return url
            url = getattr(config_obj, 'openai_base_url', None)
            if url:
                return url
            url = getattr(config_obj, 'base_url', None)
            if url:
                return url
            # 从环境变量或服务配置获取
            env_url = os.getenv(f'{service.upper()}_BASE_URL')
            if env_url:
                return env_url
            try:
                return get_service_config(service).base_url
            except Exception:
                return None

        # 根据配置类型获取 LLM 信息
        # pip 版本：config 是单个 memory 配置项，LLM 信息在 config.llm 中（由 load_memory 注入）
        # 本地源码版本：config 是整个 Agent config，LLM 信息在 config.llm 中
        if self._is_memory_config:
            # pip 版本：从 memory 配置中的 llm 字段获取（load_memory 会注入）
            # 注意：pip 版本注入的是 'service' 字段，不是 'provider'
            llm_config = getattr(self.config, 'llm', OmegaConf.create({}))
            service = getattr(llm_config, 'service', None) or getattr(llm_config, 'provider', 'modelscope')
        else:
            # 本地源码版本
            llm_config = getattr(self.config, 'llm', OmegaConf.create({}))
            service = getattr(llm_config, 'service', 'modelscope')
        
        # Embedder 配置（优先使用专门的 embedder 配置，否则从 llm 配置/环境变量推断）
        # 注意：pip 版本中，self.config 是单个 memory 配置项，可能没有 embedder 字段
        # 需要从环境变量或使用默认值
        if self._is_memory_config:
            # pip 版本：memory 配置项中可能没有 embedder，使用默认值或从环境变量获取
            embedder_config = OmegaConf.create({})
        else:
            # 本地源码版本：从整个 config 中获取 embedder 配置
            embedder_config = getattr(self.config, 'embedder', OmegaConf.create({}))
        
        embedder_service = getattr(embedder_config, 'service', service)
        embedder_api_key = get_api_key(embedder_config, embedder_service) or get_api_key(llm_config, service)
        embedder_base_url = get_base_url(embedder_config, embedder_service) or get_base_url(llm_config, service)
        embedder_model = getattr(embedder_config, 'model', 'Qwen/Qwen3-Embedding-8B')
        embedding_dims = getattr(embedder_config, 'embedding_dims', None)

        embedder = {
            'provider': 'openai',
            'config': {
                'api_key': embedder_api_key,
                'openai_base_url': embedder_base_url,
                'model': embedder_model,
            }
        }
        if embedding_dims:
            embedder['config']['embedding_dims'] = embedding_dims

        # LLM 配置
        llm = None
        if llm_config:
            llm_model = getattr(llm_config, 'model', 'Qwen/Qwen3-Coder-30B-A3B-Instruct')
            llm_api_key = get_api_key(llm_config, service)
            llm_base_url = get_base_url(llm_config, service)
            
            # 获取 max_tokens：优先从 llm_config，然后从 generation_config（如果存在）
            max_tokens = getattr(llm_config, 'max_tokens', None)
            if max_tokens is None and not self._is_memory_config:
                # 本地源码版本：尝试从 generation_config 获取
                max_tokens = getattr(
                    getattr(self.config, 'generation_config', OmegaConf.create({})), 'max_tokens', None
                )
            if max_tokens is None:
                max_tokens = 2000  # 默认值

            llm = {
                'provider': 'openai',
                'config': {
                    'model': llm_model,
                    'api_key': llm_api_key,
                    'openai_base_url': llm_base_url,
                }
            }
            if max_tokens:
                llm['config']['max_tokens'] = max_tokens

        # Vector Store 配置
        # 优先使用 chromadb（更稳定，兼容性更好）
        # 如果 chromadb 不可用，回退到 qdrant
        collection_name = sanitize_name(f'deepcode_{self.project_id}')
        
        # 检查是否可以使用 chromadb
        use_chromadb = True
        try:
            import chromadb
        except ImportError:
            use_chromadb = False
            logger.warning("chromadb 未安装，使用 qdrant 作为向量存储")
        
        if use_chromadb:
            # 使用 chromadb 作为向量存储（更稳定）
            vector_store = {
                'provider': 'chroma',
                'config': {
                    'path': self.memory_path,
                    'collection_name': collection_name,
                }
            }
        else:
            # 使用 qdrant 作为向量存储（需要兼容性处理）
            vector_store = {
                'provider': 'qdrant',
                'config': {
                    'path': self.memory_path,
                    'on_disk': True,
                    'collection_name': collection_name,
                }
            }
        
        if embedding_dims:
            if use_chromadb:
                # chromadb 使用不同的参数名
                vector_store['config']['embedding_dim'] = embedding_dims
            else:
                vector_store['config']['embedding_model_dims'] = embedding_dims

        # 最终配置
        mem0_config = {
            'vector_store': vector_store,
            'embedder': embedder,
        }
        if llm:
            mem0_config['llm'] = llm
            mem0_config['is_infer'] = True

        # 添加自定义提取提示词
        mem0_config['custom_fact_extraction_prompt'] = self._get_fact_extraction_prompt()

        return mem0_config

    def _get_fact_extraction_prompt(self) -> str:
        """获取事实提取提示词"""
        try:
            from ms_agent.utils import get_fact_retrieval_prompt
            prompt = get_fact_retrieval_prompt()
        except Exception:
            prompt = "Extract key facts and information from the conversation."
        
        return prompt + f"\nToday's date is {datetime.now().strftime('%Y-%m-%d')}."

    # ========== 核心 API ==========

    def add(
        self,
        content: str,
        agent_id: str = None,
        metadata: Dict[str, Any] = None,
        iteration: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """添加记忆"""
        if not self.memory:
            logger.warning("Memory not initialized")
            return None
        
        try:
            # 自动获取迭代信息
            if iteration is None:
                try:
                    from src.utils.workflow_manager import workflow_manager
                    iteration = workflow_manager.get_iteration()
                except Exception:
                    iteration = None

            # 合并 metadata
            final_metadata = metadata.copy() if metadata else {}
            if iteration is not None:
                final_metadata['iteration'] = iteration
            
            result = self.memory.add(
                content,
                user_id=self.project_id,
                agent_id=agent_id,
                metadata=final_metadata
            )
            
            iter_info = f", iteration={iteration}" if iteration else ""
            logger.debug(f"Added memory: agent={agent_id}{iter_info}, content={content[:50]}...")
            return result
            
        except Exception as e:
            logger.error(f"Failed to add memory: {e}")
            return None

    def search(
        self,
        query: str,
        agent_id: str = None,
        limit: int = 10,
        iteration: Optional[int] = None,
        prefer_previous_iteration: bool = True
    ) -> List[Dict[str, Any]]:
        """搜索记忆"""
        if not self.memory:
            logger.warning("Memory not initialized")
            return []
        
        try:
            # 获取上一次迭代
            previous_iteration = None
            if prefer_previous_iteration and iteration is None:
                try:
                    from src.utils.workflow_manager import workflow_manager
                    current_iteration = workflow_manager.get_iteration()
                    if current_iteration and current_iteration > 1:
                        previous_iteration = current_iteration - 1
                except Exception:
                    pass
            
            # 搜索
            search_limit = limit * 2 if (iteration is not None or prefer_previous_iteration) else limit
            search_kwargs = {
                'query': query,
                'user_id': self.project_id,
                'limit': search_limit
            }
            if agent_id:
                search_kwargs['agent_id'] = agent_id
            
            result = self.memory.search(**search_kwargs)
            
            if not result or not isinstance(result, dict) or 'results' not in result:
                return []
            
            memories = result['results']
            
            # 按迭代过滤
            if iteration is not None:
                memories = [
                    m for m in memories
                    if m.get('metadata', {}).get('iteration') == iteration
                ]
            
            # 优先上一次迭代
            if prefer_previous_iteration and previous_iteration is not None:
                previous_memories = [
                    m for m in memories
                    if m.get('metadata', {}).get('iteration') == previous_iteration
                ]
                other_memories = [
                    m for m in memories
                    if m.get('metadata', {}).get('iteration') != previous_iteration
                ]
                memories = previous_memories + other_memories
            
            memories = memories[:limit]
            logger.debug(f"Found {len(memories)} memories for query: {query[:30]}...")
            return memories
            
        except Exception as e:
            logger.error(f"Failed to search memories: {e}")
            return []

    def get_all(self, agent_id: str = None) -> List[Dict[str, Any]]:
        """获取所有记忆"""
        if not self.memory:
            return []
        
        try:
            kwargs = {'user_id': self.project_id}
            if agent_id:
                kwargs['agent_id'] = agent_id
            
            result = self.memory.get_all(**kwargs)
            
            if result and isinstance(result, dict) and 'results' in result:
                return result['results']
            return []
            
        except Exception as e:
            logger.error(f"Failed to get all memories: {e}")
            return []

    def delete(self, memory_id: str) -> bool:
        """删除指定记忆"""
        if not self.memory:
            return False
        
        try:
            self.memory.delete(memory_id=memory_id)
            logger.info(f"Deleted memory: {memory_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete memory: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """获取记忆统计"""
        all_memories = self.get_all()
        
        by_agent = {}
        by_iteration = {}
        
        for mem in all_memories:
            agent = mem.get('agent_id', 'unknown')
            by_agent[agent] = by_agent.get(agent, 0) + 1
            
            iteration = mem.get('metadata', {}).get('iteration')
            if iteration is not None:
                by_iteration[iteration] = by_iteration.get(iteration, 0) + 1
        
        return {
            'project_id': self.project_id,
            'total_count': len(all_memories),
            'by_agent': by_agent,
            'by_iteration': by_iteration,
            'storage_path': self.memory_path
        }

    # ========== ms-agent Memory 标准接口 ==========

    def set_base_config(self, config: DictConfig):
        """设置基础配置"""
        self.base_config = config

    async def run(self, messages: List[Message]) -> List[Message]:
        """处理消息并注入相关记忆（标准接口）
        
        性能优化：只有特定 Agent 才能检索记忆（与保存记忆的 Agent 一致）
        """
        async with self._lock:
            if not self.memory:
                return messages

            try:
                # 从 base_config.tag 获取 agent_id
                agent_id = None
                if self.base_config and hasattr(self.base_config, 'tag'):
                    agent_id = self.base_config.tag
                
                # 检查是否允许该 Agent 检索记忆（性能优化）
                if agent_id:
                    # 精确匹配
                    if agent_id not in MEMORY_ENABLED_AGENTS:
                        # 模糊匹配（处理带后缀的情况，如 coding_1）
                        agent_base = agent_id.split('_')[0].lower()
                        if agent_base not in MEMORY_ENABLED_AGENTS:
                            logger.debug(f"[DeepCodeMemory] [{agent_id}] 非关键 Agent，跳过记忆检索")
                            return messages
                
                latest_message = self._get_latest_user_message(messages)
                if not latest_message:
                    return messages

                # 搜索相关记忆
                limit = getattr(self.config, 'conversation_search_limit', 5)
                prefer_previous = getattr(self.config, 'prefer_previous_iteration_memory', True)
                
                memories = self.search(
                    query=latest_message,
                    agent_id=agent_id,
                    limit=limit,
                    prefer_previous_iteration=prefer_previous
                )

                # 提取记忆文本
                memory_texts = [m.get('memory', '') for m in memories if m.get('memory')]
                
                if memory_texts:
                    messages = self._inject_memories_into_messages(messages, memory_texts)
                    logger.debug(f"[DeepCodeMemory] [{agent_id}] 注入了 {len(memory_texts)} 条记忆")
                else:
                    logger.debug(f"[DeepCodeMemory] [{agent_id}] 未检索到相关记忆")

                return messages

            except Exception as e:
                logger.error(f"[DeepCodeMemory] 检索记忆出错: {e}")
                return messages

    def _get_latest_user_message(self, messages: List[Message]) -> Optional[str]:
        """获取最新的用户消息"""
        for msg in reversed(messages):
            if hasattr(msg, 'role') and msg.role == 'user' and msg.content:
                return msg.content
        return None

    def _inject_memories_into_messages(
        self,
        messages: List[Message],
        memory_texts: List[str]
    ) -> List[Message]:
        """将记忆注入到消息中"""
        if not memory_texts:
            return messages
        
        # 构建记忆上下文
        memory_context = "## 📚 相关记忆\n\n"
        for i, text in enumerate(memory_texts, 1):
            memory_context += f"{i}. {text}\n"
        memory_context += "\n---\n\n"
        
        # 注入到第一条用户消息
        for i, msg in enumerate(messages):
            if hasattr(msg, 'role') and msg.role == 'user' and msg.content:
                new_content = memory_context + msg.content
                messages[i] = Message(role=msg.role, content=new_content)
                break
        
        return messages

    def export(self, output_file: str = None) -> str:
        """导出记忆到 JSON"""
        import json
        
        memories = self.get_all()
        
        export_data = {
            'project_id': self.project_id,
            'exported_at': datetime.now().isoformat(),
            'total_count': len(memories),
            'memories': memories
        }
        
        if not output_file:
            output_file = os.path.join(self.memory_path, 'export.json')
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Exported {len(memories)} memories to {output_file}")
        return output_file
