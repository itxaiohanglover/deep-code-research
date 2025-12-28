"""Agent 模块

所有 Agent 直接继承 LLMAgent，遵循 ms-agent 最佳实践。
通过 Mixin 提供公共功能支持。
"""

from .analysis.requirements import RequirementsAgent
from .analysis.tech_research import TechResearchAgent
from .analysis.architecture import ArchitectureAgent
from .analysis.risk import RiskAgent
from .analysis.spec_gen import SpecGenAgent, SpecAgent
from .analysis.evolution import EvolutionAgent
from .generate.planning import PlanningAgent
from .generate.coding import CodingAgent
from .generate.testing import TestingAgent
from .review.reflecting import ReflectingAgent
from .review.summary import SummaryAgent
from .mixins import ArtifactStoreMixin
from .types import (
    AgentInput,
    AgentOutput,
    ArtifactDict,
    ArtifactNames,
    AgentResult,
    DocumentResult,
)

__all__ = [
    # Agents
    "RequirementsAgent",
    "TechResearchAgent",
    "ArchitectureAgent",
    "RiskAgent",
    "SpecGenAgent",
    "SpecAgent",  # 别名，兼容配置文件中的 class_name
    "EvolutionAgent",
    "PlanningAgent",
    "CodingAgent",
    "TestingAgent",
    "ReflectingAgent",
    "SummaryAgent",
    # Mixins
    "ArtifactStoreMixin",
    # Types
    "AgentInput",
    "AgentOutput",
    "ArtifactDict",
    "ArtifactNames",
    "AgentResult",
    "DocumentResult",
]
