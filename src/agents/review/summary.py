"""Summary Agent：总结项目执行过程，提取成功模式为 Claude Agent Skills

核心职责：
1. 从 spec_code_mapping.json 读取 Spec-Code 映射信息
2. 读取 Spec Kit 和 repo 产物
3. 生成符合 Claude 标准的 Agent Skill

Claude Agent Skill 目录结构：
    skills/<skill_id>/
        SKILL.md           # 核心提示词与指令
        scripts/           # 可执行脚本 (Python/Bash/JS)
        references/        # 参考文档（Spec Kit + Markdown）
        assets/            # 静态资源（HTML/CSS/JSON 等）

前置条件：
- 由 ReflectingAgent.next_flow() 控制跳转
- 只有当测试全部通过时，才会跳转到此 Agent
"""

from pathlib import Path
from typing import Any, Dict

from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger

from src.agents._base_agent import BaseAgent
from src.tools.skill import SkillGenerator

logger = get_logger()


class SummaryAgent(BaseAgent):
    """Summary Agent：生成符合 Claude 标准的 Agent Skills
    
    职责：
    1. 从 spec_code_mapping.json 读取 Spec-Code 映射信息
    2. 读取 Spec Kit 和 repo 产物
    3. 直接生成 Claude Agent Skill（不需要 LLM）
    
    Claude Agent Skill 目录结构：
        skills/<skill_id>/
            SKILL.md           # 核心提示词与指令
            scripts/           # 可执行脚本
            references/        # 参考文档（含 Spec Kit）
            assets/            # 静态资源
    """
    
    def __init__(self, config, tag: str = "summary", **kwargs):
        super().__init__(config, tag, **kwargs)
    
    def _get_spec_code_mapping_summary(self) -> Dict[str, Any]:
        """获取 Spec-Code 映射摘要"""
        mapping = self.tracker.mapping
        verification = self.tracker.verify_mapping()
        
        return {
            "spec_to_code": mapping.get("spec_to_code", {}),
            "code_to_test": mapping.get("code_to_test", {}),
            "verification": verification,
            "stats": {
                "total_tasks": len(mapping.get("spec_to_code", {})),
                "total_code_files": len(mapping.get("code_to_spec", {})),
                "mapped_count": len(verification.get("mapped", [])),
                "partial_count": len(verification.get("partial", [])),
            }
        }
    
    def _build_prompt(self, user_input: str) -> str:
        """构建提示词（此 Agent 不使用 LLM，但需要保持接口一致）"""
        return "生成 Claude Agent Skill"
    
    def _create_skill_generator(self) -> SkillGenerator:
        """创建 SkillGenerator 实例"""
        return SkillGenerator(
            spec_kit_dir=self.path_manager.spec_kit_dir,
            repo_dir=self.path_manager.repo_dir,
            skills_dir=self.path_manager.skills_dir
        )
    
    def _generate_report(self, skill_id: str, skill_dir: Path, mapping_summary: Dict[str, Any]) -> str:
        """生成成功报告"""
        report_parts = [
            "# Claude Agent Skill 生成成功",
            "",
            "## Skill 信息",
            "",
            f"- **Skill ID**: `{skill_id}`",
            f"- **目录位置**: `{skill_dir}`",
            "",
            "## 目录结构",
            "",
            "```",
            f"{skill_id}/",
            "├── SKILL.md          # 核心提示词与指令",
            "├── scripts/          # 可执行脚本",
            "├── references/       # 参考文档（含 Spec Kit）",
            "└── assets/           # 静态资源",
            "```",
            "",
            "## Spec-Code 映射统计",
            "",
            f"- 总任务数: {mapping_summary['stats']['total_tasks']}",
            f"- 代码文件数: {mapping_summary['stats']['total_code_files']}",
            f"- 已完成映射: {mapping_summary['stats']['mapped_count']}",
            "",
            "## 使用方式",
            "",
            "将此 Skill 目录添加到 Claude 的 skill 目录中，",
            "Claude 会自动识别并加载 SKILL.md 中的指令。",
            "",
            "## 流程总结",
            "",
            "1. ✅ 需求分析完成",
            "2. ✅ 代码生成完成", 
            "3. ✅ 测试全部通过",
            "4. ✅ Claude Agent Skill 已生成",
        ]
        
        return "\n".join(report_parts)
    
    async def run(self, inputs: Any, **kwargs: Any) -> Any:
        """运行 Agent：直接生成 Claude Agent Skill
        
        工作流程：
        1. 读取 spec_code_mapping.json 获取映射信息
        2. 使用 SkillGenerator 生成完整的 Skill 目录
        3. 返回生成报告
        
        注意：此 Agent 不调用 LLM，所有信息从产物中获取
        """
        logger.info(f"[{self.tag}] 开始生成 Claude Agent Skill")
        
        # 1. 获取 Spec-Code 映射摘要
        mapping_summary = self._get_spec_code_mapping_summary()
        logger.info(f"[{self.tag}] Spec-Code 映射: {mapping_summary['stats']['total_tasks']} 任务, "
                   f"{mapping_summary['stats']['total_code_files']} 文件")
        
        # 2. 创建 SkillGenerator 并生成 Skill
        generator = self._create_skill_generator()
        skill_id = generator.generate_skill_id()
        
        # 3. 使用 SkillGenerator 生成完整的 Claude Agent Skill
        skill_dir = generator.generate(
            skill_id=skill_id,
            mapping_summary=mapping_summary
        )
        
        # 4. 验证生成结果
        if not generator.validate(skill_dir):
            logger.warning(f"[{self.tag}] Skill 验证失败，但目录已创建")
        
        logger.info(f"[{self.tag}] Claude Agent Skill 已创建: {skill_dir}")
        
        # 5. 生成报告
        report = self._generate_report(skill_id, skill_dir, mapping_summary)
        return [Message(role="assistant", content=report)]
