"""规划 Agent 提示词模板"""

import json
from typing import Any, Dict, List


def build_planning_prompt(
    user_input: str,
    spec_kit: Dict[str, str],
    spec_metadata: Dict[str, Any],
    tasks: List[Dict[str, Any]],
    file_structure: List[str]
) -> str:
    """构建规划提示词
    
    Args:
        user_input: 用户输入
        spec_kit: Spec Kit 内容字典（包含 constitution、spec、plan、tasks）
        spec_metadata: Spec Kit 元数据
        tasks: 任务列表
        file_structure: 文件结构列表
    
    Returns:
        格式化后的提示词
    """
    # 准备 Spec Kit 内容
    constitution = spec_kit.get("constitution", "未找到")
    spec_content = spec_kit.get("spec", "未找到")
    if len(spec_content) > 2500:
        spec_content = spec_content[:2500] + "..."
    plan_content = spec_kit.get("plan", "未找到")
    if len(plan_content) > 1500:
        plan_content = plan_content[:1500] + "..."
    tasks_content = spec_kit.get("tasks", "未找到")
    if len(tasks_content) > 1500:
        tasks_content = tasks_content[:1500] + "..."
    
    # 构建任务列表
    task_list = []
    for i, task in enumerate(tasks, 1):
        task_id = task.get("id", f"task_{i}")
        task_desc = task.get("description", task.get("name", ""))
        task_deps = task.get("dependencies", [])
        task_list.append(f"{i}. **{task_id}**：{task_desc}")
        if task_deps:
            task_list.append(f"   依赖：{', '.join(task_deps)}")
    
    # 准备 JSON 示例
    file_structure_json = json.dumps(file_structure, indent=2, ensure_ascii=False)
    mapping_example_json = json.dumps({
        "task_1": ["src/module1/file1.py", "src/module1/file2.py"],
        "task_2": ["src/module2/file3.py"],
    }, indent=2, ensure_ascii=False)
    
    task_list_text = "\n".join(task_list)
    
    return f"""# 角色定义
你是一位资深软件项目经理，擅长项目规划和任务分解。

# 核心任务
基于 Spec Kit，生成文件列表（files.json）、任务规划，并建立映射关系（spec_code_mapping.json）。

# 输入信息
## Spec Kit 内容

### 项目宪法（constitution.md）
{constitution}

### 功能规格（spec.md）
{spec_content}

### 实施计划（plan.md）
{plan_content}

### 任务分解（tasks.md）
{tasks_content}

## 任务列表
{task_list_text}

# 执行说明

## 1. 生成文件列表
- 使用 `file_system.write_file` 工具创建 `repo/files.json`（必须使用相对路径）
- 格式：JSON 数组，示例：
```json
{file_structure_json}
```

## 2. 任务分组（重要：优化效率）
- 首先使用 `file_system.read_file` 读取 `repo/files.json`
- 然后使用 `split_to_sub_task` 工具对编码任务进行分组
- **分组大小：每组 5-8 个文件**（为效率优化，避免过多小组）
- 分组原则：
  - 按依赖关系（先底层模块，后上层模块）
  - 相关模块放在同一组（特别是完整的调用栈或相互依赖的模块）
  - 项目文件（package.json、README.md、requirements.txt）必须放在第一组
- **每个子任务提示词必须指明文件在 `repo/` 目录**
- **子任务读取文件时必须使用 `repo/` 前缀**（如 `repo/src/main.py`，而非 `src/main.py`）

## 3. 建立映射
- 使用 `file_system.write_file` 工具创建 `repo/spec_code_mapping.json`
- 格式示例：
```json
{mapping_example_json}
```
- 映射原则：
  - 每个任务映射到实现该任务的文件
  - 一个任务可映射到多个文件
  - 一个文件可对应多个任务
  - 确保所有任务都有对应的文件映射

## 4. 重要注意事项
- **所有文件路径必须使用相对路径**（相对于输出目录）
- **禁止使用绝对路径**（如 `/mnt/data/output/files.json`）
- 正确格式：`repo/files.json`、`repo/spec_code_mapping.json`

请开始规划：
""".strip()
