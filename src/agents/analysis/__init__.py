"""分析阶段 Agent 模块

包含需求分析、技术调研、架构设计、风险评估、SpecKit 生成和进化等 Agent。
"""

from .requirements import RequirementsAgent
from .tech_research import TechResearchAgent
from .architecture import ArchitectureAgent
from .risk import RiskAgent
from .spec_gen import SpecGenAgent, SpecAgent
from .evolution import EvolutionAgent

__all__ = [
    "RequirementsAgent",
    "TechResearchAgent",
    "ArchitectureAgent",
    "RiskAgent",
    "SpecGenAgent",
    "SpecAgent",  # 别名，兼容配置文件中的 class_name
    "EvolutionAgent",
]
