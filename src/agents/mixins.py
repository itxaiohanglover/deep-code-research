"""Agent Mixins - 提供公共功能

设计原则：
1. 使用 Mixin 模式，避免创建基类
2. 保持 Agent 直接继承 LLMAgent
3. 通过多重继承组合功能
"""

import os
from pathlib import Path
from typing import Any, Optional

from ms_agent.utils import get_logger
from omegaconf import DictConfig

from src.utils.artifact_store import ArtifactStore
from src.utils.path_manager import PathManager
from src.utils.workflow_manager import workflow_manager

logger = get_logger()


def register_deepcode_memory():
    """注册 DeepCodeMemory 到 ms-agent 的 memory_mapping
    
    遵循 ms-agent 最佳实践：配置驱动
    - 将自定义 Memory 注册到框架的 memory_mapping
    - 在 YAML 配置中使用 `deepcode_memory` 名称
    - 基于 mem0ai（https://github.com/mem0ai/mem0）实现
    
    Usage:
        # 在项目启动时调用一次
        from src.agents.mixins import register_deepcode_memory
        register_deepcode_memory()
        
        # 然后在 YAML 配置中使用：
        # memory:
        # - name: deepcode_memory
    """
    try:
        from ms_agent.memory import memory_mapping
        from src.memory.deepcode_memory import DeepCodeMemory
        
        if 'deepcode_memory' not in memory_mapping:
            memory_mapping['deepcode_memory'] = DeepCodeMemory
            logger.info("✅ 已注册 deepcode_memory 到 ms-agent memory_mapping")
        
    except Exception as e:
        logger.warning(f"注册 deepcode_memory 失败: {e}")


def register_simple_memory():
    """注册 SimpleMemory（JSON 文件存储，不依赖 mem0）
    
    作为 DeepCodeMemory 的轻量级替代方案
    """
    try:
        from ms_agent.memory import memory_mapping
        # from src.memory.simple_memory import SimpleMemory
        
        if 'simple_memory' not in memory_mapping:
            # memory_mapping['simple_memory'] = SimpleMemory
            logger.info("✅ 已注册 simple_memory 到 ms-agent memory_mapping")
        
    except Exception as e:
        logger.warning(f"注册 simple_memory 失败: {e}")


