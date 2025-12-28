"""反思 Agent 提示词模板"""

from typing import Any, Dict


def build_reflecting_prompt(
    test_results: Dict[str, Any],
    mapping_info: Dict[str, Any]
) -> str:
    """构建反思提示词
    
    Args:
        test_results: 测试结果字典，包含 all_tests、failed_tests、all_passed 等
        mapping_info: Spec-Code 映射验证信息，包含 mapped、unmapped、partial
    
    Returns:
        格式化后的提示词
    """
    total = test_results['total']
    passed = test_results['passed']
    failed = test_results['failed']
    
    # 准备映射验证信息
    mapping_status = ""
    if mapping_info.get('unmapped'):
        unmapped_count = len(mapping_info['unmapped'])
        mapping_status += f"""
## Spec-Code 映射状态

- 未映射的 Spec 任务：{unmapped_count}
  （表示 {unmapped_count} 个 Spec 任务没有对应的代码实现，可能是设计问题）

"""
    
    if mapping_info.get('partial'):
        partial_count = len(mapping_info['partial'])
        mapping_status += f"- 部分映射的任务：{partial_count}\n  （{partial_count} 个任务有代码但缺少测试）\n\n"
    
    # 准备失败测试详情
    failed_tests_detail = ""
    if test_results['failed_tests']:
        failed_tests_list = []
        for i, test in enumerate(test_results['failed_tests'], 1):
            error_output = test['output'][:1500]  # 限制长度
            code_file = test['code_file']
            spec_task_id = test['spec_task_id'] or '未知'
            test_script = test['test_script']
            
            failed_tests_list.append(f"""### 测试 {i}
- 代码文件：{code_file}
- Spec 任务：{spec_task_id}
- 测试脚本：{test_script}
- 错误输出：
```
{error_output}
```

""")
        failed_tests_detail = "## 失败测试详情\n\n" + "".join(failed_tests_list)
    else:
        failed_tests_detail = "## ✅ 所有测试通过\n\n"
    
    # 准备任务章节
    if test_results['all_passed']:
        task_section = """
## 任务说明
所有测试已通过。输出以下 JSON：

```json
{
  "next_phase": "summary",
  "reason": "所有测试通过，进入总结阶段"
}
```
"""
    else:
        task_section = """
## 任务说明
分析上述失败测试和映射状态，判断缺陷类型：

1. **设计缺陷**（Spec Kit 问题）：
   - 需求理解偏差、架构设计问题、接口定义错误
   - 未映射的 Spec 任务（unmapped tasks）通常表示设计问题
   - 需要返回需求阶段重新设计
   - 输出 `"next_phase": "phase2"`

2. **实现缺陷**（代码问题）：
   - 代码逻辑错误、语法错误、运行时错误
   - Spec 任务已映射但代码实现有误
   - 只需返回编码阶段修复代码
   - 输出 `"next_phase": "phase3"`

**决策提示**：
- 如果存在未映射的 Spec 任务，通常是设计缺陷
- 如果所有任务都已映射但测试失败，通常是实现缺陷

输出 JSON 格式：

```json
{
  "next_phase": "phase2 或 phase3",
  "defect_type": "design 或 implementation",
  "reason": "简要原因"
}
```

**仅输出 JSON，不要其他内容。**
"""
    
    return f"""# 角色定义
你是一位代码审查专家，负责分析测试结果并判断缺陷类型。

# 输入信息
## 测试结果

- 总测试数：{total}
- 通过：{passed}
- 失败：{failed}

{mapping_status}{failed_tests_detail}{task_section}
""".strip()
