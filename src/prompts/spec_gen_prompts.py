"""规格套件生成 Agent 提示词模板

优化策略：
1. 添加 few-shot 示例片段，提升输出格式一致性
2. 强化结构化约束，确保每个章节都存在
3. 明确输出格式要求，便于下游解析

推荐使用单文档生成函数：
- build_constitution_prompt
- build_spec_prompt
- build_plan_prompt
- build_tasks_prompt

废弃函数：
- build_spec_gen_prompt（旧版，使用代码块格式，已不推荐）
"""

import warnings
from typing import Dict, Optional

from src.prompts.risk_prompts import build_artifact_sections


# Tasks 文档的 few-shot 示例（用于解析器正确提取任务）
TASKS_FEW_SHOT = """
## 示例（参考格式）

### 阶段一：基础设施

**Task-1.1: 项目初始化**
- **Goal**: 搭建项目基础结构
- **Dependencies**: 无
- **创建/修改文件**:
  - `src/__init__.py`
  - `src/main.py`
  - `requirements.txt`
- **详细步骤**:
  1. 创建项目目录结构
  2. 初始化 requirements.txt
  3. 创建入口文件
- **验证方式**: `python -m pytest` 通过

**Task-1.2: 配置管理**
- **Goal**: 实现配置加载
- **Dependencies**: Task-1.1
- **创建/修改文件**:
  - `src/config.py`
- **详细步骤**:
  1. 定义配置类
  2. 实现环境变量加载
- **验证方式**: 配置加载测试通过

---
"""


# Spec 文档的 few-shot 示例
SPEC_FEW_SHOT = """
## 示例（参考格式）

### US-001: 用户登录
- **作为**: 注册用户
- **我想要**: 使用用户名密码登录
- **以便**: 访问系统功能
- **验收标准**:
  - [ ] AC-001: 输入正确凭据后跳转到首页
  - [ ] AC-002: 输入错误凭据后显示错误提示

### FR-001: 登录验证
- **描述**: 验证用户凭据
- **输入**: 用户名、密码
- **处理**: 比对数据库记录
- **输出**: 验证结果（成功/失败）
- **异常处理**: 账户锁定、网络超时

---
"""


def build_spec_gen_prompt(
    user_input: str,
    requirements: Optional[str] = None,
    tech_research: Optional[str] = None,
    architecture: Optional[str] = None,
    risk: Optional[str] = None
) -> str:
    """构建规格套件生成提示词
    
    .. deprecated::
        此函数已废弃，使用代码块格式输出，容易被截断。
        请使用 build_constitution_prompt, build_spec_prompt, 
        build_plan_prompt, build_tasks_prompt 替代。
    
    Args:
        user_input: 用户输入
        requirements: 需求分析结果
        tech_research: 技术研究结果
        architecture: 架构设计结果
        risk: 风险评估结果
    
    Returns:
        格式化后的提示词
    """
    warnings.warn(
        "build_spec_gen_prompt 已废弃，请使用 build_constitution_prompt 等单文档函数",
        DeprecationWarning,
        stacklevel=2
    )
    
    artifacts = {
        "requirements": requirements or "",
        "tech_research": tech_research or "",
        "architecture": architecture or "",
        "risk": risk or "",
    }
    
    sections = build_artifact_sections(artifacts)
    
    if not sections:
        return user_input
    
    sections_text = "\n\n".join(sections)
    
    return f"""# 已废弃
此函数已废弃，请使用单文档生成函数。

{sections_text}
""".strip()


def build_constitution_prompt(
    user_input: str,
    requirements: Optional[str] = None,
    tech_research: Optional[str] = None,
    architecture: Optional[str] = None,
    risk: Optional[str] = None
) -> str:
    """构建 constitution.md 生成提示词
    
    生成项目宪法文档，包含：
    - 项目目标和成功标准
    - 设计原则
    - 架构原则
    - 编码原则
    - 约束条件
    - 质量标准
    
    注意：直接输出 markdown 内容，不需要代码块包裹。
    """
    artifacts = {
        "requirements": requirements or "",
        "architecture": architecture or "",
    }
    
    sections = build_artifact_sections(artifacts)
    sections_text = "\n\n".join(sections) if sections else ""
    
    return f"""# 角色定义

你是一位资深技术文档架构师。基于前期研究成果，生成 **constitution.md**（项目宪法）文档。

# 核心要求

1. **完整性**：必须包含所有 6 个章节
2. **具体性**：每个原则和标准必须具体可执行
3. **一致性**：与需求和架构保持一致

# 输入信息

{sections_text}

# 输出规范

**直接输出 markdown 文档内容**，不需要用代码块包裹。

必须包含以下 6 个章节：

```
# 项目宪法：[项目名称]

## 1. 项目目标
- **核心价值**：[一句话描述产品价值]
- **目标用户**：[具体的用户画像]
- **成功标准**：[如何衡量项目成功]

## 2. 设计原则
- **原则一**：[名称] - [描述]
- **原则二**：[名称] - [描述]
- **原则三**：[名称] - [描述]

## 3. 架构原则
- **架构风格**：[选择的架构模式]
- **核心约束**：[架构层面的约束]
- **扩展策略**：[如何支持未来扩展]

## 4. 编码原则
- **代码风格**：[Linter/Formatter 规则]
- **命名规范**：[变量/函数/类的命名规则]
- **错误处理**：[统一的错误处理策略]
- **日志规范**：[日志格式和级别]

## 5. 约束条件
- **技术约束**：[必须/不能使用的技术]
- **环境约束**：[运行环境要求]
- **资源约束**：[时间/性能/存储限制]

## 6. 质量标准
- **测试覆盖**：[测试要求]
- **性能指标**：[性能要求]
- **文档要求**：[文档标准]
```

**开始生成：**
""".strip()