class ArtifactStoreMixin:
    """ArtifactStore Mixin - 提供统一的产物存储访问
    
    职责：
    1. 统一管理 ArtifactStore 初始化（懒加载）
    2. 提供便捷的前序产物读取方法
    3. 避免在每个 Agent 中重复初始化代码
    
    Usage:
        class MyAgent(LLMAgent, ArtifactStoreMixin):
            async def run(self, inputs, **kwargs):
                # 直接使用 self.artifact_store 和 self._get_previous_artifact()
                requirements = self._get_previous_artifact("requirements")
                return await super().run(inputs, **kwargs)
    
    注意：
        - 需要 Agent 有 self.config 属性（LLMAgent 已提供）
        - ArtifactStore 是懒加载的，只在第一次访问时初始化
        - 产物保存应该由 ArtifactCallback 统一处理，Agent 只负责读取
    """
    
    @property
    def artifact_store(self) -> ArtifactStore:
        """获取 ArtifactStore 实例（懒加载）
        
        每次访问时确保迭代状态与 WorkflowManager 同步。
        
        Returns:
            ArtifactStore 实例
        """
        if not hasattr(self, '_artifact_store'):
            # 使用 PathManager 统一管理路径
            path_manager = PathManager.from_config(self.config)
            
            # 从环境变量获取 session_id（统一方式）
            session_id = os.getenv("SESSION_ID")
            
            # 初始化 ArtifactStore
            # 注意：path_manager.artifacts_dir 已经是 output/{session_id}/artifacts/
            # 所以不需要再传入 session_id，避免重复添加 session_id 子目录
            self._artifact_store = ArtifactStore(
                base_dir=path_manager.artifacts_dir,
                session_id=None,  # base_dir 已经包含 session_id，不需要再添加
            )
            
            logger.debug(
                f"[{self.tag}] 初始化 ArtifactStore: "
                f"base_dir={path_manager.artifacts_dir}, session_id={session_id}"
            )
        
        # 每次访问时同步迭代状态（确保与 WorkflowManager 同步）
        iteration = workflow_manager.get_iteration()
        if iteration is not None:
            self._artifact_store.set_iteration(iteration)
        
        return self._artifact_store
    
    @property
    def path_manager(self) -> PathManager:
        """获取 PathManager 实例（懒加载）
        
        Returns:
            PathManager 实例
        """
        if not hasattr(self, '_path_manager'):
            # 注意：config.output_dir 已经包含 session_id（由 ConfigHandler 设置）
            # 所以不要再传递 session_id，避免路径重复
            self._path_manager = PathManager.from_config(self.config, session_id=None)
        return self._path_manager
    
    def _get_previous_artifact(self, name: str, default: str = "") -> str:
        """获取前序产物（统一方法）
        
        Args:
            name: 产物名称（不含扩展名，会自动添加 .md）
            default: 默认值（如果产物不存在）
            
        Returns:
            产物内容
        """
        # 获取当前迭代，并确保 ArtifactStore 同步
        iteration = workflow_manager.get_iteration()
        if iteration is not None:
            self.artifact_store.set_iteration(iteration)
        
        # 自动添加 .md 扩展名（如果没有）
        artifact_name = name if name.endswith('.md') else f"{name}.md"
        return self.artifact_store.get(artifact_name, iteration=iteration, default=default)
    
    def _get_previous_artifact_json(self, name: str, default: Optional[dict] = None) -> Optional[dict]:
        """获取前序 JSON 产物（统一方法）
        
        Args:
            name: 产物名称（不含扩展名，会自动添加 .json）
            default: 默认值（如果产物不存在）
            
        Returns:
            JSON 数据（字典）
        """
        # 获取当前迭代，并确保 ArtifactStore 同步
        iteration = workflow_manager.get_iteration()
        if iteration is not None:
            self.artifact_store.set_iteration(iteration)
        
        # 自动添加 .json 扩展名（如果没有）
        artifact_name = name if name.endswith('.json') else f"{name}.json"
        return self.artifact_store.get_json(artifact_name, iteration=iteration, default=default)
    
    def _load_spec_kit(self) -> dict:
        """加载 Spec Kit（统一方法）
        
        步骤：
        1. 使用 SpecKitParser 解析 spec_kit_dir
        2. 返回完整的 Spec Kit 字典
        
        Returns:
            Spec Kit 字典（包含 constitution, spec, plan, tasks 等）
        """
        from src.tools.spec.parser import SpecKitParser
        
        parser = SpecKitParser(self.path_manager.spec_kit_dir)
        return parser.load()
    
    @property
    def tracker(self):
        """获取 SpecCodeTracker 实例（懒加载）
        
        统一管理 Spec-Code 追踪器初始化，避免在每个 Agent 中重复代码。
        
        Returns:
            SpecCodeTracker 实例
        """
        if not hasattr(self, '_tracker'):
            from src.tools.tracker.spec_code_tracker import SpecCodeTracker
            
            # 使用 PathManager 统一管理路径
            tracker_base = self.path_manager.output_dir
            if self.path_manager.session_id:
                tracker_base = tracker_base / self.path_manager.session_id
            self._tracker = SpecCodeTracker(tracker_base)
            logger.debug(
                f"[{self.tag}] 初始化 SpecCodeTracker: tracker_base={tracker_base}"
            )
        return self._tracker
    
    def _build_artifact_sections(self, artifacts: dict[str, str]) -> list[str]:
        """构建产物章节（用于提示词）
        
        注意：此方法已迁移到 src.prompts.risk_prompts.build_artifact_sections
        保留此方法以保持向后兼容，实际调用 prompts 模块中的函数。
        
        Args:
            artifacts: 产物字典，格式为 {名称: 内容}
            
        Returns:
            章节列表（Markdown 格式）
        """
        from src.prompts.risk_prompts import build_artifact_sections
        return build_artifact_sections(artifacts)


