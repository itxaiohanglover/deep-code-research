"""Prompts 模块 - 统一管理所有 Agent 的提示词模板

该模块包含以下三个阶段的提示词构建函数：

分析阶段（Analysis Phase）：
- build_requirements_prompt: 需求分析
- build_tech_research_prompt: 技术研究  
- build_architecture_prompt: 架构设计
- build_risk_prompt: 风险评估
- build_spec_gen_prompt: 规格套件生成
- build_evolution_prompt: 演进验证

生成阶段（Generate Phase）：
- build_planning_prompt: 开发规划
- build_coding_prompt: 代码实现
- build_testing_prompt: 测试执行

评审阶段（Review Phase）：
- build_reflecting_prompt: 反思分析
- build_summary_prompt: 总结生成
"""

from src.prompts.requirements_prompts import build_requirements_prompt
from src.prompts.tech_research_prompts import build_tech_research_prompt
from src.prompts.architecture_prompts import build_architecture_prompt
from src.prompts.risk_prompts import build_risk_prompt, build_artifact_sections
from src.prompts.spec_gen_prompts import build_spec_gen_prompt
from src.prompts.evolution_prompts import build_evolution_prompt
from src.prompts.planning_prompts import build_planning_prompt
from src.prompts.coding_prompts import build_coding_prompt
from src.prompts.testing_prompts import build_testing_prompt
from src.prompts.reflecting_prompts import build_reflecting_prompt
from src.prompts.summary_prompts import build_summary_prompt

__all__ = [
    # 分析阶段
    "build_requirements_prompt",
    "build_tech_research_prompt",
    "build_architecture_prompt",
    "build_risk_prompt",
    "build_artifact_sections",
    "build_spec_gen_prompt",
    "build_evolution_prompt",
    # 生成阶段
    "build_planning_prompt",
    "build_coding_prompt",
    "build_testing_prompt",
    # 评审阶段
    "build_reflecting_prompt",
    "build_summary_prompt",
]
