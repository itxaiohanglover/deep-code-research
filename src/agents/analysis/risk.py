"""风险评估 Agent - Phase 4"""

from ms_agent.utils import get_logger

from src.agents._base_agent import BaseAgent
from src.prompts.risk_prompts import build_risk_prompt

logger = get_logger()


class RiskAgent(BaseAgent):
    """风险评估 Agent
    
    职责：
    1. 识别和评估项目风险（技术风险、项目风险、业务风险）
    2. 提供风险缓解方案
    3. 评估运营风险（运维、监控、安全等）
    
    使用产物依赖声明机制自动收集前序产物。
    """
    
    # 声明依赖的前序产物
    # 优化：只依赖 requirements，允许与 tech_research/architecture 并行执行
    # 所有产物会在 spec_gen 阶段整合
    ARTIFACT_DEPENDENCIES = ["requirements"]
    
    def _build_prompt(self, user_input: str) -> str:
        """构建风险评估提示词"""
        # 使用 _get_artifacts() 自动收集声明的产物
        artifacts = self._get_artifacts()
        
        logger.info(f"[{self.tag}] 获取到前序研究结果，开始风险评估")
        
        return build_risk_prompt(
            user_input=user_input,
            requirements=artifacts.get("requirements") or None,
            tech_research=artifacts.get("tech_research") or None,
            architecture=artifacts.get("architecture") or None
        )
