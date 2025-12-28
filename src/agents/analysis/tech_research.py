"""技术调研 Agent - Phase 2"""

from typing import List

from ms_agent.utils import get_logger

from src.agents._base_agent import BaseAgent
from src.prompts.tech_research_prompts import build_tech_research_prompt

logger = get_logger()


class TechResearchAgent(BaseAgent):
    """技术调研 Agent
    
    职责：
    1. 基于需求分析结果，进行深入的技术调研
    2. 推荐合适的技术栈、框架和工具
    3. 提供技术选型建议
    
    使用 ArtifactStoreMixin 提供统一的产物存储访问。
    产物保存由 ArtifactCallback 统一处理，Agent 只负责读取。
    
    产物依赖：
    - requirements：需求分析结果
    """
    
    # 声明依赖的前序产物
    ARTIFACT_DEPENDENCIES: List[str] = ["requirements"]
    
    def _build_prompt(self, user_input: str) -> str:
        """构建技术调研提示词
        
        步骤：
        1. 通过 ARTIFACT_DEPENDENCIES 自动获取前序产物
        2. 如果存在 requirements，基于需求进行技术调研
        3. 如果不存在，使用原始输入作为回退
        """
        artifacts = self._get_artifacts()
        requirements = artifacts.get("requirements", "")
        
        if requirements:
            logger.info(f"[{self.tag}] 获取到需求分析结果，开始技术调研")
        
        return build_tech_research_prompt(
            user_input=user_input,
            requirements=requirements if requirements else None
        )
