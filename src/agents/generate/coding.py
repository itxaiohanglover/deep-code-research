"""编码阶段 Agent：根据编码任务进行编码实现

职责：
1. 根据规划任务生成实际的代码文件
2. 使用代码块格式输出（```type: filename）
3. 通过 ArtifactCallback 自动保存代码文件

关键：必须输出真实的代码，而不是规划文档或总结！
"""

import json
from pathlib import Path
from typing import Any, Dict, List

from ms_agent.utils import get_logger
from omegaconf import DictConfig

from src.agents._base_agent import BaseAgent
from src.prompts.coding_prompts import build_coding_prompt
from src.utils.workflow_manager import workflow_manager

logger = get_logger()


class CodingAgent(BaseAgent):
    """编码阶段 Agent
    
    职责：
    1. 根据规划任务生成实际的代码文件
    2. 使用代码块格式输出（```type: filename）
    3. 通过 ArtifactCallback 自动保存代码文件
    
    关键：必须输出真实的代码，而不是规划文档或总结！
    """
    
    # 禁用缓存，确保每次都重新生成代码
    ENABLE_CACHE = False

    def __init__(self, config: DictConfig, tag: str = "coding", **kwargs):
        super().__init__(config, tag, **kwargs)
        
        # 使用 PathManager 统一管理路径
        self.spec_kit_dir = self.path_manager.spec_kit_dir
        self.repo_dir = self.path_manager.repo_dir
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        
        # SpecCodeTracker 由 ArtifactStoreMixin 统一管理，直接使用 self.tracker
    
    def _load_planning_mapping(self) -> Dict[str, List[str]]:
        """加载 Planning Agent 生成的映射关系
        
        步骤：
        1. 从文件加载映射关系
        2. 如果失败，返回空字典
        
        Returns:
            映射字典：task_id -> [code_files]
        """
        from src.utils.agent_utils import load_mapping_from_file
        
        mapping = load_mapping_from_file(self.repo_dir / "spec_code_mapping.json")
        if mapping:
            logger.info(f"[{self.tag}] 加载 Planning 映射关系: {len(mapping)} 个任务")
        return mapping or {}
    
    def _get_task_for_file(self, file_path: str, mapping: Dict[str, List[str]]) -> List[str]:
        """根据文件路径获取对应的任务 ID
        
        Args:
            file_path: 代码文件路径
            mapping: 映射字典
        
        Returns:
            任务 ID 列表
        """
        task_ids = []
        file_path_normalized = str(Path(file_path).as_posix())
        
        for task_id, code_files in mapping.items():
            for code_file in code_files:
                if str(Path(code_file).as_posix()) == file_path_normalized:
                    task_ids.append(task_id)
        
        return task_ids
    
    def _build_prompt(self, user_input: str) -> str:
        """构建编码提示词
        
        参考 code_scratch/callbacks/coding_callback.py 的逻辑
        """
        # 获取规划结果
        planning_output = self._get_previous_artifact("planning", default="")
        
        # 加载 Planning 生成的映射关系
        planning_mapping = self._load_planning_mapping()
        
        # 获取 Spec Kit（完整内容，使用 Mixin 提供的方法）
        spec_kit = self._load_spec_kit()
        
        # 项目章程必须完整参考（百分百）
        if not spec_kit.get("constitution", ""):
            logger.warning(f"[{self.tag}] 未找到项目章程，编码可能不符合规范")
        
        # 获取回退上下文（如果有）
        rollback_context = workflow_manager.get_rollback_context()
        if rollback_context and rollback_context.get("target_agent") == "coding":
            logger.info(f"[{self.tag}] 检测到回退上下文: {rollback_context.get('reason', '未知原因')}")
        
        # 使用 prompts 模块构建提示词
        return build_coding_prompt(
            user_input=user_input if user_input else "请根据规划任务生成代码",
            planning_output=planning_output if planning_output else None,
            planning_mapping=planning_mapping,
            spec_kit=spec_kit,
            rollback_context=rollback_context
        )
    
    # 使用 BaseAgent 的默认 run 方法，无需重写
    # 注意：代码文件与 Spec Kit 的映射关系应该由 Callback 在保存文件时建立
