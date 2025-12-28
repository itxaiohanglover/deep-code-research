"""需求分析 Agent - Phase 1"""

from typing import List

from ms_agent.utils import get_logger

from src.agents._base_agent import BaseAgent
from src.prompts.requirements_prompts import build_requirements_prompt

logger = get_logger()


class RequirementsAgent(BaseAgent):
    """需求分析 Agent
    
    职责：
    1. 深入剖析用户的原始需求
    2. 输出结构化、详尽且可执行的需求分析报告
    3. 支持迭代优化（如果存在前序需求分析结果）
    
    使用 ArtifactStoreMixin 提供统一的产物存储访问。
    产物保存由 ArtifactCallback 统一处理，Agent 只负责读取。
    
    产物依赖：
    - requirements（可选）：前序需求分析结果，用于迭代优化
    """
    
    # 声明依赖的前序产物（迭代场景：读取自己的历史版本）
    ARTIFACT_DEPENDENCIES: List[str] = ["requirements"]
    
    def _build_prompt(self, user_input: str) -> str:
        """构建需求分析提示词
        
        步骤：
        1. 通过 ARTIFACT_DEPENDENCIES 自动获取前序产物
        2. 如果存在前序 requirements，进行迭代优化
        3. 如果不存在，直接分析用户输入
        """
        artifacts = self._get_artifacts()
        previous = artifacts.get("requirements", "")
        
        if previous:
            logger.info(f"[{self.tag}] 检测到前序需求分析结果，将进行迭代优化")
        
        return build_requirements_prompt(
            user_input=user_input,
            previous_requirements=previous if previous else None
        )
