"""Spec Kit 解析器

解析 Spec Kit 文档，提取任务、模块和依赖关系。
支持中英文格式。

Phase 2 增强：
1. 更多规则模式，提高覆盖率
2. LLM 后备解析器，处理复杂格式
3. 解析结果验证和修复
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ms_agent.utils import get_logger

logger = get_logger()


class SpecKitParser:
    """Spec Kit 解析器
    
    Phase 2 增强：
    - 支持更多任务格式变体
    - 支持 LLM 后备解析
    - 自动验证和修复解析结果
    """
    
    # 任务 ID 模式（用于统一格式）
    TASK_ID_PATTERN = re.compile(r'Task-?(\d+)[.\-_](\d+)', re.IGNORECASE)
    
    def __init__(self, spec_kit_dir: Path, use_llm_fallback: bool = True):
        """初始化解析器
        
        Args:
            spec_kit_dir: Spec Kit 目录路径
            use_llm_fallback: 是否启用 LLM 后备解析（默认 True）
        """
        self.spec_kit_dir = Path(spec_kit_dir)
        self.use_llm_fallback = use_llm_fallback
        self.constitution = None
        self.spec = None
        self.plan = None
        self.tasks = None
        self.metadata = None
        
        # LLM 后备解析器（懒加载）
        self._llm_parser = None
    
    def load(self) -> Dict:
        """加载 Spec Kit 文档
        
        Returns:
            包含所有文档内容的字典
        """
        # 加载各个文档
        constitution_file = self.spec_kit_dir / "constitution.md"
        spec_file = self.spec_kit_dir / "spec.md"
        plan_file = self.spec_kit_dir / "plan.md"
        tasks_file = self.spec_kit_dir / "tasks.md"
        metadata_file = self.spec_kit_dir / "spec_metadata.json"
        
        result = {}
        
        if constitution_file.exists():
            self.constitution = constitution_file.read_text(encoding="utf-8")
            result["constitution"] = self.constitution
        
        if spec_file.exists():
            self.spec = spec_file.read_text(encoding="utf-8")
            result["spec"] = self.spec
        
        if plan_file.exists():
            self.plan = plan_file.read_text(encoding="utf-8")
            result["plan"] = self.plan
        
        if tasks_file.exists():
            self.tasks = tasks_file.read_text(encoding="utf-8")
            result["tasks"] = self.tasks
        
        if metadata_file.exists():
            self.metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
            result["metadata"] = self.metadata
        
        return result
    
    def extract_tasks(self) -> List[Dict]:
        """从 tasks.md 中提取任务列表（增强版）
        
        支持格式（按优先级）：
        1. **Task-X.Y: 任务名称**（加粗格式）
        2. ### Task-X.Y: 任务名称（标题格式）
        3. #### Task-X.Y 任务名称（无冒号）
        4. ## 任务 N: 任务名称（中文旧格式）
        5. 编号列表格式
        
        如果规则解析失败，自动使用 LLM 后备解析。
        
        Returns:
            任务列表，每个任务包含 id, description, dependencies 等字段
        """
        if not self.tasks:
            return []
        
        # 尝试多种规则解析
        tasks = self._extract_tasks_by_rules()
        
        # 如果规则解析失败且启用了 LLM 后备
        if not tasks and self.use_llm_fallback:
            logger.warning("[SpecKitParser] 规则解析未找到任务，尝试 LLM 后备解析")
            tasks = self._extract_tasks_by_llm()
        
        # 验证和修复
        if tasks:
            tasks = self._validate_and_fix_tasks(tasks)
            logger.info(f"[SpecKitParser] 提取到 {len(tasks)} 个任务")
        
        return tasks
    
    def _extract_tasks_by_rules(self) -> List[Dict]:
        """使用规则提取任务（多策略）"""
        tasks = []
        
        # 策略 1: **Task-X.Y: 任务名称** 格式（加粗）
        tasks = self._extract_tasks_bold_format()
        if tasks:
            logger.debug(f"[SpecKitParser] 使用加粗格式提取到 {len(tasks)} 个任务")
            return tasks
        
        # 策略 2: ### Task-X.Y: 任务名称（标题格式）
        tasks = self._extract_tasks_heading_format()
        if tasks:
            logger.debug(f"[SpecKitParser] 使用标题格式提取到 {len(tasks)} 个任务")
            return tasks
        
        # 策略 3: 编号列表格式（1. Task-1.1 或 - Task-1.1）
        tasks = self._extract_tasks_list_format()
        if tasks:
            logger.debug(f"[SpecKitParser] 使用列表格式提取到 {len(tasks)} 个任务")
            return tasks
        
        # 策略 4: 中文旧格式（## 任务 N）
        tasks = self._extract_tasks_chinese_format()
        if tasks:
            logger.debug(f"[SpecKitParser] 使用中文格式提取到 {len(tasks)} 个任务")
            return tasks
        
        return []
    
    def _extract_tasks_bold_format(self) -> List[Dict]:
        """提取加粗格式的任务: **Task-X.Y: 任务名称**"""
        tasks = []
        
        # 更宽松的模式，支持多种变体
        patterns = [
            r'\*\*Task-(\d+)[.\-](\d+):\s*(.+?)\*\*',  # **Task-1.1: 名称**
            r'\*\*Task-(\d+)[.\-](\d+)\s+(.+?)\*\*',   # **Task-1.1 名称**
            r'\*\*Task(\d+)[.\-](\d+):\s*(.+?)\*\*',   # **Task1.1: 名称**
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, self.tasks, re.DOTALL)
            if matches:
                for phase, seq, title in matches:
                    task_id = f"Task-{phase}.{seq}"
                    description = title.strip().replace('\n', ' ')[:200]
                    
                    # 提取内容和依赖
                    content, dependencies = self._extract_task_details(task_id)
                    
                    tasks.append({
                        "id": task_id,
                        "description": description,
                        "dependencies": dependencies,
                        "content": content
                    })
                return tasks
        
        return []
    
    def _extract_tasks_heading_format(self) -> List[Dict]:
        """提取标题格式的任务: ### Task-X.Y: 任务名称"""
        tasks = []
        
        # 支持 2-4 个 #，冒号可选
        pattern = r'#{2,4}\s*Task-?(\d+)[.\-](\d+)\s*[:：]?\s*(.+?)(?=\n#{2,4}\s*Task-?|\n#{2,3}\s*(?:\*\*)?[阶段Phase]|\n---|\Z)'
        matches = re.findall(pattern, self.tasks, re.DOTALL | re.IGNORECASE)
        
        for phase, seq, content in matches:
            task_id = f"Task-{phase}.{seq}"
            
            # 提取描述
            description = self._extract_description_from_content(content)
            
            # 提取依赖
            dependencies = self._extract_dependencies(content)
            
            tasks.append({
                "id": task_id,
                "description": description,
                "dependencies": dependencies,
                "content": content.strip()
            })
        
        return tasks
    
    def _extract_tasks_list_format(self) -> List[Dict]:
        """提取列表格式的任务: - Task-X.Y 或 1. Task-X.Y"""
        tasks = []
        
        # 匹配列表项中的任务
        pattern = r'(?:^[-*\d.]+)\s*(?:\*\*)?Task-?(\d+)[.\-](\d+)(?:\*\*)?[:\s]*(.+?)(?=\n[-*\d.]+\s*(?:\*\*)?Task-?|\n#{2,}|\Z)'
        matches = re.findall(pattern, self.tasks, re.MULTILINE | re.DOTALL)
        
        for phase, seq, content in matches:
            task_id = f"Task-{phase}.{seq}"
            description = self._extract_description_from_content(content)
            dependencies = self._extract_dependencies(content)
            
            tasks.append({
                "id": task_id,
                "description": description,
                "dependencies": dependencies,
                "content": content.strip()
            })
        
        return tasks
    
    def _extract_tasks_chinese_format(self) -> List[Dict]:
        """提取中文格式的任务: ## 任务 N"""
        tasks = []
        
        pattern = r'##\s*任务\s*(\d+)[:：]\s*(.+?)(?=\n##|\Z)'
        matches = re.findall(pattern, self.tasks, re.DOTALL)
        
        for task_num, content in matches:
            task_id = f"task_{task_num}"
            description = content.split('\n')[0].strip()
            dependencies = self._extract_dependencies(content)
            
            tasks.append({
                "id": task_id,
                "description": description,
                "dependencies": dependencies,
                "content": content.strip()
            })
        
        return tasks
    
    def _extract_task_details(self, task_id: str) -> Tuple[str, List[str]]:
        """提取任务的详细内容和依赖
        
        Args:
            task_id: 任务 ID
            
        Returns:
            (内容, 依赖列表)
        """
        # 构建正则提取任务内容区域
        match = self.TASK_ID_PATTERN.match(task_id)
        if not match:
            return "", []
        
        phase, seq = match.groups()
        
        # 查找任务内容区域
        section_patterns = [
            rf'\*\*Task-{phase}[.\-]{seq}[:\s].+?\*\*(.+?)(?=\n\*\*Task-|\n---|\n##|\Z)',
            rf'#{2,4}\s*Task-{phase}[.\-]{seq}.+?\n(.+?)(?=\n#{2,4}\s*Task-|\n---|\Z)',
        ]
        
        for pattern in section_patterns:
            section_match = re.search(pattern, self.tasks, re.DOTALL | re.IGNORECASE)
            if section_match:
                content = section_match.group(1).strip()
                dependencies = self._extract_dependencies(content)
                return content, dependencies
        
        return "", []
    
    def _extract_description_from_content(self, content: str) -> str:
        """从内容中提取描述"""
        # 优先查找 Goal/目标字段
        goal_patterns = [
            r'\*\*(?:Goal|目标)\*\*[：:]\s*(.+?)(?=\n|$)',
            r'-\s*\*\*(?:Goal|目标)\*\*[：:]\s*(.+?)(?=\n|$)',
            r'(?:Goal|目标)[：:]\s*(.+?)(?=\n|$)',
        ]
        
        for pattern in goal_patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group(1).strip()[:200]
        
        # 使用第一行
        first_line = content.split('\n')[0].strip()
        first_line = re.sub(r'^\*\*|\*\*$|^[-*]\s*', '', first_line).strip()
        return first_line[:200] if first_line else "未知任务"
    
    def _extract_dependencies(self, content: str) -> List[str]:
        """从内容中提取依赖关系"""
        dep_patterns = [
            r'\*\*(?:Dependencies?|依赖任务?|依赖)\*\*[：:]\s*(.+?)(?=\n|$)',
            r'-\s*\*\*(?:Dependencies?|依赖任务?|依赖)\*\*[：:]\s*(.+?)(?=\n|$)',
            r'(?:Dependencies?|依赖任务?|依赖)[：:]\s*(.+?)(?=\n|$)',
        ]
        
        for pattern in dep_patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                deps_str = match.group(1).strip()
                
                # 检查是否为空值
                if deps_str.lower() in ['none', '无', 'n/a', '[]', '[ ]', '-']:
                    return []
                
                # 清理和分割
                deps_str = re.sub(r'[\[\]()]', '', deps_str)
                dependencies = [
                    d.strip()
                    for d in re.split(r'[,，、;；或and]', deps_str)
                    if d.strip() and d.strip().lower() not in ['none', '无', 'n/a']
                ]
                
                # 标准化任务 ID 格式
                normalized = []
                for dep in dependencies:
                    match = self.TASK_ID_PATTERN.search(dep)
                    if match:
                        phase, seq = match.groups()
                        normalized.append(f"Task-{phase}.{seq}")
                
                return normalized
        
        return []
    
    def _extract_tasks_by_llm(self) -> List[Dict]:
        """使用 LLM 后备解析器提取任务"""
        try:
            from src.tools.spec.llm_parser import llm_spec_parser
            import asyncio
            
            # 同步调用异步方法
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果已经在异步上下文中，创建新的 task
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        llm_spec_parser.extract_tasks(self.tasks)
                    )
                    return future.result()
            else:
                return loop.run_until_complete(
                    llm_spec_parser.extract_tasks(self.tasks)
                )
        except Exception as e:
            logger.warning(f"[SpecKitParser] LLM 后备解析失败: {e}")
            return []
    
    def _validate_and_fix_tasks(self, tasks: List[Dict]) -> List[Dict]:
        """验证和修复任务列表"""
        fixed_tasks = []
        seen_ids = set()
        
        for task in tasks:
            task_id = task.get("id", "")
            
            # 标准化任务 ID
            match = self.TASK_ID_PATTERN.search(task_id)
            if match:
                phase, seq = match.groups()
                task_id = f"Task-{phase}.{seq}"
            
            # 去重
            if task_id in seen_ids:
                continue
            seen_ids.add(task_id)
            
            # 确保必要字段
            fixed_task = {
                "id": task_id,
                "description": task.get("description", "未知任务")[:200],
                "dependencies": task.get("dependencies", []),
                "content": task.get("content", ""),
            }
            
            fixed_tasks.append(fixed_task)
        
        # 按任务 ID 排序
        fixed_tasks.sort(key=lambda t: (
            int(self.TASK_ID_PATTERN.search(t["id"]).group(1)) if self.TASK_ID_PATTERN.search(t["id"]) else 0,
            int(self.TASK_ID_PATTERN.search(t["id"]).group(2)) if self.TASK_ID_PATTERN.search(t["id"]) else 0,
        ))
        
        return fixed_tasks
    
    def extract_modules(self) -> List[Dict]:
        """从 spec.md 中提取模块列表
        
        支持格式：
        - ## N. Module Name（数字编号的章节，中英文均可）
        - ## 功能模块 N: 模块名称（向后兼容）
        - 从 User Stories/用户故事 中推断模块
        
        Returns:
            模块列表
        """
        if not self.spec:
            return []
        
        modules = []
        
        # 方法1: 匹配数字编号的章节（如 ## 1. 概述, ## 2. 用户故事）
        module_pattern_v2 = r'##\s*(\d+)\.\s*(.+?)(?=\n##|\Z)'
        matches_v2 = re.findall(module_pattern_v2, self.spec, re.DOTALL)
        
        for module_id, content in matches_v2:
            # 提取模块名称（第一行或标题）
            name = content.split('\n')[0].strip()
            # 移除可能的 Markdown 格式
            name = re.sub(r'^\*\*|\*\*$', '', name).strip()
            
            modules.append({
                "id": f"module_{module_id}",
                "name": name,
                "content": content.strip()
            })
        
        # 方法2: 如果没有找到，尝试从 User Stories/用户故事 推断模块
        if not modules:
            us_patterns = [
                r'###\s*US-(\d+)[:：]\s*(.+?)(?=\n###|\n##|\Z)',  # US-001 格式
                r'###\s*用户故事[- ]?(\d+)[:：]\s*(.+?)(?=\n###|\n##|\Z)',  # 用户故事-001 格式
            ]
            
            us_matches = []
            for us_pattern in us_patterns:
                us_matches = re.findall(us_pattern, self.spec, re.DOTALL)
                if us_matches:
                    break
            
            if us_matches:
                # 将所有 User Stories 归为一个模块
                modules.append({
                    "id": "module_user_stories",
                    "name": "用户故事",
                    "content": "\n\n".join([f"US-{us_id}: {content.split(chr(10))[0]}" for us_id, content in us_matches])
                })
        
        # 方法3: 向后兼容旧格式
        if not modules:
            module_pattern_v1 = r'##\s*功能模块\s*(\d+)[:：]\s*(.+?)(?=\n##|\Z)'
            matches_v1 = re.findall(module_pattern_v1, self.spec, re.DOTALL)
            
            for module_id, content in matches_v1:
                modules.append({
                    "id": f"module_{module_id}",
                    "name": content.split('\n')[0].strip(),
                    "content": content.strip()
                })
        
        return modules
    
    def get_file_structure(self) -> List[str]:
        """根据 Spec Kit 生成文件结构建议
        
        Returns:
            文件路径列表
        """
        # 这是一个简化的实现，实际应该根据 spec 和 tasks 智能生成
        # 参考 code_scratch 的 architecture.yaml，生成类似 files.json 的结构
        files = []
        
        # 根据模块和任务生成文件列表
        modules = self.extract_modules()
        tasks = self.extract_tasks()
        
        # 基础文件结构（可以根据项目类型调整）
        files.extend([
            "README.md",
            "requirements.txt",  # 或 package.json
            ".gitignore",
        ])
        
        # 根据模块生成文件
        for module in modules:
            module_name = module["name"].lower().replace(" ", "_")
            # 处理中文模块名
            if re.search(r'[\u4e00-\u9fff]', module_name):
                # 如果是中文，使用模块 ID
                module_name = module["id"].replace("module_", "")
            files.append(f"src/{module_name}/__init__.py")
            files.append(f"src/{module_name}/main.py")
        
        # 测试文件
        files.append("tests/__init__.py")
        files.append("tests/test_main.py")
        
        return files
    
    def extract_test_scripts(self) -> List[Dict]:
        """从 Spec Kit 中提取测试脚本信息
        
        测试脚本可能在以下位置定义：
        1. tasks.md 中的测试任务
        2. spec.md 中的测试规范
        3. plan.md 中的测试计划
        
        Returns:
            测试脚本列表，每个脚本包含 command, description, test_files 等字段
        """
        test_scripts = []
        
        # 从 tasks.md 中提取测试任务（支持中英文）
        if self.tasks:
            # 查找测试相关的任务（包含"测试"、"test"等关键词）
            test_patterns = [
                r'##\s*任务\s*(\d+)[:：].*?测试.*?(?=\n##|\Z)',
                r'##\s*Task\s*(\d+)[:：].*?[Tt]est.*?(?=\n##|\Z)',
            ]
            
            test_matches = []
            for test_pattern in test_patterns:
                test_matches = re.findall(test_pattern, self.tasks, re.DOTALL | re.IGNORECASE)
                if test_matches:
                    break
            
            for task_id, content in test_matches:
                # 提取测试命令（支持中英文）
                command_patterns = [
                    r'(?:命令|Command)[：:]\s*(.+?)(?=\n|$)',
                ]
                command = None
                for command_pattern in command_patterns:
                    command_match = re.search(command_pattern, content, re.IGNORECASE)
                    if command_match:
                        command = command_match.group(1).strip()
                        break
                
                # 提取测试文件（支持中英文）
                test_file_patterns = [
                    r'(?:测试文件|Test Files?)[：:]\s*(.+?)(?=\n|$)',
                ]
                test_files = []
                for test_file_pattern in test_file_patterns:
                    test_file_match = re.search(test_file_pattern, content, re.IGNORECASE)
                    if test_file_match:
                        test_files = [f.strip() for f in re.split(r'[,，、]', test_file_match.group(1)) if f.strip()]
                        break
                
                if command:
                    test_scripts.append({
                        "id": f"test_task_{task_id}",
                        "command": command,
                        "description": content.split('\n')[0].strip(),
                        "test_files": test_files,
                        "content": content.strip()
                    })
        
        # 如果没有找到测试脚本，尝试从 repo 目录查找测试文件
        # 这将在 Testing Agent 中处理
        
        return test_scripts
