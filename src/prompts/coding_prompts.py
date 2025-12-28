"""编码 Agent 提示词模板"""

from typing import Any, Dict, List, Optional


def build_coding_prompt(
    user_input: str,
    planning_output: Optional[str] = None,
    planning_mapping: Optional[Dict[str, List[str]]] = None,
    spec_kit: Optional[Dict[str, str]] = None,
    rollback_context: Optional[Dict[str, Any]] = None
) -> str:
    """构建编码提示词
    
    Args:
        user_input: 用户输入
        planning_output: 规划结果
        planning_mapping: 规划生成的映射关系
        spec_kit: Spec Kit 内容字典
        rollback_context: 回退上下文（包含上次失败的错误信息）
    
    Returns:
        格式化后的提示词
    """
    # 项目宪法必须完整引用（100%）
    constitution = spec_kit.get("constitution", "") if spec_kit else ""
    
    # 准备编码任务描述
    coding_task = user_input if user_input else "根据规划任务生成代码"
    
    # 准备 Spec Kit 内容
    spec_content = ""
    plan_content = ""
    tasks_content = ""
    if spec_kit:
        spec_content_raw = spec_kit.get("spec", "未找到")
        spec_content = spec_content_raw[:2500] + "..." if len(spec_content_raw) > 2500 else spec_content_raw
        
        plan_content_raw = spec_kit.get("plan", "未找到")
        plan_content = plan_content_raw[:1500] + "..." if len(plan_content_raw) > 1500 else plan_content_raw
        
        tasks_content_raw = spec_kit.get("tasks", "未找到")
        tasks_content = tasks_content_raw[:1500] + "..." if len(tasks_content_raw) > 1500 else tasks_content_raw
    
    # 构建任务-文件映射信息
    mapping_info = ""
    if planning_mapping:
        mapping_lines = []
        for task_id, code_files in planning_mapping.items():
            mapping_lines.append(f"- **{task_id}** → {', '.join(code_files)}")
        mapping_info = f"\n## 规划映射\n\n" + "\n".join(mapping_lines) + "\n"
    
    # 构建 Spec Kit 引用章节
    spec_kit_section = ""
    if spec_kit:
        spec_kit_section = f"""
### 功能规格（spec.md）
{spec_content}

### 实施计划（plan.md）
{plan_content}

### 任务分解（tasks.md）
{tasks_content}

"""
    
    # 构建回退上下文提示（如果有）
    rollback_section = ""
    if rollback_context and rollback_context.get("target_agent") == "coding":
        failed_tests = rollback_context.get("failed_tests", [])
        failed_tests_info = ""
        if failed_tests:
            failed_tests_info = "\n".join([
                f"  - 文件: {t.get('code_file', '未知')}\n    错误: {t.get('error_output', '无')[:200]}"
                for t in failed_tests[:3]
            ])
        
        rollback_section = f"""
# 🔴 重要：这是一次回退修复任务

上一次测试发现了问题，需要你修复代码。

## 回退原因
{rollback_context.get('reason', '测试未通过')}

## 错误分析
{rollback_context.get('error_analysis', '未提供详细分析')}

## 测试统计
- 通过率: {rollback_context.get('pass_rate', 0):.1f}%
- 失败数: {rollback_context.get('failed_count', 0)}/{rollback_context.get('total_count', 0)}

## 失败的测试
{failed_tests_info if failed_tests_info else "无详细信息"}

## 修复建议
{', '.join(rollback_context.get('suggestions', [])) if rollback_context.get('suggestions') else '请根据错误分析修复代码'}

---

**请针对上述问题修复代码，直接覆盖生成完整的代码文件。**

"""

    return f"""你是一位专业程序员。你的唯一任务是：**输出代码文件**。
{rollback_section}
# ⚠️ 严格禁止以下行为：
- ❌ 不要输出"项目规划总结"
- ❌ 不要输出"任务完成报告"
- ❌ 不要输出任务列表或文件清单表格
- ❌ 不要说"已创建"、"已完成"等描述性文字

# ✅ 你必须做的唯一事情：
直接输出代码块！每个文件使用以下格式：

```语言: repo/文件路径
完整的代码内容
```

# 立即开始输出代码

根据以下信息，直接输出每个文件的完整代码：

## 要生成的文件
{mapping_info if mapping_info else "请根据项目需求生成所有必要的代码文件"}

## 项目宪法
{constitution}

## Spec Kit 参考
{spec_kit_section}

---

**现在开始！直接输出第一个代码文件（以 ```语言: repo/文件路径 开头）：**
""".strip()
