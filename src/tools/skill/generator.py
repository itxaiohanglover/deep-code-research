"""Claude Agent Skill 生成器

职责：
1. 收集 Spec Kit 文档和 repo 代码产物
2. 生成符合 Claude 标准的 Agent Skill 目录

Claude Agent Skill 目录结构：
    skills/<skill_id>/
        SKILL.md           # 核心提示词与指令（必需）
        scripts/           # 可执行脚本 (Python/Bash/JS)
        references/        # 参考文档（Markdown/TXT）
        assets/            # 静态资源与模板

SKILL.md 格式要求：
- YAML frontmatter 必须包含 name 和 description
- name 最多 64 字符，description 最多 1024 字符
- 正文应包含详细的指令，指导 Claude 如何执行该技能
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ms_agent.utils import get_logger

logger = get_logger()

# 支持的脚本文件扩展名
SUPPORTED_SCRIPT_EXT = {'.py', '.sh', '.js', '.ts', '.bash'}

# 支持的参考文档扩展名
SUPPORTED_REFERENCE_EXT = {'.md', '.txt', '.rst'}

# 支持的资产文件扩展名
SUPPORTED_ASSET_EXT = {'.html', '.css', '.json', '.yaml', '.yml', '.xml', '.svg', '.png', '.jpg'}


class SpecKitCollector:
    """Spec Kit 文档收集器"""
    
    SPEC_KIT_DOCS = [
        "constitution.md",
        "spec.md", 
        "plan.md",
        "tasks.md",
        "spec_metadata.json"
    ]
    
    def __init__(self, spec_kit_dir: Path):
        self.spec_kit_dir = Path(spec_kit_dir)
    
    def collect(self) -> Dict[str, Any]:
        """收集所有 Spec Kit 文档"""
        result = {}
        
        for doc_name in self.SPEC_KIT_DOCS:
            doc_path = self.spec_kit_dir / doc_name
            if doc_path.exists():
                if doc_name.endswith(".json"):
                    result[doc_name.replace(".json", "")] = json.loads(
                        doc_path.read_text(encoding="utf-8")
                    )
                else:
                    key = doc_name.replace(".md", "")
                    result[key] = doc_path.read_text(encoding="utf-8")
        
        return result
    
    def get_doc_paths(self) -> List[Path]:
        """获取所有存在的文档路径"""
        paths = []
        for doc_name in self.SPEC_KIT_DOCS:
            doc_path = self.spec_kit_dir / doc_name
            if doc_path.exists():
                paths.append(doc_path)
        return paths


class RepoCollector:
    """代码仓库收集器"""
    
    IGNORED_DIRS = {"__pycache__", ".git", ".pytest_cache", "node_modules", ".venv", "venv"}
    IGNORED_FILES = {"files.json", "spec_code_mapping.json", ".DS_Store", "Thumbs.db"}
    
    def __init__(self, repo_dir: Path):
        self.repo_dir = Path(repo_dir)
    
    def _should_ignore(self, file_path: Path) -> bool:
        """判断文件是否应该被忽略"""
        for part in file_path.parts:
            if part in self.IGNORED_DIRS:
                return True
        if file_path.name in self.IGNORED_FILES:
            return True
        if file_path.name.startswith("."):
            return True
        return False
    
    def collect_scripts(self) -> List[Path]:
        """收集脚本文件"""
        scripts = []
        if not self.repo_dir.exists():
            return scripts
        
        for file_path in self.repo_dir.rglob("*"):
            if not file_path.is_file() or self._should_ignore(file_path):
                continue
            if file_path.suffix.lower() in SUPPORTED_SCRIPT_EXT:
                scripts.append(file_path)
        
        return scripts
    
    def collect_references(self) -> List[Path]:
        """收集参考文档"""
        references = []
        if not self.repo_dir.exists():
            return references
        
        for file_path in self.repo_dir.rglob("*"):
            if not file_path.is_file() or self._should_ignore(file_path):
                continue
            if file_path.suffix.lower() in SUPPORTED_REFERENCE_EXT:
                references.append(file_path)
        
        return references
    
    def collect_assets(self) -> List[Path]:
        """收集资产文件"""
        assets = []
        if not self.repo_dir.exists():
            return assets
        
        for file_path in self.repo_dir.rglob("*"):
            if not file_path.is_file() or self._should_ignore(file_path):
                continue
            if file_path.suffix.lower() in SUPPORTED_ASSET_EXT:
                assets.append(file_path)
        
        return assets


class SkillMetadataExtractor:
    """Skill 元数据提取器"""
    
    @staticmethod
    def extract_name(spec_kit: Dict[str, Any], default: str = "DeepCode Generated Skill") -> str:
        """提取 Skill 名称（最多 64 字符）"""
        if spec_kit.get("spec_metadata") and spec_kit["spec_metadata"].get("title"):
            name = spec_kit["spec_metadata"]["title"]
        elif spec_kit.get("constitution"):
            first_line = spec_kit["constitution"].strip().split("\n")[0]
            name = first_line.lstrip("#").strip()
        elif spec_kit.get("spec"):
            first_line = spec_kit["spec"].strip().split("\n")[0]
            name = first_line.lstrip("#").strip()
        else:
            name = default
        
        return name[:64] if name else default
    
    @staticmethod
    def extract_description(spec_kit: Dict[str, Any], default: str = "Auto-generated skill") -> str:
        """提取 Skill 描述（最多 1024 字符）"""
        if spec_kit.get("spec_metadata") and spec_kit["spec_metadata"].get("description"):
            desc = spec_kit["spec_metadata"]["description"]
        elif spec_kit.get("constitution"):
            lines = spec_kit["constitution"].strip().split("\n")
            for line in lines[1:10]:
                line = line.strip()
                if line and not line.startswith("#"):
                    desc = line
                    break
            else:
                desc = default
        else:
            desc = default
        
        return desc[:1024] if desc else default
    
    @staticmethod
    def extract_tags(spec_kit: Dict[str, Any]) -> List[str]:
        """提取标签"""
        tags = ["auto-generated", "deepcode"]
        if spec_kit.get("spec_metadata") and spec_kit["spec_metadata"].get("tags"):
            tags.extend(spec_kit["spec_metadata"]["tags"])
        return list(set(tags))


class ClaudeSkillMdGenerator:
    """符合 Claude 标准的 SKILL.md 生成器
    
    Claude Agent Skill 的 SKILL.md 应该包含：
    1. YAML frontmatter（name, description 必需）
    2. 角色定义：告诉 Claude 它扮演什么角色
    3. 能力说明：这个技能能做什么
    4. 输入输出：期望的输入格式和输出格式
    5. 执行步骤：详细的执行指令
    6. 示例：至少一个使用示例
    """
    
    @staticmethod
    def generate(
        name: str,
        description: str,
        spec_kit: Dict[str, Any],
        mapping_summary: Dict[str, Any],
        scripts: Optional[List[str]] = None,
        references: Optional[List[str]] = None,
        assets: Optional[List[str]] = None
    ) -> str:
        """生成符合 Claude 标准的 SKILL.md
        
        Args:
            name: Skill 名称
            description: Skill 描述
            spec_kit: Spec Kit 内容
            mapping_summary: Spec-Code 映射摘要
            scripts: 脚本文件列表
            references: 参考文档列表
            assets: 资产文件列表
        """
        # 构建 YAML frontmatter
        tags = SkillMetadataExtractor.extract_tags(spec_kit)
        tags_str = ", ".join(tags)
        
        # 安全处理 name 和 description，避免 YAML 解析错误
        # 1. 截断长度
        # 2. 转义双引号
        # 3. 用双引号包裹
        safe_name = name[:64].replace('"', '\\"').replace('\n', ' ')
        safe_desc = description[:1024].replace('"', '\\"').replace('\n', ' ')
        
        parts = [
            "---",
            f'name: "{safe_name}"',
            f'description: "{safe_desc}"',
            "version: v1.0.0",
            "author: DeepCode Research",
            f"tags: [{tags_str}]",
            "---",
            "",
        ]
        
        # 1. 标题和角色定义
        parts.extend([
            f"# {name}",
            "",
            "## 角色定义",
            "",
            f"你是一个专业的 {name} 专家。你的任务是根据以下规范和指令，帮助用户完成相关工作。",
            "",
        ])
        
        # 2. 能力说明
        parts.extend([
            "## 能力说明",
            "",
            description,
            "",
        ])
        
        # 3. 项目章程（如果有）
        if spec_kit.get("constitution"):
            constitution_preview = spec_kit["constitution"][:2000]
            parts.extend([
                "## 项目章程 (Constitution)",
                "",
                "以下是你必须严格遵守的项目章程：",
                "",
                "```markdown",
                constitution_preview,
                "```",
                "",
            ])
        
        # 4. 功能规格（如果有）
        if spec_kit.get("spec"):
            spec_preview = spec_kit["spec"][:1500]
            parts.extend([
                "## 功能规格 (Specification)",
                "",
                spec_preview,
                "",
            ])
        
        # 5. 执行计划（如果有）
        if spec_kit.get("plan"):
            plan_preview = spec_kit["plan"][:1500]
            parts.extend([
                "## 执行计划 (Plan)",
                "",
                plan_preview,
                "",
            ])
        
        # 6. 任务清单（如果有）
        if spec_kit.get("tasks"):
            tasks_preview = spec_kit["tasks"][:2000]
            parts.extend([
                "## 任务清单 (Tasks)",
                "",
                tasks_preview,
                "",
            ])
        
        # 7. Spec-Code 映射（重要参考）
        if mapping_summary.get("spec_to_code"):
            parts.extend([
                "## Spec-Code 映射",
                "",
                "以下是任务与代码文件的映射关系：",
                "",
                "| 任务 ID | 代码文件 |",
                "|---------|----------|",
            ])
            for task_id, files in mapping_summary["spec_to_code"].items():
                files_str = ", ".join(f"`{f}`" for f in files[:3]) if files else "-"
                parts.append(f"| {task_id} | {files_str} |")
            parts.append("")
        
        # 8. 可用脚本
        if scripts:
            parts.extend([
                "## 可用脚本 (Scripts)",
                "",
                "以下脚本可以在 `scripts/` 目录中找到并执行：",
                "",
            ])
            for script in scripts[:10]:
                parts.append(f"- `scripts/{script}`")
            parts.append("")
        
        # 9. 参考文档
        if references:
            parts.extend([
                "## 参考文档 (References)",
                "",
                "以下参考文档可以在 `references/` 目录中找到：",
                "",
            ])
            for ref in references[:10]:
                parts.append(f"- `references/{ref}`")
            parts.append("")
        
        # 10. 使用示例
        parts.extend([
            "## 使用示例",
            "",
            "### 示例 1：查看项目结构",
            "",
            "```",
            f"请帮我了解 {name} 项目的整体结构和功能模块。",
            "```",
            "",
            "### 示例 2：执行特定任务",
            "",
            "```",
            "请帮我执行任务清单中的第一个任务，并说明执行步骤。",
            "```",
            "",
        ])
        
        # 11. 执行指令
        parts.extend([
            "## 执行指令",
            "",
            "当用户激活此技能时，你应该：",
            "",
            "1. **理解上下文**：阅读项目章程和功能规格，理解项目目标",
            "2. **遵循规范**：严格按照任务清单和执行计划进行操作",
            "3. **使用资源**：必要时查阅参考文档和执行脚本",
            "4. **验证结果**：完成任务后，验证输出是否符合规格要求",
            "",
        ])
        
        # 12. 成功经验
        stats = mapping_summary.get("stats", {})
        parts.extend([
            "## 成功经验 (Best Practices)",
            "",
            "此 Skill 基于以下成功实践生成：",
            "",
            f"- 完成任务数：{stats.get('total_tasks', 0)}",
            f"- 生成代码文件：{stats.get('total_code_files', 0)}",
            f"- 映射覆盖率：{stats.get('mapped_count', 0)}/{stats.get('total_tasks', 0)}",
            "",
            "---",
            "",
            f"*由 DeepCode Research 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ])
        
        return "\n".join(parts)


class SkillGenerator:
    """Claude Agent Skill 生成器
    
    生成符合 Claude 标准的 Agent Skill 目录结构：
    - SKILL.md: 核心提示词与指令
    - scripts/: 可执行脚本
    - references/: 参考文档
    - assets/: 静态资源
    """
    
    def __init__(
        self,
        spec_kit_dir: Path,
        repo_dir: Path,
        skills_dir: Path
    ):
        self.spec_kit_dir = Path(spec_kit_dir)
        self.repo_dir = Path(repo_dir)
        self.skills_dir = Path(skills_dir)
        
        self.spec_kit_collector = SpecKitCollector(spec_kit_dir)
        self.repo_collector = RepoCollector(repo_dir)
        self.metadata_extractor = SkillMetadataExtractor()
    
    def generate_skill_id(self, prefix: str = "skill") -> str:
        """生成 Skill ID"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{prefix}_{timestamp}"
    
    def generate(
        self,
        skill_id: Optional[str] = None,
        mapping_summary: Optional[Dict[str, Any]] = None
    ) -> Path:
        """生成 Claude Agent Skill 目录
        
        Args:
            skill_id: Skill ID（可选）
            mapping_summary: Spec-Code 映射摘要（可选）
            
        Returns:
            生成的 Skill 目录路径
        """
        skill_id = skill_id or self.generate_skill_id()
        skill_dir = self.skills_dir / skill_id
        skill_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"[SkillGenerator] 开始生成 Claude Agent Skill: {skill_id}")
        
        # 1. 收集 Spec Kit 内容
        spec_kit = self.spec_kit_collector.collect()
        
        # 2. 提取元数据
        name = self.metadata_extractor.extract_name(spec_kit)
        description = self.metadata_extractor.extract_description(spec_kit)
        
        # 3. 收集并复制脚本到 scripts/
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        script_names = self._copy_scripts(scripts_dir)
        
        # 4. 收集并复制参考文档到 references/
        references_dir = skill_dir / "references"
        references_dir.mkdir(exist_ok=True)
        reference_names = self._copy_references(references_dir)
        self._copy_spec_kit_to_references(references_dir)
        
        # 5. 收集并复制资产到 assets/
        assets_dir = skill_dir / "assets"
        assets_dir.mkdir(exist_ok=True)
        asset_names = self._copy_assets(assets_dir)
        
        # 6. 生成 SKILL.md
        mapping_summary = mapping_summary or {"spec_to_code": {}, "stats": {}}
        skill_md_content = ClaudeSkillMdGenerator.generate(
            name=name,
            description=description,
            spec_kit=spec_kit,
            mapping_summary=mapping_summary,
            scripts=script_names,
            references=reference_names,
            assets=asset_names
        )
        (skill_dir / "SKILL.md").write_text(skill_md_content, encoding="utf-8")
        
        logger.info(f"[SkillGenerator] Claude Agent Skill 生成完成: {skill_dir}")
        return skill_dir
    
    def _copy_scripts(self, dest_dir: Path) -> List[str]:
        """复制脚本文件到目标目录"""
        scripts = self.repo_collector.collect_scripts()
        names = []
        
        for script_path in scripts:
            rel_path = script_path.relative_to(self.repo_dir)
            dest_path = dest_dir / rel_path
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(script_path, dest_path)
            names.append(str(rel_path))
        
        if names:
            logger.info(f"[SkillGenerator] 已复制 {len(names)} 个脚本到 scripts/")
        return names
    
    def _copy_references(self, dest_dir: Path) -> List[str]:
        """复制参考文档到目标目录"""
        references = self.repo_collector.collect_references()
        names = []
        
        for ref_path in references:
            dest_path = dest_dir / ref_path.name
            shutil.copy2(ref_path, dest_path)
            names.append(ref_path.name)
        
        if names:
            logger.info(f"[SkillGenerator] 已复制 {len(names)} 个参考文档到 references/")
        return names
    
    def _copy_spec_kit_to_references(self, dest_dir: Path):
        """复制 Spec Kit 文档到 references/"""
        for doc_path in self.spec_kit_collector.get_doc_paths():
            if doc_path.suffix == ".md":  # 只复制 Markdown 文档
                shutil.copy2(doc_path, dest_dir / doc_path.name)
        logger.info(f"[SkillGenerator] 已复制 Spec Kit 文档到 references/")
    
    def _copy_assets(self, dest_dir: Path) -> List[str]:
        """复制资产文件到目标目录"""
        assets = self.repo_collector.collect_assets()
        names = []
        
        for asset_path in assets:
            rel_path = asset_path.relative_to(self.repo_dir)
            dest_path = dest_dir / rel_path
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(asset_path, dest_path)
            names.append(str(rel_path))
        
        if names:
            logger.info(f"[SkillGenerator] 已复制 {len(names)} 个资产到 assets/")
        return names
    
    def validate(self, skill_dir: Path) -> bool:
        """验证 Skill 目录结构是否符合 Claude 标准"""
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists() or skill_md.stat().st_size == 0:
            logger.warning(f"[SkillGenerator] SKILL.md 不存在或为空")
            return False
        
        try:
            import re
            import yaml
            content = skill_md.read_text(encoding="utf-8")
            pattern = r'^---\s*\n(.*?)\n---\s*\n'
            match = re.match(pattern, content, re.DOTALL)
            if not match:
                logger.warning("[SkillGenerator] SKILL.md 缺少 YAML frontmatter")
                return False
            
            frontmatter = yaml.safe_load(match.group(1))
            if not frontmatter or 'name' not in frontmatter or 'description' not in frontmatter:
                logger.warning("[SkillGenerator] frontmatter 缺少必需字段")
                return False
            
            return True
        except Exception as e:
            logger.warning(f"[SkillGenerator] 验证失败: {e}")
            return False
