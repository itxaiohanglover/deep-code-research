"""总结 Agent 提示词模板"""

import json
from typing import Any, Dict


def build_summary_prompt(
    mapping_summary: Dict[str, Any],
    spec_kit: Dict[str, str],
    scripts_info: str
) -> str:
    """构建总结提示词
    
    Args:
        mapping_summary: Spec-Code 映射总结
        spec_kit: Spec Kit 内容字典
        scripts_info: 脚本文件信息
    
    Returns:
        格式化后的提示词
    """
    # 准备 Spec Kit 信息
    spec_kit_section = ""
    if spec_kit:
        spec_kit_parts = ["### 项目背景（Spec Kit）", ""]
        
        if spec_kit.get("constitution"):
            constitution = spec_kit["constitution"]
            if len(constitution) > 1200:
                constitution = constitution[:1200] + "\n...（已截断）"
            spec_kit_parts.extend([
                "#### 项目宪法",
                "",
                constitution,
                ""
            ])
        
        if spec_kit.get("plan"):
            plan_content = spec_kit["plan"]
            if len(plan_content) > 1200:
                plan_content = plan_content[:1200] + "\n...（已截断）"
            spec_kit_parts.extend([
                "#### 原始实施计划",
                "",
                plan_content,
                ""
            ])
        
        if spec_kit.get("tasks"):
            tasks_content = spec_kit["tasks"]
            if len(tasks_content) > 1200:
                tasks_content = tasks_content[:1200] + "\n...（已截断）"
            spec_kit_parts.extend([
                "#### 原始任务分解",
                "",
                tasks_content,
                ""
            ])
        
        spec_kit_section = "\n".join(spec_kit_parts) + "\n"
    
    # 准备执行结果
    total_tasks = mapping_summary['stats']['total_tasks']
    total_code_files = mapping_summary['stats']['total_code_files']
    mapped_count = mapping_summary['stats']['mapped_count']
    
    # 准备映射详情
    mapping_detail = ""
    if mapping_summary["spec_to_code"]:
        mapping_str = json.dumps(mapping_summary["spec_to_code"], indent=2, ensure_ascii=False)
        if len(mapping_str) > 2000:
            mapping_str = mapping_str[:2000] + "\n..."
        mapping_detail = f"""#### 任务-代码映射（已成功实现）
```json
{mapping_str}
```

"""
    
    # 准备测试结果
    test_results_section = ""
    code_to_test = mapping_summary.get("code_to_test", {})
    if code_to_test:
        total_tests = 0
        passed_tests = 0
        for tests in code_to_test.values():
            for test in tests:
                total_tests += 1
                if test.get("result", {}).get("success", False):
                    passed_tests += 1
        
        test_results_section = f"""#### 测试结果

- 总测试数：{total_tests}
- 全部通过：{passed_tests == total_tests}

"""
    
    scripts_section = scripts_info + "\n" if scripts_info else ""
    
    return f"""# 角色定义
你是一位 Agent Skill 生成器。

# 核心任务
基于项目执行信息，生成一份 **ms-agent 兼容的 Agent Skill 文档**。
此 Skill 将被其他 AI Agent 加载和执行，因此必须包含清晰的计划和任务。

# 输入信息
{spec_kit_section}### 执行结果

- 完成任务数：{total_tasks}
- 生成代码文件数：{total_code_files}
- 映射完整度：{mapped_count}

{mapping_detail}{scripts_section}{test_results_section}

---

# SKILL.md 输出要求

生成一份**完整的 SKILL.md 文件**，格式如下：

## 1. YAML 前置元数据（必需）

```yaml
---
name: [简洁的 Skill 名称，最多 64 字符]
description: [功能描述，最多 1024 字符，说明此 Skill 的功能]
version: v0.1.0
author: DeepCode Research
tags: [相关标签，如 python、automation 等]
---
```

## 2. 内容结构

```markdown
# [Skill 名称]

## 概述
[简要描述 Skill 的目的和功能]

## 实施计划
[分步实施计划，清晰列出实现目标所需的步骤]
1. 步骤一：...
2. 步骤二：...

## 任务清单
[具体任务列表，每个任务应可独立执行]
- [ ] 任务 1：...
- [ ] 任务 2：...

## 脚本说明
[说明每个脚本文件的用途和使用方式]
- `script.py`：用途、执行方式

## 最佳实践
[提炼的可复用模式和最佳实践]
```

**重要说明**：
- name 不能超过 64 字符
- description 不能超过 1024 字符
- 计划和任务必须具体可执行
- 脚本说明应清晰，便于其他 Agent 理解和使用

**请直接输出完整的 SKILL.md 内容，以 `---` 开头：**
""".strip()