def build_spec_prompt(
    user_input: str,
    requirements: Optional[str] = None,
    tech_research: Optional[str] = None,
    architecture: Optional[str] = None,
    risk: Optional[str] = None
) -> str:
    """构建 spec.md 生成提示词
    
    生成功能规格文档，包含：
    - 概述和范围边界
    - 用户故事与验收标准（US-xxx 格式）
    - 功能需求（FR-xxx 格式）
    - 非功能需求（NFR-xxx 格式）
    - 数据模型
    - 接口定义
    
    注意：直接输出 markdown 内容，不需要代码块包裹。
    """
    artifacts = {
        "requirements": requirements or "",
        "architecture": architecture or "",
    }
    
    sections = build_artifact_sections(artifacts)
    sections_text = "\n\n".join(sections) if sections else ""
    
    return f"""# 角色定义

你是一位资深技术文档架构师。基于前期研究成果，生成 **spec.md**（功能规格）文档。

# 核心要求

1. **完整性**：必须包含所有 6 个章节
2. **可验证性**：每个用户故事必须有验收标准
3. **无歧义**：不使用"可能"、"也许"等模糊词汇

{SPEC_FEW_SHOT}

# 输入信息

{sections_text}

# 输出规范

**直接输出 markdown 文档内容**，不需要用代码块包裹。

必须包含以下 6 个章节：

```
# 功能规格：[项目名称]

## 1. 概述
- **核心功能**：[一句话描述]
- **范围边界**：
  - **做**：[核心范围]
  - **不做**：[明确排除的功能]

## 2. 用户故事与验收标准

### US-001: [故事名称]
- **作为**：[角色]
- **我想要**：[操作]
- **以便**：[价值]
- **验收标准**：
  - [ ] AC-001：[具体可验证的标准]
  - [ ] AC-002：[具体可验证的标准]

### US-002: [故事名称]
...

## 3. 功能需求

### FR-001: [功能名称]
- **描述**：[功能描述]
- **输入**：[输入数据]
- **处理**：[处理逻辑]
- **输出**：[输出结果]
- **异常处理**：[异常情况]

### FR-002: [功能名称]
...

## 4. 非功能需求
- **NFR-001 性能**：[具体指标]
- **NFR-002 安全**：[安全要求]
- **NFR-003 可用性**：[可用性要求]

## 5. 数据模型
### 核心实体
- **实体1**：[属性列表]
- **实体2**：[属性列表]

### 数据流
[数据流描述]

## 6. 接口定义
### API 接口
- `POST /api/xxx`：[输入/输出]
- `GET /api/xxx`：[输入/输出]

### 模块接口
- `module.function()`：[描述]
```

**开始生成：**
""".strip()


