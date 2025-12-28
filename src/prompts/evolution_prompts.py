"""演进验证 Agent 提示词模板 - 验证和优化 Spec Kit 质量"""

from typing import Dict, Optional

from src.utils.context_manager import truncate_artifact


def build_evolution_prompt(
    user_input: str,
    spec_kit: Optional[Dict[str, str]] = None,
    requirements: Optional[str] = None,
    # 兼容旧接口
    spec_gen: Optional[str] = None,
) -> str:
    """构建演进验证提示词
    
    Args:
        user_input: 用户输入
        spec_kit: Spec Kit 文件字典 {constitution, spec, plan, tasks}
        requirements: 需求分析结果（用于验证）
        spec_gen: 兼容旧接口（已废弃，使用 spec_kit 代替）
    
    Returns:
        格式化后的提示词
    """
    # 构建 Spec Kit 内容
    spec_kit_content = _build_spec_kit_content(spec_kit, spec_gen)
    
    if not spec_kit_content:
        return user_input
    
    # 截断 requirements（保留 2000 字符）
    req_preview = truncate_artifact(requirements, max_chars=2000) if requirements else ""
    
    req_section = f"""
## 原始需求
{req_preview}
""" if req_preview else ""
    
    return f"""# 角色定义
你是一位资深技术文档评审专家和质量保证工程师。
你的任务是**验证和优化 Spec Kit 质量**，确保完整性、一致性和可执行性。

# 核心规则
1. **需求对齐**：Spec Kit 必须完整覆盖原始需求，无遗漏或偏离
2. **一致性检查**：四份文档（constitution、spec、plan、tasks）必须保持一致
3. **可执行性**：tasks.md 中的任务必须具体、可执行、有明确验证方式
4. **完整性**：每份文档必须包含所有必要章节
5. **无歧义**：不允许使用"可能"、"也许"、"应该有"等模糊词汇

# 输入信息
{req_section}
## Spec Kit 内容
{spec_kit_content}

# 任务说明
按以下步骤进行验证和优化：

## 1. 需求覆盖检查
- 原始需求中的所有功能点是否都体现在 spec.md 中？
- 是否有遗漏的需求？
- 是否有偏离原始需求的地方？

## 2. 四文档一致性检查
- constitution.md 中的设计原则是否体现在 spec.md 中？
- spec.md 中的功能需求是否在 plan.md 中有对应的实施计划？
- plan.md 中的开发阶段是否在 tasks.md 中有对应的具体任务？
- 技术栈选择在四份文档中是否一致？

## 3. 任务可执行性检查
- 每个任务是否有明确的文件路径？
- 任务依赖关系是否正确？
- 验证方式是否具体可操作？
- 任务粒度是否合适（通常每个任务 1-3 个文件）？

## 4. 完整性检查
- constitution.md 是否包含：项目目标、设计原则、架构原则、编码原则、约束条件？
- spec.md 是否包含：用户故事、功能需求、非功能需求、数据模型、接口定义？
- plan.md 是否包含：技术栈、目录结构、开发阶段、里程碑？
- tasks.md 是否包含：所有阶段任务、依赖关系、验证方式？

## 5. 质量检查
- 是否有需要替换为具体描述的模糊词汇？
- 是否有需要补充的边界情况？
- 是否有需要优化的结构或表达？

# 输出规范
按以下格式输出验证报告：

---

# Spec Kit 质量验证报告

## 1. 需求覆盖评估

### 1.1 覆盖情况
| 原始需求 | Spec 中对应内容 | 状态 |
|----------|----------------|------|
| [需求1] | [对应功能] | ✅ 已覆盖 / ❌ 缺失 / ⚠️ 部分覆盖 |

### 1.2 覆盖评分
- **覆盖率**：XX%
- **缺失项**：[列表]
- **偏离项**：[列表]

## 2. 四文档一致性检查

### 2.1 一致性矩阵
| 检查项 | constitution | spec | plan | tasks | 状态 |
|--------|--------------|------|------|-------|------|
| 技术栈 | [描述] | [描述] | [描述] | [描述] | ✅ / ❌ |
| 架构 | [描述] | [描述] | [描述] | [描述] | ✅ / ❌ |

### 2.2 发现的不一致
- [不一致1]：[问题] → [修复建议]
- [不一致2]：[问题] → [修复建议]

## 3. 任务可执行性评估

### 3.1 任务质量检查
| 任务 | 文件路径 | 依赖关系 | 验证方式 | 状态 |
|------|----------|----------|----------|------|
| Task-1.1 | ✅ 明确 / ❌ 缺失 | ✅ 正确 / ❌ 错误 | ✅ 具体 / ❌ 模糊 | ✅ / ⚠️ / ❌ |

### 3.2 问题任务
- [任务ID]：[问题] → [修复建议]

## 4. 完整性检查

### 4.1 文档完整性
| 文档 | 必需章节 | 状态 | 缺失内容 |
|------|----------|------|----------|
| constitution.md | [列表] | ✅ 完整 / ⚠️ 部分 | [缺失项] |
| spec.md | [列表] | ✅ / ⚠️ | [缺失项] |
| plan.md | [列表] | ✅ / ⚠️ | [缺失项] |
| tasks.md | [列表] | ✅ / ⚠️ | [缺失项] |

## 5. 质量改进建议

### 5.1 必须修复（关键）
1. [问题] → [具体修复方案]
2. [问题] → [具体修复方案]

### 5.2 建议优化
1. [优化建议]
2. [优化建议]

## 6. 综合评分

| 维度 | 评分 | 备注 |
|------|------|------|
| 需求覆盖 | X/10 | [备注] |
| 一致性 | X/10 | [备注] |
| 可执行性 | X/10 | [备注] |
| 完整性 | X/10 | [备注] |
| **总分** | **X/10** | [综合评估] |

## 7. 结论

- **是否可进入开发**：✅ 是 / ⚠️ 需小幅修复 / ❌ 需大幅修复
- **主要风险点**：[列表]
- **下一步建议**：[具体建议]

---

# 输出质量检查
- [ ] 逐项检查需求覆盖情况
- [ ] 检查四份文档的一致性
- [ ] 验证每个任务的可执行性
- [ ] 提供具体的修复建议
- [ ] 综合评分客观公正

请开始验证：
""".strip()


def _build_spec_kit_content(
    spec_kit: Optional[Dict[str, str]] = None,
    spec_gen: Optional[str] = None
) -> str:
    """构建 Spec Kit 内容（用于 prompt）
    
    Args:
        spec_kit: Spec Kit 文件字典
        spec_gen: 兼容旧接口的单字符串
        
    Returns:
        格式化的 Spec Kit 内容
    """
    # 如果提供了结构化的 spec_kit
    if spec_kit and isinstance(spec_kit, dict):
        sections = []
        
        # 按顺序处理各文档
        doc_order = [
            ("constitution", "项目宪法 (constitution.md)"),
            ("spec", "功能规格 (spec.md)"),
            ("plan", "实施计划 (plan.md)"),
            ("tasks", "任务分解 (tasks.md)"),
        ]
        
        for key, title in doc_order:
            content = spec_kit.get(key, "")
            if content:
                # 截断长内容（每个文档最多 3000 字符）
                preview = truncate_artifact(content, max_chars=3000)
                sections.append(f"### {title}\n\n{preview}")
        
        if sections:
            return "\n\n---\n\n".join(sections)
    
    # 兼容旧接口：单字符串
    if spec_gen:
        return spec_gen
    
    return ""
