# DeepCodeResearch

> 🔬 基于 MS-Agent 框架的智能深度代码研究系统，实现从需求到代码的自动化生成。

---

## 📝 项目介绍

DeepCodeResearch 是一个基于 MS-Agent 框架的智能代码生成系统，实现了从需求到代码的自动化生成。系统采用**多 Agent 协作**的架构，通过**11 个专业 Agent** 分工协作，完成从需求分析到代码生成再到测试优化的完整流程。

### 项目背景

随着人工智能技术的飞速发展，代码生成和自动补全已经成为软件开发领域的重要研究方向。本项目旨在通过深度学习技术，实现从需求描述到代码生成的自动化过程，提高软件开发效率，降低人力成本。

### 项目目标

- 实现从需求描述到代码生成的自动化过程。

## 🏗️ 系统架构

### 整体架构图

![DeepCodeResearchWorkflow](./asset/DeepCodeResearchWorkflow.png)

分析阶段：

![analysis_phase](./asset/analysis_phase.png)

生成阶段：

![generate_phase](./asset/generate_phase.png)

审查阶段：

![review_phase](./asset/review_phase.png)

### 核心组件

| 组件 | 说明 |
|------|------|
| **11 个专业 Agent** | 分工明确，各司其职，通过产物链式协作，统一继承 BaseAgent |
| **工作流引擎** | 基于 MS-Agent 的 ChainWorkflow，支持迭代执行和会话管理 |
| **产物管理系统** | ArtifactStore + 文件系统，统一管理所有产物，支持按会话和迭代分类 |
| **路径管理器** | PathManager 统一管理所有输出路径，支持按会话分类，Skills 常驻 |
| **配置处理器** | ConfigHandler 统一处理配置生命周期，自动设置 session 目录 |
| **工具函数模块** | agent_utils 提供公共逻辑（消息提取、映射处理等） |
| **Mock 系统** | 支持快速测试，无需调用真实 LLM |

---

## 🚀 快速启动

### 1. 环境准备

```bash
# 创建 Conda 环境（推荐 Python 3.12）
conda create -n deep-code python=3.12
conda activate deep-code

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置 API Key

创建 `.env` 文件：

```bash
# ModelScope API 配置（必需）
MODELSCOPE_API_KEY=your_api_key
MODELSCOPE_BASE_URL=https://api-inference.modelscope.cn/v1

# 输出目录配置（可选，默认 ./output）
OUTPUT_DIR=./output

# 工作流配置（可选，默认 src/config/workflow.yaml）
WORKFLOW_CONFIG=src/config/workflow.yaml

# 是否信任远程代码（可选，默认 true）
TRUST_REMOTE_CODE=true
```

> 💡 **提示**：ModelScope API Key 可在 [ModelScope 控制台](https://modelscope.cn/my/myaccesstoken) 获取

### 3. 准备输入文档（可选）

将需要研究的文档放入 `output/{session_id}/uploads/` 目录（首次运行会自动创建会话目录）：

```
output/{session_id}/uploads/
├── requirement.pdf      # 需求文档
├── architecture.docx    # 架构设计文档
├── reference.pptx       # 参考资料
└── screenshot.png       # 界面截图
```

> 💡 **提示**：会话 ID 会在工作流启动时自动生成（12 位十六进制字符串），也可以通过环境变量 `SESSION_ID` 手动指定。

### 4. 启动服务

**方式一：命令行直接运行**

```bash
python -m src.main "请帮我生成一个贪吃蛇小游戏"
```

**方式二：Python API 调用**

```python
from src.main import run_workflow
import asyncio

