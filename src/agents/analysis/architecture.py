"""架构设计 Agent - Phase 3"""

from ms_agent.utils import get_logger

from src.agents._base_agent import BaseAgent
from src.prompts.architecture_prompts import build_architecture_prompt

logger = get_logger()


class ArchitectureAgent(BaseAgent):
    """架构设计 Agent
    
    职责：
    1. 基于需求分析和技术调研结果，设计系统架构
    2. 设计模块划分、接口设计、数据模型
    3. 提供部署架构设计
    
    使用产物依赖声明机制自动收集前序产物。
    """
    
    # 声明依赖的前序产物
    # 优化：只依赖 requirements，允许与 tech_research 并行执行
    # tech_research 的技术调研结果会在 spec_gen 阶段整合
    ARTIFACT_DEPENDENCIES = ["requirements"]
    
    def _build_prompt(self, user_input: str) -> str:
        """构建架构设计提示词"""
        # 使用 _get_artifacts() 自动收集声明的产物
        artifacts = self._get_artifacts()
        
        if artifacts.get("requirements") and artifacts.get("tech_research"):
            logger.info(f"[{self.tag}] 获取到需求和技术调研结果，开始架构设计")
        
        return build_architecture_prompt(
            user_input=user_input,
            requirements=artifacts.get("requirements") or None,
            tech_research=artifacts.get("tech_research") or None
        )