def build_plan_prompt(
    user_input: str,
    requirements: Optional[str] = None,
    tech_research: Optional[str] = None,
    architecture: Optional[str] = None,
    risk: Optional[str] = None
) -> str:
    """构建 plan.md 生成提示词
    
    生成实施计划文档，包含：
    - 技术栈表格
    - 目录结构
    - 开发阶段
    - 里程碑
    - 风险应对
    
    注意：直接输出 markdown 内容，不需要代码块包裹。
    """
    artifacts = {
        "tech_research": tech_research or "",
        "architecture": architecture or "",
        "risk": risk or "",
    }
    
    sections = build_artifact_sections(artifacts)
    sections_text = "\n\n".join(sections) if sections else ""
    
    return f"""# 角色定义

你是一位资深技术文档架构师。基于前期研究成果，生成 **plan.md**（实施计划）文档。

# 核心要求

1. **完整性**：必须包含所有 5 个章节
2. **可执行性**：每个阶段必须有明确的目标和验证方式
3. **风险意识**：必须识别关键风险并提供应对措施

# 输入信息

{sections_text}

# 输出规范

**直接输出 markdown 文档内容**，不需要用代码块包裹。

必须包含以下 5 个章节：

```
# 实施计划：[项目名称]

## 1. 技术栈
| 类别 | 技术 | 版本 | 用途 |
|------|------|------|------|
| 语言 | [技术] | [版本] | [用途] |
| 框架 | [技术] | [版本] | [用途] |
| 数据库 | [技术] | [版本] | [用途] |
| 测试 | [技术] | [版本] | [用途] |

## 2. 目录结构
```text
project/
├── src/
│   ├── module1/
│   │   ├── __init__.py
│   │   └── main.py
│   └── module2/
│       └── ...
├── tests/
│   └── test_*.py
├── README.md
├── requirements.txt
└── ...
```

## 3. 开发阶段

### 阶段一：基础设施
- **目标**：搭建项目脚手架
- **文件**：[文件列表]
- **验证方式**：[如何验证完成]

### 阶段二：核心功能
- **目标**：实现核心业务逻辑
- **文件**：[文件列表]
- **验证方式**：[如何验证完成]

### 阶段三：用户界面/API
- **目标**：实现外部接口
- **文件**：[文件列表]
- **验证方式**：[如何验证完成]

### 阶段四：测试与优化
- **目标**：完成测试和优化
- **文件**：[文件列表]
- **验证方式**：[如何验证完成]

## 4. 里程碑
| 里程碑 | 目标 | 交付物 |
|--------|------|--------|
| M1 | [目标] | [交付物] |
| M2 | [目标] | [交付物] |

## 5. 风险应对
| 风险 | 影响 | 应对措施 |
|------|------|----------|
| [风险1] | [影响] | [措施] |
| [风险2] | [影响] | [措施] |
```

**开始生成：**
""".strip()


def build_tasks_prompt(
    user_input: str,
    requirements: Optional[str] = None,
    tech_research: Optional[str] = None,
    architecture: Optional[str] = None,
    risk: Optional[str] = None
) -> str:
    """构建 tasks.md 生成提示词
    
    生成开发任务清单文档，包含：
    - 按阶段分解的任务（Task-X.Y 格式）
    - 每个任务的详细信息（目标、文件、步骤、验证方式）
    - 任务依赖图
    - 验收清单
    
    重要：任务格式必须遵循特定格式，便于解析器提取。
    
    注意：直接输出 markdown 内容，不需要代码块包裹。
    """
    artifacts = {
        "requirements": requirements or "",
        "architecture": architecture or "",
    }
    
    sections = build_artifact_sections(artifacts)
    sections_text = "\n\n".join(sections) if sections else ""
    
    return f"""# 角色定义

你是一位资深技术文档架构师。基于前期研究成果，生成 **tasks.md**（开发任务清单）文档。

# 核心要求

1. **格式严格**：每个任务必须使用 **Task-X.Y: 任务名称** 格式（加粗）
2. **文件锚定**：每个任务必须指定具体的文件路径
3. **依赖清晰**：明确标注任务依赖关系
4. **可验证**：每个任务必须有验证方式

{TASKS_FEW_SHOT}

# 输入信息

{sections_text}

# 输出规范

**直接输出 markdown 文档内容**，不需要用代码块包裹。

**关键格式要求**：
- 任务 ID 格式：`**Task-X.Y: 任务名称**`（必须加粗，X 是阶段号，Y 是序号）
- Dependencies 格式：`- **Dependencies**: Task-1.1` 或 `- **Dependencies**: 无`
- Goal 格式：`- **Goal**: 任务目标描述`

必须包含以下结构：

```
# 开发任务清单：[项目名称]

## 阶段一：基础设施

**Task-1.1: [任务名称]**
- **Goal**: [简要描述]
- **Dependencies**: 无
- **创建/修改文件**:
  - `src/path/to/file1.py`
  - `src/path/to/file2.py`
- **参考文件**:
  - `src/types/index.py`
- **详细步骤**:
  1. 创建 xxx 文件
  2. 实现 xxx 函数
  3. 导出模块
- **验证方式**: [如何验证完成]
- **完成定义**: [DoD]

**Task-1.2: [任务名称]**
- **Goal**: [简要描述]
- **Dependencies**: Task-1.1
...

## 阶段二：核心功能

**Task-2.1: [任务名称]**
...

## 阶段三：用户界面/API

**Task-3.1: [任务名称]**
...

## 阶段四：测试与优化

**Task-4.1: [任务名称]**
...

---

## 任务依赖图
```text
Task-1.1 → Task-1.2 → Task-2.1
                ↓
           Task-2.2 → Task-3.1
                         ↓
                    Task-4.1
```

## 验收清单
- [ ] 所有任务都有明确的文件路径
- [ ] 任务按依赖关系排序
- [ ] 每个任务都有验证方式
- [ ] 包含集成测试任务
```

**开始生成：**
""".strip()