result = asyncio.run(run_workflow(
    query="实现一个 REST API 服务器，支持用户注册和登录",
    files=["path/to/document.pdf"]
))
```

---

## 📁 项目结构

### 源代码结构

```
deep-code-research-new/
├── src/                              # 源代码目录
│   ├── agents/                       # Agent 实现
│   │   ├── _base_agent.py           # Agent 基类（统一代码模式）
│   │   ├── mixins.py                # Mixin（MockMixin, ArtifactStoreMixin）
│   │   ├── analysis/                # 分析阶段 Agent（6个）
│   │   │   ├── requirements.py
│   │   │   ├── tech_research.py
│   │   │   ├── architecture.py
│   │   │   ├── risk.py
│   │   │   ├── spec_gen.py
│   │   │   └── evolution.py
│   │   ├── generate/                # 生成阶段 Agent（3个）
│   │   │   ├── planning.py
│   │   │   ├── coding.py
│   │   │   └── testing.py
│   │   └── review/                  # 审查阶段 Agent（2个）
│   │       ├── reflecting.py
│   │       └── summary.py
│   │
│   ├── config/                      # 配置文件
│   │   ├── config_handler.py        # 配置生命周期处理器
│   │   ├── workflow.yaml            # 工作流配置
│   │   ├── agents/                  # Agent 配置
│   │   │   ├── _base.yaml          # 基础配置（可复用）
│   │   │   ├── analysis/           # 分析阶段配置
│   │   │   ├── generate/            # 生成阶段配置
│   │   │   └── review/              # 审查阶段配置
│   │   └── mocks/                   # Mock 文件（测试用）
│   │
│   ├── tools/                        # 工具模块
│   │   ├── document/                # 文档处理（PDF/PPT/DOCX/TXT）
│   │   ├── spec/                    # SpecKit 工具
│   │   ├── tracker/                 # Spec-Code 关联追踪
│   │   ├── code/                    # 代码处理工具
│   │   └── ...
│   │
│   ├── workflows/                    # 工作流实现
│   │   └── deepcode_workflow.py
│   │
│   ├── callbacks/                    # 回调函数
│   │   ├── artifact_callback.py     # 产物保存回调
│   │   ├── spec_metadata_callback.py # SpecKit 元数据回调
│   │   └── workflow_callback.py     # 工作流回调
│   │
│   └── utils/                        # 工具函数
│       ├── agent_utils.py           # Agent 工具函数（提取公共逻辑）
│       ├── artifact_store.py        # 产物存储
│       ├── path_manager.py         # 路径管理
│       ├── path_resolver.py         # 路径解析
│       ├── workflow_manager.py     # 工作流管理
│       └── encoding_patch.py       # 编码补丁（修复 Windows 编码问题）
```

### 输出目录结构

```
output/
├── skills/                           # Agent Skills（常驻，所有会话共享）
│   └── skill_*.md
│
└── {session_id}/                     # 按会话分类（会话 ID 为 12 位十六进制字符串）
    ├── artifacts/                    # 文本产物（按迭代分类）
    │   └── iteration_{N}/
    │       ├── requirements.md
    │       ├── tech_research.md
    │       ├── architecture.md
    │       ├── spec_gen.md
    │       ├── planning.md
    │       ├── coding.md
    │       ├── testing.md
    │       ├── reflecting.md
    │       └── summary.md
    │
    ├── repo/                         # 生成的代码仓库
    │   ├── src/
    │   ├── tests/
    │   ├── README.md
    │   ├── requirements.txt
    │   ├── files.json                # 文件列表
    │   └── spec_code_mapping.json    # Spec-Code 映射关系
    │
    ├── spec_kit/                     # Spec Kit 文档
    │   ├── constitution.md           # 项目章程
    │   ├── spec.md                   # 功能规范
    │   ├── plan.md                   # 实现计划
    │   ├── tasks.md                  # 任务分解
    │   └── spec_metadata.json       # Spec Kit 元数据
    │
    ├── memory/                       # 记忆存储（JSON/YAML）
    │   ├── requirements.json
    │   ├── requirements.yaml
    │   ├── tech_research.json
    │   └── ...
    │
    ├── uploads/                      # 用户上传文档
    │   └── ...
    │
    └── rag_index/                    # RAG 索引
        └── ...
