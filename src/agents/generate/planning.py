"""规划阶段 Agent：根据 spec kit 任务，生成编码任务规划并建立映射关系

参考 code_scratch 的 architecture.yaml 和 coding.yaml：
1. 从 Spec Kit 解析任务和模块（包括 spec_metadata.json）
2. 生成文件列表（files.json）
3. 生成任务分组（按依赖关系分组）
4. 建立 Spec Kit -> Repo 的映射关系并保存
"""

import json
import re
from typing import Any, Dict, List

from ms_agent.utils import get_logger
from omegaconf import DictConfig

from src.agents._base_agent import BaseAgent
from src.prompts.planning_prompts import build_planning_prompt
from src.tools.spec.parser import SpecKitParser

logger = get_logger()


class PlanningAgent(BaseAgent):
    """规划阶段 Agent（直接继承 LLMAgent，使用 Mixin）
    
    职责：
    1. 解析 Spec Kit，提取任务和模块（包括 spec_metadata.json）
    2. 生成文件列表（files.json）
    3. 生成任务分组规划（按依赖关系分组，3-5个文件一组）
    4. 建立 Spec Kit -> Repo 的映射关系并保存到 spec_code_mapping.json
    
    使用 ArtifactStoreMixin 提供统一的产物存储访问。
    产物保存由 ArtifactCallback 统一处理，Agent 只负责读取。
    """

    def __init__(self, config: DictConfig, tag: str = "planning", **kwargs):
        super().__init__(config, tag, **kwargs)
        # 使用 PathManager 统一管理路径
        self.spec_kit_dir = self.path_manager.spec_kit_dir
        self.repo_dir = self.path_manager.repo_dir
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        
        # SpecCodeTracker 由 ArtifactStoreMixin 统一管理，直接使用 self.tracker
    
    def _load_spec_metadata(self) -> Dict:
        """加载 Spec Kit 元数据"""
        metadata_file = self.spec_kit_dir / "spec_metadata.json"
        if metadata_file.exists():
            try:
                return json.loads(metadata_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"[{self.tag}] 加载 spec_metadata.json 失败: {e}")
        return {}
    
    def _save_mapping(self, mapping: Dict[str, List[str]]):
        """保存映射关系到追踪器和文件
        
        步骤：
        1. 保存到追踪器
        2. 保存到文件（供 Coding Agent 使用）
        
        Args:
            mapping: 映射字典
        """
        # 1. 保存到追踪器
        for task_id, code_files in mapping.items():
            self.tracker.add_spec_code_mapping(task_id, code_files)
        
        # 2. 保存到文件（供 Coding Agent 使用）
        from src.utils.agent_utils import save_mapping_to_file
        
        mapping_file = self.repo_dir / "spec_code_mapping.json"
        save_mapping_to_file(mapping, mapping_file, tag=self.tag)
    
    def _build_prompt(self, user_input: str) -> str:
        """构建规划提示词
        
        参考 code_scratch/coding.yaml 的 prompt 设计
        """
        logger.debug(f"[{self.tag}] 构建规划提示词")
        # 加载 Spec Kit（使用 Mixin 提供的方法）
        spec_kit = self._load_spec_kit()
        spec_metadata = self._load_spec_metadata()
        
        # 解析任务和模块（需要解析器）
        parser = SpecKitParser(self.spec_kit_dir)
        tasks = parser.extract_tasks()
        modules = parser.extract_modules()
        
        # 如果有元数据，优先使用元数据中的任务信息
        if spec_metadata and "modules" in spec_metadata:
            # 从元数据中提取任务
            metadata_tasks = []
            for module in spec_metadata["modules"]:
                if "tasks" in module:
                    metadata_tasks.extend(module["tasks"])
            if metadata_tasks:
                tasks = metadata_tasks
                logger.info(f"[{self.tag}] 使用 spec_metadata.json 中的任务信息: {len(tasks)} 个任务")
        
        # 生成文件结构建议
        file_structure = parser.get_file_structure()
        
        # 使用 prompts 模块构建提示词
        return build_planning_prompt(
            user_input=user_input,
            spec_kit=spec_kit,
            spec_metadata=spec_metadata,
            tasks=tasks,
            file_structure=file_structure
        )
    
    async def run(self, inputs: Any, **kwargs: Any) -> Any:
        """运行 Agent（重写以添加映射关系建立逻辑）
        
        步骤：
        1. 调用父类方法执行 Agent
        2. 提取输出内容
        3. 尝试从输出中提取映射关系
        4. 如果失败，尝试从文件读取
        5. 如果仍然失败，从 spec_metadata.json 自动生成
        6. 保存映射关系
        """
        # 1. 调用父类方法执行 Agent
        result = await super().run(inputs, **kwargs)
        
        # 2. 提取输出内容
        from src.utils.agent_utils import (
            extract_message_content,
            extract_mapping_from_output,
            load_mapping_from_file,
        )
        
        output = extract_message_content(result)
        
        # 3. 尝试从输出中提取映射关系
        mapping = extract_mapping_from_output(output, tag=self.tag)
        
        # 4. 如果失败，尝试从文件读取
        if not mapping:
            logger.warning(f"[{self.tag}] 未能从输出中提取映射关系，将尝试从文件读取")
            mapping = load_mapping_from_file(self.repo_dir / "spec_code_mapping.json")
        
        # 5. 如果仍然失败，从 spec_metadata.json 自动生成
        if not mapping:
            logger.warning(f"[{self.tag}] 文件中也未找到映射，将从 spec_metadata.json 自动生成")
            mapping = self._generate_mapping_from_metadata()
        
        # 6. 保存映射关系
        if mapping:
            self._save_mapping(mapping)
            logger.info(f"[{self.tag}] ✅ 规划完成，已建立 {len(mapping)} 个任务的映射关系")
        else:
            logger.warning(f"[{self.tag}] ⚠️ 未能建立映射关系，后续 coding 阶段可能受影响")
        
        return result
    
    def _generate_mapping_from_metadata(self) -> Dict[str, List[str]]:
        """从 spec_metadata.json 自动生成映射关系
        
        策略：
        1. 读取 spec_metadata.json 中的 tasks
        2. 从每个任务的 content 中提取"创建/修改文件"列表
        3. 生成任务到文件的映射
        
        Returns:
            映射字典 {task_id: [file_paths]}
        """
        mapping = {}
        
        try:
            metadata = self._load_spec_metadata()
            if not metadata:
                logger.warning(f"[{self.tag}] spec_metadata.json 为空或不存在")
                return {}
            
            tasks = metadata.get("tasks", [])
            
            for task in tasks:
                task_id = task.get("id", "")
                if not task_id:
                    continue
                
                # 从任务内容中提取文件列表
                content = task.get("content", "")
                files = self._extract_files_from_content(content)
                
                if files:
                    # 添加 repo/ 前缀（如果没有）
                    normalized_files = []
                    for f in files:
                        if not f.startswith(("repo/", "spec_kit/", "skills/")):
                            normalized_files.append(f"repo/{f}")
                        else:
                            normalized_files.append(f)
                    mapping[task_id] = normalized_files
            
            if mapping:
                logger.info(f"[{self.tag}] ✅ 从 spec_metadata.json 自动生成 {len(mapping)} 个任务的映射")
            else:
                logger.warning(f"[{self.tag}] 无法从 spec_metadata.json 生成映射")
            
        except Exception as e:
            logger.error(f"[{self.tag}] 从 spec_metadata.json 生成映射失败: {e}")
        
        return mapping
    
    def _extract_files_from_content(self, content: str) -> List[str]:
        """从任务内容中提取文件列表
        
        支持的格式：
        - **创建/修改文件**:
          - `index.html`
          - `README.md`
        
        Args:
            content: 任务内容
            
        Returns:
            文件路径列表
        """
        files = []
        
        # 查找"创建/修改文件"部分
        pattern = r'创建/修改文件[：:]\s*\n((?:\s*-\s*`[^`]+`\s*\n?)+)'
        match = re.search(pattern, content)
        
        if match:
            files_section = match.group(1)
            # 提取反引号中的文件名
            file_pattern = r'`([^`]+)`'
            files = re.findall(file_pattern, files_section)
        
        # 如果没找到，尝试备用模式
        if not files:
            # 查找任何 .html, .md, .json, .py 等文件
            file_pattern = r'`([^`]+\.(?:html|md|json|py|js|css|txt))`'
            files = re.findall(file_pattern, content)
        
        return files
