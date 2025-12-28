"""风险评估 Agent 提示词模板"""

from typing import Dict, Optional

from src.utils.context_manager import fit_artifacts_for_prompt, truncate_artifact


def build_artifact_sections(artifacts: Dict[str, str]) -> list[str]:
    """构建产物章节
    
    Args:
        artifacts: 产物字典，格式：{名称: 内容}
    
    Returns:
        章节列表（Markdown 格式）
    """
    sections = []
    for name, content in artifacts.items():
        if content:
            title_map = {
                "requirements": "需求分析",
                "tech_research": "技术研究",
                "architecture": "架构设计",
                "risk": "风险评估",
                "spec_gen": "规格套件",
                "planning": "开发规划",
                "coding": "代码实现",
                "testing": "测试报告",
                "reflecting": "反思报告",
            }
            title = title_map.get(name, name.replace("_", " ").title())
            sections.append(f"## {title}\n\n{content}")
    return sections


def build_risk_prompt(
    user_input: str,
    requirements: Optional[str] = None,
    tech_research: Optional[str] = None,
    architecture: Optional[str] = None
) -> str:
    """构建风险评估提示词
    
    Args:
        user_input: 用户输入
        requirements: 需求分析结果
        tech_research: 技术研究结果
        architecture: 架构设计结果
    
    Returns:
        格式化后的提示词
    """
    # 使用 ContextManager 智能分配空间（总共 6000 字符，按优先级分配）
    artifacts = {
        "architecture": architecture or "",
        "requirements": requirements or "",
        "tech_research": tech_research or "",
    }
    
    # 架构设计优先级最高（风险评估重点关注架构）
    fitted = fit_artifacts_for_prompt(
        artifacts,
        max_total_chars=6000,
        priorities=["architecture", "requirements", "tech_research"]
    )
    
    arch_preview = fitted.get("architecture") or user_input
    req_preview = fitted.get("requirements", "")
    tech_preview = fitted.get("tech_research", "")
    
    input_sections = []
    if req_preview:
        input_sections.append(f"## 需求分析\n{req_preview}")
    if tech_preview:
        input_sections.append(f"## 技术研究\n{tech_preview}")
    if arch_preview:
        input_sections.append(f"## 架构设计\n{arch_preview}")
    
    if not input_sections:
        return user_input
    
    input_text = "\n\n".join(input_sections)
    
    return f"""# 角色定义
你是一位资深风险评估专家，擅长识别和评估项目风险，并制定有效的应对策略。

# 核心任务
识别和评估项目风险，提供风险缓解策略。聚焦于 3-5 个最高优先级的风险。

# 输入信息
{input_text}

# 输出规范
使用 Markdown 格式输出。内容精炼，仅列出 3-5 个高优先级风险。

---

## 1. 技术风险

| 风险ID | 风险项 | 影响程度 | 发生概率 | 风险指数 | 应对策略 |
|--------|--------|----------|----------|----------|----------|
| TR-001 | [风险名称] | 高/中/低 | 高/中/低 | 高/中/低 | [简要策略] |
| TR-002 | [风险名称] | 高/中/低 | 高/中/低 | 高/中/低 | [简要策略] |

**详细分析**（仅针对高风险项，最多3个）：

### TR-001: [风险名称]
| 维度 | 说明 |
|------|------|
| **风险描述** | [详细描述] |
| **触发条件** | [什么情况下可能发生] |
| **影响范围** | [对项目的具体影响] |
| **证据/依据** | [CVE 或已知问题，如有] |

**应对策略**：
- **预防措施**：[如何避免]
- **应急预案**：[发生时如何处理]
- **备选方案**：[替代解决方案]

## 2. 实施风险
（列出 3 个最关键的实施风险）

### 2.1 [风险点]
- **风险评估**：[说明]
- **应对策略**：[具体措施]

### 2.2 [风险点]
...

## 3. 运维风险
（列出 3 个最关键的运维风险）

### 3.1 [风险点]
- **风险评估**：[说明]
- **应对策略**：[具体措施]

## 4. 项目风险
（列出 3 个最关键的项目风险）

### 4.1 [风险点]
- **应对策略**：[具体措施]

## 5. 风险矩阵

### 高优先级（高影响 + 高概率）
1. [风险ID]：[风险名称] - 策略：[主要应对策略]

### 中优先级
1. [风险ID]：[风险名称] - 策略：[应对策略]

---

# 输出质量检查
- [ ] 覆盖技术、实施、运维、项目四类风险
- [ ] 风险评估客观、有据可依
- [ ] 应对策略具体可执行
- [ ] 高风险项有详细分析和备选方案
- [ ] 检查了常见漏洞和已知问题
- [ ] 优先级排序清晰
- [ ] 内容精炼无冗余

请开始风险评估：
""".strip()
