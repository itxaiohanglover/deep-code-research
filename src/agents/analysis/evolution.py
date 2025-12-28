"""Evolution Agent - Phase 6"""

from typing import List

from ms_agent.utils import get_logger

from src.agents._base_agent import BaseAgent
from src.prompts.evolution_prompts import build_evolution_prompt

logger = get_logger()


class EvolutionAgent(BaseAgent):
    """Evolution Agent（验证和优化）
    
    职责：
    1. 验证 Spec Kit 的质量（完整性、一致性、可执行性）
    2. 优化 Spec Kit，确保其可以直接用于开发
    3. 提供优化建议（如果需要）
    
    产物依赖：
    - requirements：需求分析结果（用于验证覆盖度）
    - spec_kit：从 spec_kit 目录加载（constitution, spec, plan, tasks）
    
    注意：spec_kit 不是一个产物，而是 4 个独立文件，使用 _load_spec_kit() 加载
    """
    
    # 声明依赖的前序产物（只依赖 requirements，spec_kit 单独加载）
    ARTIFACT_DEPENDENCIES: List[str] = ["requirements"]
    
    def _build_prompt(self, user_input: str) -> str:
        """构建 Evolution 提示词
        
        步骤：
        1. 获取 requirements 产物
        2. 加载 spec_kit 目录下的 4 个文档
        3. 构建验证提示词
        """
        # 获取 requirements
        artifacts = self._get_artifacts()
        requirements = artifacts.get("requirements", "")
        
        # 加载 Spec Kit（4 个文档）
        spec_kit = self._load_spec_kit()
        
        if spec_kit:
            loaded_docs = [k for k, v in spec_kit.items() if v]
            logger.info(f"[{self.tag}] 加载 Spec Kit 文档: {loaded_docs}")
        else:
            logger.warning(f"[{self.tag}] 未找到 Spec Kit 文档")
        
        return build_evolution_prompt(
            user_input=user_input,
            spec_kit=spec_kit if spec_kit else None,
            requirements=requirements if requirements else None
        )