class RAGMixin:
    """RAG 功能 Mixin
    
    使用 SharedRAGService 共享 RAG 实例，避免每个 Agent 重复初始化。
    
    设计原则：
    1. 委托 SharedRAGService 管理所有 RAG 资源
    2. 知识库和用户文档只加载一次（由 SharedRAGService 管理）
    3. 简化 do_rag 逻辑，使用策略模式处理不同模式
    
    Usage:
        class MyAgent(RAGMixin, LLMAgent, ArtifactStoreMixin):
            # RAG 会在 LLMAgent.run 中自动调用 prepare_rag 和 do_rag
            pass
    
    注意：
        - 需要 Agent 有 self.config 和 self.tag 属性（LLMAgent 已提供）
        - 继承顺序：RAGMixin 必须在 LLMAgent 之前（以覆盖 prepare_rag/do_rag）
    """
    
    def __init__(self, *args, **kwargs):
        """初始化 Mixin"""
        super().__init__(*args, **kwargs)
        self._rag_applied = False
    
    async def prepare_rag(self):
        """覆盖父类的 prepare_rag 方法
        
        委托 SharedRAGService 处理所有初始化和加载逻辑。
        使用全局单例，避免重复初始化。
        
        注意：每次调用时重置 _rag_applied 标记，确保工作流回退时 RAG 可以再次应用。
        
        功能开关：通过 config.features.rag 控制是否启用 RAG
        """
        # 重置 _rag_applied 标记
        self._rag_applied = False
        
        # 检查 features.rag 开关（优先级最高）
        features = getattr(self.config, 'features', None)
        if features is not None:
            rag_enabled = getattr(features, 'rag', True)  # 默认 True（向后兼容）
            if not rag_enabled:
                logger.debug(f"[{self.tag}] RAG 功能已禁用 (features.rag=false)")
                return
        
        # 获取 RAG 配置
        rag_config = getattr(self.config, 'rag', None)
        if rag_config is None:
            logger.debug(f"[{self.tag}] 配置中未启用 RAG")
            return
        
        from src.tools.rag import shared_rag_service
        
        try:
            # 检查是否已有共享实例（单例模式：只初始化一次）
            if shared_rag_service.rag is not None:
                # 直接使用共享实例，不重复初始化
                self.rag = shared_rag_service.rag
                logger.info(f"[{self.tag}] 🔗 复用 RAG 服务")
            else:
                # 首次初始化
                logger.info(f"[{self.tag}] 🔍 初始化 RAG 服务 (name: {getattr(rag_config, 'name', 'unknown')})")
                await shared_rag_service.initialize(self.config)
                
                if shared_rag_service.rag is None:
                    logger.error(f"[{self.tag}] ❌ RAG 服务初始化失败")
                    return
                
                self.rag = shared_rag_service.rag
                logger.info(f"[{self.tag}] ✅ RAG 服务初始化完成")
            
            # 加载知识库和用户文档（如果尚未加载）
            await self._ensure_documents_loaded()
            
        except Exception as e:
            logger.error(f"[{self.tag}] ❌ RAG 初始化失败: {e}")
            self.rag = None
    
    async def _ensure_documents_loaded(self):
        """确保文档已加载（委托给 SharedRAGService）"""
        from src.tools.rag import shared_rag_service
        
        # 加载知识库
        kb_count = await shared_rag_service.load_knowledge_base(self.config)
        if kb_count > 0:
            logger.info(f"[{self.tag}] 📚 知识库: {kb_count} 个文档")
        
        # 加载用户文档
        await self._load_user_documents()
    
    async def _load_user_documents(self):
        """加载用户上传的文档"""
        from src.tools.rag import shared_rag_service
        
        # 如果已加载，跳过
        if shared_rag_service._user_docs_loaded:
            logger.debug(f"[{self.tag}] 用户文档已加载，跳过")
            return
        
        # 检查配置
        rag_config = getattr(self.config, 'rag', None)
        if not rag_config:
            logger.debug(f"[{self.tag}] 无 RAG 配置，跳过用户文档")
            return
        
        knowledge_sources = getattr(rag_config, 'knowledge_sources', None)
        if not knowledge_sources:
            logger.debug(f"[{self.tag}] 无 knowledge_sources 配置，跳过用户文档")
            return
        
        uploads_config = getattr(knowledge_sources, 'uploads', None)
        if not uploads_config or not getattr(uploads_config, 'enabled', False):
            logger.debug(f"[{self.tag}] uploads 未启用，跳过用户文档")
            return
        
        try:
            from src.tools.document.processor import DocumentProcessor
            from src.utils.path_manager import PathManager
            
            # 获取 uploads 目录（优先使用已有的 path_manager，确保 session_id 正确）
            path_manager = getattr(self, 'path_manager', None)
            if path_manager is None:
                # 回退：从环境变量获取
                path_manager = PathManager.from_env()
            
            uploads_dir = path_manager.uploads_dir
            logger.info(f"[{self.tag}] 📁 扫描用户文档: {uploads_dir}")
            
            if not uploads_dir.exists():
                logger.info(f"[{self.tag}] 📁 uploads 目录不存在")
                shared_rag_service._user_docs_loaded = True
                return
            
            # 收集支持的文件
            supported_extensions = {'.pdf', '.docx', '.doc', '.pptx', '.ppt', '.txt', '.md'}
            file_paths = [
                str(f) for f in uploads_dir.iterdir()
                if f.is_file() and f.suffix.lower() in supported_extensions
            ]
            
            if not file_paths:
                logger.info(f"[{self.tag}] 📁 无用户文档")
                shared_rag_service._user_docs_loaded = True
                return
            
            # 显示解析信息
            file_names = [Path(fp).name for fp in file_paths]
            logger.info(f"[{self.tag}] 📄 解析用户文档: {', '.join(file_names)}")
            
            # 处理文档
            processor = DocumentProcessor(
                upload_root=uploads_dir,
                enable_vision=True,
                enable_ocr=True,
            )
            summary = processor.process(file_paths)
            
            # 统计结果
            success_count = sum(1 for f in summary.get("files", []) if f.get("status") == "success")
            total_count = len(file_paths)
            if success_count == total_count:
                logger.info(f"[{self.tag}] ✅ 用户文档解析成功 ({success_count}/{total_count})")
            else:
                logger.warning(f"[{self.tag}] ⚠️ 用户文档解析部分失败 ({success_count}/{total_count} 成功)")
            
            # 添加到 RAG
            docs = [
                {"filename": f.get("filename", "unknown"), "content": f.get("content", "")}
                for f in summary.get("files", [])
                if f.get("status") == "success" and f.get("content")
            ]
            
            if docs:
                count = await shared_rag_service.add_user_documents(docs)
                if count > 0:
                    logger.info(f"[{self.tag}] 📄 用户文档: {count} 个")
            
        except Exception as e:
            # 用户文档加载失败是可恢复错误，记录警告但不终止流程
            from src.utils.exceptions import DocumentProcessingError
            logger.warning(f"[{self.tag}] 加载用户文档失败（可恢复）: {e}")
            # 不抛出异常，继续执行（没有用户文档的 RAG 增强）
        finally:
            shared_rag_service._user_docs_loaded = True
    
    async def do_rag(self, messages):
        """覆盖父类 do_rag，正确处理 retrieve_only 模式
        
        策略：
        - retrieve_only=False: 使用 query 模式（LLM 增强）
        - retrieve_only=True: 使用 retrieve 模式（纯检索，整合到 prompt）
        """
        # 检查前置条件
        if not self._should_apply_rag(messages):
            return
        
        rag_config = getattr(self.config, 'rag', None)
        retrieve_only = getattr(rag_config, 'retrieve_only', False) if rag_config else False
        
        # 获取用户查询
        user_query = self._get_user_query(messages)
        if not user_query:
            logger.warning(f"[{self.tag}] ⚠️ 未找到用户消息，跳过 RAG")
            return
        
        logger.info(f"[{self.tag}] 🔍 RAG 检索 (retrieve_only={retrieve_only})")
        
        try:
            if retrieve_only:
                await self._do_retrieve_only(messages, user_query)
            else:
                await self._do_query_mode(messages, user_query)
        except Exception as e:
            # RAG 失败是可恢复错误，记录日志但不终止流程
            from src.utils.exceptions import RAGError
            logger.error(f"[{self.tag}] ❌ RAG 失败（可恢复）: {e}")
            # 不抛出异常，让 Agent 继续执行（使用没有 RAG 增强的输入）
    
    def _should_apply_rag(self, messages) -> bool:
        """检查是否应该应用 RAG"""
        # RAG 未初始化
        if self.rag is None:
            return False
        
        # 已经应用过
        if self._rag_applied:
            logger.debug(f"[{self.tag}] RAG 已应用，跳过")
            return False
        
        # 工具调用循环中（messages > 2 且最后不是新的 user 消息）
        if len(messages) > 2:
            last_msg = messages[-1] if messages else None
            if not (last_msg and hasattr(last_msg, 'role') and last_msg.role == 'user'):
                logger.debug(f"[{self.tag}] 工具调用循环中，跳过 RAG")
                return False
        
        return True
    
    def _get_user_query(self, messages) -> str:
        """获取最后一条用户消息"""
        for msg in reversed(messages):
            if hasattr(msg, 'role') and msg.role == 'user' and hasattr(msg, 'content'):
                return msg.content
        return ""
    
    async def _do_query_mode(self, messages, user_query: str):
        """Query 模式：使用 LLM 增强"""
        enhanced_content = await self.rag.query(user_query)
        self._update_user_message(messages, enhanced_content)
        self._rag_applied = True
        logger.info(f"[{self.tag}] ✅ RAG query 完成")
    
    async def _do_retrieve_only(self, messages, user_query: str):
        """Retrieve-only 模式：检索并整合到 prompt
        
        优化策略（Phase 2）：
        1. 使用 Reranker 重排序提升相关性
        2. 可选启用 Query Expansion 多路召回
        """
        from src.tools.rag import shared_rag_service
        
        query = user_query[:500]  # 截断长查询
        
        # 获取 RAG 配置
        rag_config = getattr(self.config, 'rag', None)
        use_rerank = getattr(rag_config, 'use_rerank', True) if rag_config else True
        use_expansion = getattr(rag_config, 'use_expansion', False) if rag_config else False
        
        # 选择检索方式
        if use_expansion:
            # 使用查询扩展（更全面但更慢）
            results = await shared_rag_service.retrieve_with_expansion(
                query=query,
                limit=5,
                expansion_limit=10,
            )
        else:
            # 普通检索（可选重排序）
            results = await shared_rag_service.retrieve(
                query=query,
                limit=5,
                score_threshold=0.0,
                use_rerank=use_rerank,
            )
        
        if not results:
            logger.warning(f"[{self.tag}] ⚠️ RAG 未检索到结果")
            return
        
        context = self._format_rag_results(results)
        if context:
            enhanced = f"## 📚 知识库参考\n\n{context}\n\n---\n\n"
            self._prepend_to_user_message(messages, enhanced)
            self._rag_applied = True
            logger.info(f"[{self.tag}] ✅ RAG retrieve 完成 ({len(results)} 条, rerank={use_rerank})")
    
    def _update_user_message(self, messages, new_content: str):
        """更新最后一条用户消息（确保格式正确）"""
        for msg in reversed(messages):
            if hasattr(msg, 'role') and msg.role == 'user':
                # 统一转换为字符串格式（避免 multimodal 格式问题）
                if isinstance(new_content, str):
                    msg.content = new_content
                elif isinstance(new_content, list):
                    # 如果是列表，提取所有文本内容合并
                    text_parts = []
                    for item in new_content:
                        if isinstance(item, dict) and 'text' in item:
                            text_parts.append(item['text'])
                        elif isinstance(item, str):
                            text_parts.append(item)
                    msg.content = '\n'.join(text_parts)
                return
    
    def _prepend_to_user_message(self, messages, prefix: str):
        """在用户消息前添加内容（正确处理 multimodal 格式）"""
        for msg in reversed(messages):
            if hasattr(msg, 'role') and msg.role == 'user':
                # 处理不同格式的 content
                if isinstance(msg.content, str):
                    # 字符串格式：直接拼接
                    msg.content = prefix + msg.content
                elif isinstance(msg.content, list):
                    # 列表格式（multimodal）：确保所有元素都有正确的格式
                    normalized_content = []
                    for item in msg.content:
                        if isinstance(item, dict):
                            # 如果已经是字典，确保有 type 字段
                            if 'type' not in item:
                                # 如果有 text 字段但没有 type，补充 type
                                if 'text' in item:
                                    item['type'] = 'text'
                                else:
                                    # 格式不正确，跳过
                                    logger.warning(f"[{self.tag}] 跳过格式不正确的 content 项: {item}")
                                    continue
                            normalized_content.append(item)
                        elif isinstance(item, str):
                            # 如果是字符串，转换为正确的格式
                            normalized_content.append({"type": "text", "text": item})
                        else:
                            logger.warning(f"[{self.tag}] 跳过未知类型的 content 项: {type(item)}")
                    
                    # 在前面插入新的文本内容
                    msg.content = [{"type": "text", "text": prefix}] + normalized_content
                return
    
    def _format_rag_results(self, results: list) -> str:
        """格式化 RAG 检索结果"""
        parts = []
        for i, r in enumerate(results, 1):
            text = r.get('text', '')[:800]
            score = r.get('score', 0)
            if text.strip():
                parts.append(f"### 参考 {i} (相关度: {score:.2f})\n{text}")
        return "\n\n".join(parts)
    
