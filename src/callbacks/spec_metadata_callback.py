"""Spec 元数据回调

职责：
1. 在 SpecGenAgent 任务结束时，自动生成 spec_metadata.json
2. 从消息中提取 spec_kit 文件内容进行解析
3. 提取模块和任务信息，构建结构化元数据

设计原则：
- 回调负责所有元数据生成逻辑（从 SpecGenAgent 中分离）
- 优先从消息中提取内容，避免文件 I/O 依赖
- 支持从磁盘文件作为后备方案
"""

from typing import List, Optional, Tuple, Dict, Any
from pathlib import Path
import json
import os
import re
from datetime import datetime

from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks import Callback
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig

from src.tools.spec.parser import SpecKitParser
from src.tools.code.file_parser import extract_code_blocks
from src.utils.workflow_manager import workflow_manager

from src.utils.path_manager import PathManager

logger = get_logger()


class SpecMetadataCallback(Callback):
    """Spec 元数据回调
    
    职责：
    1. 在 SpecGenAgent 任务结束时，解析生成的 Spec Kit 文档
    2. 提取模块和任务信息
    3. 生成 spec_metadata.json
    
    工作流程：
    1. 从消息中提取 spec_kit 代码块（tasks.md, spec.md 等）
    2. 使用 SpecKitParser 解析内容
    3. 构建结构化元数据
    4. 保存到 spec_kit/spec_metadata.json
    """
    
    def __init__(self, config: DictConfig):
        super().__init__(config)
        # 使用 PathManager 统一管理路径
        # 注意：config.output_dir 已经包含 session_id（由 ConfigHandler 设置）
        path_manager = PathManager.from_config(config, session_id=None)
        self.spec_kit_dir = path_manager.spec_kit_dir
        self.spec_kit_dir.mkdir(parents=True, exist_ok=True)
    
        # 防止重复生成元数据的标记
        # 由于 SpecGenAgent 为每个文档单独调用 LLM，on_task_end 会被触发多次
        self._metadata_generated = False
        
        logger.info(f"[SpecMetadataCallback] 初始化完成，spec_kit_dir={self.spec_kit_dir}")
    
    def _extract_spec_kit_from_messages(self, messages: List[Message]) -> Dict[str, str]:
        """从消息中提取所有 spec_kit 文件内容
        
        Args:
            messages: 消息列表
            
        Returns:
            文件名到内容的映射字典
        """
        # 合并所有消息内容
        content = '\n'.join([m.content for m in messages if m.content])
        
        # 使用 file_parser 提取代码块
        code_blocks, _ = extract_code_blocks(content)
        
        spec_kit_files = {}
        target_files = ['tasks.md', 'spec.md', 'constitution.md', 'plan.md']
        
        for block in code_blocks:
            filename = block.get('filename', '').lower()
            code = block.get('code', '')
            
            for target in target_files:
                if target in filename:
                    spec_kit_files[target] = code
                    logger.debug(f"[SpecMetadataCallback] 从消息中提取到 {target} ({len(code)} 字符)")
                    break
        
        return spec_kit_files
    
    def _get_module_for_task(self, task_id: str) -> Optional[str]:
        """根据任务ID推断模块ID
        
        支持的格式：
        - Task-X.Y -> module_X
        - task_N -> module_N
        
        Args:
            task_id: 任务ID
            
        Returns:
            模块ID，如果无法推断则返回 None
        """
        # 匹配 Task-X.Y 格式
        match = re.match(r'Task-(\d+)\.\d+', task_id)
        if match:
            return f"module_{match.group(1)}"
        
        # 匹配 task_N 格式（向后兼容）
        match = re.match(r'task_(\d+)', task_id)
        if match:
            return f"module_{match.group(1)}"
        
        return None
    
    def _build_metadata(
        self,
        modules: List[Dict[str, Any]],
        tasks: List[Dict[str, Any]],
        iteration: int
    ) -> Dict[str, Any]:
        """构建元数据结构
        
        Args:
            modules: 模块列表
            tasks: 任务列表
            iteration: 当前迭代号
            
        Returns:
            结构化的元数据字典
        """
        # 构建元数据
        metadata = {
            'spec_kit_version': '1.0.0',
            'generated_at': datetime.now().isoformat(),
            'project_id': 'deepcode_project',
            'iteration': iteration,
            'modules': [
                {
                    'id': module['id'],
                    'name': module['name'],
                    'tasks': [
                        {
                            'id': task['id'],
                            'description': task['description'],
                            'dependencies': task.get('dependencies', [])
                        }
                        for task in tasks
                        if self._get_module_for_task(task['id']) == module['id']
                    ]
                }
                for module in modules
            ],
            'tasks': [
                {
                    'id': task['id'],
                    'description': task['description'],
                    'dependencies': task.get('dependencies', [])
                }
                for task in tasks
            ]
        }
        
        # 如果没有模块但有任务，使用默认模块
        if not metadata['modules'] and tasks:
            metadata['modules'] = [{
                'id': 'module_default',
                'name': '默认模块',
                'tasks': [
                    {
                        'id': task['id'],
                        'description': task['description'],
                        'dependencies': task.get('dependencies', [])
                    }
                    for task in tasks
                ]
            }]
        
        return metadata
    
    def _has_tasks_content(self, messages: List[Message]) -> bool:
        """检查 tasks.md 是否已生成
        
        由于 SpecGenAgent 直接保存文件到磁盘（不再使用代码块格式），
        检查 spec_kit_dir 中是否存在 tasks.md 文件。
        
        Args:
            messages: 消息列表（不再使用，保留参数以兼容接口）
            
        Returns:
            tasks.md 是否存在
        """
        tasks_file = self.spec_kit_dir / 'tasks.md'
        return tasks_file.exists() and tasks_file.stat().st_size > 0
    
    async def on_task_end(self, runtime: Runtime, messages: List[Message]):
        """任务结束时生成 Spec 元数据
        
        注意：由于 SpecGenAgent 为每个文档单独调用 LLM，
        on_task_end 会被触发多次。只有当 tasks.md 存在时才生成元数据。
        
        防重复机制：
        - 使用 _metadata_generated 标记防止同一会话内重复生成
        - 检查 spec_metadata.json 是否已存在且有效
        
        设计变更（2024-12）：
        - SpecGenAgent 现在直接保存文件到磁盘（不再使用代码块格式）
        - 因此改为直接从磁盘读取文件，而不是从消息中提取代码块
        """
        logger.debug(f"[SpecMetadataCallback] on_task_end 被调用 (runtime.tag={runtime.tag})")
        
        if runtime.tag != 'spec_gen':
            return
        
        # 防止重复生成（同一会话内）
        if self._metadata_generated:
            logger.debug("[SpecMetadataCallback] 元数据已生成过，跳过")
            return
        
        # 检查 tasks.md 是否已生成
        if not self._has_tasks_content(messages):
            logger.debug("[SpecMetadataCallback] tasks.md 尚未生成，跳过元数据生成")
            return
        
        # 检查 spec_metadata.json 是否已存在且有效
        metadata_file = self.spec_kit_dir / 'spec_metadata.json'
        if metadata_file.exists():
            try:
                existing_metadata = json.loads(metadata_file.read_text(encoding='utf-8'))
                # 如果已有有效的元数据（有任务），跳过重新生成
                if existing_metadata.get('tasks'):
                    logger.debug("[SpecMetadataCallback] spec_metadata.json 已存在且有效，跳过重新生成")
                    self._metadata_generated = True
                    return
            except (json.JSONDecodeError, Exception):
                # 文件损坏或无效，继续重新生成
                pass
        
        logger.info("[SpecMetadataCallback] 开始生成 Spec 元数据")
        
        try:
            # 1. 创建 SpecKitParser 实例并从文件加载
            parser = SpecKitParser(self.spec_kit_dir)
            parser.load()
            logger.info("[SpecMetadataCallback] 从文件加载 spec_kit")
            
            # 2. 提取模块和任务
            modules = parser.extract_modules()
            tasks = parser.extract_tasks()
            
            logger.info(f"[SpecMetadataCallback] 解析结果: {len(modules)} 个模块, {len(tasks)} 个任务")
            if modules:
                logger.debug(f"[SpecMetadataCallback] 模块列表: {[m['id'] for m in modules]}")
            if tasks:
                logger.debug(f"[SpecMetadataCallback] 任务列表: {[t['id'] for t in tasks[:5]]}{'...' if len(tasks) > 5 else ''}")
            
            # 3. 获取当前迭代
            iteration = workflow_manager.get_iteration() or 1
            
            # 4. 构建元数据
            metadata = self._build_metadata(modules, tasks, iteration)
            
            # 5. 保存元数据
            metadata_file = self.spec_kit_dir / 'spec_metadata.json'
            metadata_file.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
            
            # 6. 标记为已生成
            self._metadata_generated = True
            
            # 7. 记录日志
            logger.info(f"[SpecMetadataCallback] ✅ 已保存 Spec 元数据: {metadata_file}")
            logger.info(f"[SpecMetadataCallback] 元数据内容: {len(metadata.get('modules', []))} 个模块, {len(metadata.get('tasks', []))} 个任务")
            
            # 检查是否有空模块或空任务
            self._log_warnings(metadata)
            
        except Exception as e:
            logger.error(f"[SpecMetadataCallback] ❌ 生成 Spec 元数据失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())
    
    def _log_warnings(self, metadata: Dict[str, Any]) -> None:
        """记录元数据相关的警告信息
        
        Args:
            metadata: 元数据字典
        """
        empty_modules = [m for m in metadata.get('modules', []) if not m.get('tasks')]
        if empty_modules:
            logger.warning(
                f"[SpecMetadataCallback] ⚠️ 发现 {len(empty_modules)} 个空模块（无关联任务）: "
                f"{[m['id'] for m in empty_modules]}"
            )
        
        if not metadata.get('tasks'):
            logger.error(
                "[SpecMetadataCallback] ❌ 警告：未提取到任何任务！请检查 tasks.md 格式是否正确"
            )
        if not metadata.get('modules'):
            logger.warning(
                "[SpecMetadataCallback] ⚠️ 警告：未提取到任何模块，将使用默认模块"
            )