```

**路径说明**：
- **按会话分类**：每个会话的所有文件都保存在 `output/{session_id}/` 下，会话之间完全隔离
- **Skills 常驻**：`output/skills/` 目录所有会话共享，用于存储可复用的 Agent Skills
- **Artifacts 按迭代**：文本产物保存在 `output/{session_id}/artifacts/iteration_{N}/` 下，支持多轮迭代
- **Memory 按会话**：记忆文件（JSON/YAML）保存在 `output/{session_id}/memory/` 下，不会创建全局的 `output/memory/` 目录

---

## 🛠️ 技术栈

| 类别 | 技术 |
|------|------|
| **框架** | MS-Agent 1.5.0 |
| **LLM** | Qwen3 / Qwen2.5（通过 ModelScope API） |
| **配置管理** | OmegaConf |
| **Web 框架** | FastAPI + Uvicorn（待实现） |
| **文档处理** | Docling, python-docx, python-pptx |
| **RAG** | LlamaIndex |
| **向量数据库** | Qdrant / ChromaDB |
| **记忆管理** | Mem0 |
| **搜索** | Exa, SerpAPI |

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

---

## 📄 许可证

详见 [LICENSE](../LICENSE)

---

## 🙏 致谢

- [MS-Agent](https://github.com/modelscope/ms-agent) - 轻量级 Agent 框架

## 参考文献

- Zhang, G. B., Fu, M. X., Wan, G. C., Yu, M., Wang, K., Yan, S. C. (2025). G-Memory: Tracing hierarchical memory for multi-agent systems. arXiv preprint arXiv:2506.07398 (cs.MA). https://arxiv.org/abs/2506.07398
- Chen, Z. L., Tang, X. R., Deng, G. D., Wu, F., Wu, J. L., Jiang, Z. W., Prasanna, V., Cohan, A., Wang, X. Y. (2025). LocAgent: Graph-guided LLM agents for code localization. arXiv preprint arXiv:2503.09089 (cs.SE). https://arxiv.org/abs/2503.09089
- Liu, J. W., Xu, C., Wang, C., Bai, T., Chen, W. T., Wong, K., Lou, Y. L., Peng, X. (2025). EvoDev: An iterative feature-driven framework for end-to-end software development with LLM-based agents. arXiv preprint arXiv:2511.02399 (cs.SE). https://arxiv.org/abs/2511.02399
- Xia, C.S., Zhang, L.: Conversational automated program repair. arXiv preprint arXiv:2301.13246 (2023). https://doi.org/10.48550/arXiv.2301.13246
- Wei, J., Wang, X., Schuurmans, D., Bosma, M., Ichter, B., Xia, F., Chi, E.H., Le, Q.V., Zhou, D.: Chain-of-thought prompting elicits reasoning in large language models. In: Advances in Neural Information Processing Systems 35 (NeurIPS 2022), pp. 24824--24837 (2022). https://doi.org/10.48550/arXiv.2201.11903
- Madaan, A., Tandon, N., Gupta, P., Hallinan, S., Gao, L., Wiegreffe, S., Alon, U., Dziri, N., Prabhumoye, S., Yang, Y., Gupta, S., Majumder, B.P., Hermann, K., Welleck, S., Yazdanbakhsh, A., Clark, P.: Self-Refine: Iterative refinement with self-feedback. arXiv preprint arXiv:2303.17651 (2023). https://doi.org/10.48550/arXiv.2303.17651
- Talebirad, Y., Nadiri, A.: Multi-agent collaboration: Harnessing collective intelligence with LLMs. arXiv preprint arXiv:2306.03314 (2023). https://doi.org/10.48550/arXiv.2306.03314
- Hong, Z., Zhou, B., Song, X., Shen, Y., Guan, C., Cai, Z., Sun, Z., Wang, W., Wang, B., Zhang, Y.: MetaGPT: Meta programming for multi-agent collaborative framework. arXiv preprint arXiv:2308.00352 (2023). https://doi.org/10.48550/arXiv.2308.00352
- Qian, C., Fan, S., Sun, X., Jiang, Z., Xu, R., Zhang, C., Zhang, Y.: ChatDev: Communicative agents for software development. arXiv preprint arXiv:2307.07924 (2023). https://doi.org/10.48550/arXiv.2307.07924
- Huang, D., Bu, Q., Qing, Y., Cui, H.: CodeCoT: Tackling code syntax errors in CoT reasoning for code generation. arXiv preprint arXiv:2308.08784 (2024). https://doi.org/10.48550/arXiv.2308.08784
- Pan, R., Zhang, H., Liu, C.: CodeCoR: An LLM-based self-reflective multi-agent framework for code generation. arXiv preprint arXiv:2501.07811 (2025). https://doi.org/10.48550/arXiv.2501.07811
- Islam, M.A., Ali, M.E., Parvez, M.R.: MapCoder: Multi-agent code generation for competition-level problem solving. arXiv preprint arXiv:2405.11403 (2024). https://doi.org/10.48550/arXiv.2405.11403
- Li, H., Shi, Y., Lin, S., Gu, X., Lian, H., Wang, X., Jia, Y., Huang, T., Wang, Q.: SWE-Debate: Competitive multi-agent debate for software issue resolution. arXiv preprint arXiv:2507.23348 (2025). https://doi.org/10.48550/arXiv.2507.23348
- Baqar, M., Khanda, R.: The future of software testing: AI-powered test case generation and validation. In: CompCom 2025. Springer, Cham (2025). https://doi.org/10.1007/978-3-031-92605-1; arXiv preprint arXiv:2409.05808 (2025). https://doi.org/10.48550/arXiv.2409.05808
- Jiang, X., Dong, Y., Wang, L., Fang, Z., Shang, Q., Li, G., Jin, Z., Jiao, W.: Self-planning code generation with large language models. ACM Transactions on Software Engineering and Methodology 33, 1--30 (2024). https://doi.org/10.48550/arXiv.2303.06689
- Yasunaga, M., Chen, X., Li, Y., Pasupat, P., Leskovec, J., Liang, P., Chi, E.H., Zhou, D.: Large language models as analogical reasoners. In: International Conference on Learning Representations (ICLR 2024). arXiv preprint arXiv:2310.01714 (2024). https://doi.org/10.48550/arXiv.2310.01714
- Islam, M.A., Ali, M.E., Parvez, M.R.: CODESIM: Multi-agent code generation and problem solving through simulation-driven planning and debugging. In: Findings of the 2025 Conference of the North American Chapter of the Association for Computational Linguistics (NAACL 2025). arXiv preprint arXiv:2502.05664 (2025). https://doi.org/10.48550/arXiv.2502.05664
- Nijkamp, E., Pang, B., Hayashi, H., Tu, L., Wang, H., Zhou, Y., Savarese, S., Xiong, C.: CodeGen: An open large language model for code with multi-turn program synthesis. arXiv preprint arXiv:2203.13474 (2022). https://doi.org/10.48550/arXiv.2203.01347
- Luo, Z., Xu, C., Zhao, P., Sun, Q., Geng, X., Hu, W., Tao, C., Ma, J., Lin, Q., Jiang, D.: WizardCoder: Empowering code large language models with Evol-Instruct. In: International Conference on Learning Representations (ICLR 2024). arXiv preprint arXiv:2306.08568 (2024). https://doi.org/10.48550/arXiv.2306.08568
- Qian, C., Fan, S., Sun, X., Jiang, Z., Xu, R., Zhang, C., Zhang, Y.: ChatDev: Communicative agents for software development. arXiv preprint arXiv:2307.07924 (2023). https://doi.org/10.48550/arXiv.2307.07924
- Yang, W. Q., Wang, H. B., Liu, Z. H., Li, X. Z., Yan, Y. K., Wang, S., Gu, Y., Yu, M. H., Liu, Z. Y., Yu, G. (2025). COAST: Enhancing the code debugging ability of LLMs through communicative agent based data synthesis. In L. Chiruzzo, A. Ritter, & L. Wang (Eds.), Findings of the Association for Computational Linguistics: NAACL 2025 (pp. 2570–2585). Association for Computational Linguistics. https://doi.org/10.18653/v1/2025.findings-naacl.139
- Lin, K., Zou, T., Yuan, H. (2025). Debate, verify, and debug: A multi-agent planning framework for reliable code generation. In 2025 IEEE 8th International Conference on Computer and Communication Engineering Technology (CCET) (pp. 1–7), Beijing, China. IEEE. https://doi.org/10.1109/CCET66260.2025.11199679
- Puvvadi, M., Arava, S. K., Santoria, A., Chennupati, S. S. P., Puvvadi, H. V. (2025). Coding agents: A comprehensive survey of automated bug fixing systems and benchmarks. In 2025 IEEE 14th International Conference on Communication Systems and Network Technologies (CSNT) (pp. 680–686), Bhopal, India. IEEE. https://doi.org/10.1109/CSNT64827.2025.10968728
- Ashrafi, N., Bouktif, S., Mediani, M. (2025). Enhancing LLM code generation: A systematic evaluation of multi-agent collaboration and runtime debugging for improved accuracy, reliability, and latency. arXiv preprint arXiv:2505.02133 (cs.SE). https://arxiv.org/abs/2505.02133
- Lee, C., Xia, C. S., Yang, L. J., Huang, J. T., Zhu, Z. R., Zhang, L. M., Lyu, M. R. (2025). UniDebugger: Hierarchical multi-agent framework for unified software debugging. In C. Christodoulopoulos, T. Chakraborty, C. Rose, & V. Peng (Eds.), Proceedings of the 2025 Conference on Empirical Methods in Natural Language Processing (pp. 18248–18277). Association for Computational Linguistics. https://doi.org/10.18653/v1/2025.emnlp-main.921
- Zhang, Z. Y., Dai, Q. Y., Bo, X. H., Ma, C., Li, R., Chen, X., Zhu, J. M., Dong, Z. H., Wen, J. R. (2025). A survey on the memory mechanism of large language model-based agents. ACM Transactions on Information Systems, 43(6), 155, 1–47. https://doi.org/10.1145/3748302
- Xu, W. J., Liang, Z. J., Mei, K., Gao, H., Tan, J. T., Zhang, Y. F. (2025). A-MEM: Agentic memory for LLM agents. arXiv preprint arXiv:2502.12110 (cs.CL). https://arxiv.org/abs/2502.12110
- Wang, Y., Chen, X. (2025). MIRIX: Multi-agent memory system for LLM-based agents. arXiv preprint arXiv:2507.07957 (cs.CL). https://arxiv.org/abs/2507.07957
- Zhang, G. K., Wang, B., Ma, Y. L., Zhao, D. M., Yu, Z. F. (2025). Multiple memory systems for enhancing the long-term memory of agent. arXiv preprint arXiv:2508.15294 (cs.AI). https://arxiv.org/abs/2508.15294
- Nan, J. Y., Ma, W. Q., Wu, W. L., Chen, Y. Z. (2025). Nemori: Self-organizing agent memory inspired by cognitive science. arXiv preprint arXiv:2508.03341 (cs.AI). https://arxiv.org/abs/2508.03341