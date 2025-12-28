"""统一配置中心 - 集中管理所有配置项

设计原则：
1. 单一数据源：所有配置从这里获取
2. 三层优先级：环境变量 > 配置文件 > 默认值
3. 类型安全：使用 dataclass 定义配置结构
4. 懒加载：配置在首次访问时加载

使用方式：
    from src.config.settings import settings
    
    # 访问 LLM 配置
    model = settings.llm.model
    
    # 访问 RAG 配置
    chunk_size = settings.rag.chunk_size
    
    # 访问路径配置
    output_dir = settings.paths.output_dir
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any
from functools import cached_property

from ms_agent.utils import get_logger

logger = get_logger()


# ============================================================
# 配置数据类
# ============================================================

@dataclass
class LLMConfig:
    """LLM 配置"""
    service: str = "modelscope"
    model: str = "Qwen/Qwen3-VL-235B-A22B-Instruct"
    api_key: str = ""
    base_url: str = ""
    
    # 生成参数
    temperature: float = 0.4
    max_tokens: int = 32768
    stream: bool = False
    
    # 备用模型（用于轻量任务）
    light_model: str = "Qwen/Qwen3-8B"
    
    @classmethod
    def from_env(cls) -> "LLMConfig":
        """从环境变量加载"""
        return cls(
            service=os.getenv("LLM_SERVICE", "modelscope"),
            model=os.getenv("LLM_MODEL", os.getenv("MODELSCOPE_MODEL", "Qwen/Qwen3-VL-235B-A22B-Instruct")),
            api_key=os.getenv("MODELSCOPE_API_KEY", ""),
            base_url=os.getenv("MODELSCOPE_BASE_URL", ""),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.4")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "32768")),
            stream=os.getenv("LLM_STREAM", "false").lower() == "true",
            light_model=os.getenv("LLM_LIGHT_MODEL", os.getenv("SUMMARY_MODEL", "Qwen/Qwen3-8B")),
        )


@dataclass
class RAGConfig:
    """RAG 配置"""
    enabled: bool = True
    name: str = "LlamaIndexRAG"
    embedding: str = "iic/nlp_gte_sentence-embedding_chinese-base"
    chunk_size: int = 512
    chunk_overlap: int = 50
    retrieve_only: bool = True
    
    # Reranker 配置
    use_rerank: bool = True
    use_expansion: bool = False
    reranker_model: str = ""
    
    # 知识库路径
    knowledge_paths: List[str] = field(default_factory=lambda: [
        "tech_patterns",
        "best_practices",
        "domain_knowledge",
    ])
    
    @classmethod
    def from_env(cls) -> "RAGConfig":
        """从环境变量加载"""
        return cls(
            enabled=os.getenv("RAG_ENABLED", "true").lower() == "true",
            name=os.getenv("RAG_NAME", "LlamaIndexRAG"),
            embedding=os.getenv("RAG_EMBEDDING", "iic/nlp_gte_sentence-embedding_chinese-base"),
            chunk_size=int(os.getenv("RAG_CHUNK_SIZE", "512")),
            chunk_overlap=int(os.getenv("RAG_CHUNK_OVERLAP", "50")),
            retrieve_only=os.getenv("RAG_RETRIEVE_ONLY", "true").lower() == "true",
            use_rerank=os.getenv("RAG_RERANK_ENABLED", "true").lower() == "true",
            use_expansion=os.getenv("RAG_EXPANSION_ENABLED", "false").lower() == "true",
            reranker_model=os.getenv("RERANKER_MODEL", ""),
        )


@dataclass
class CacheConfig:
    """缓存配置"""
    llm_cache_enabled: bool = True
    llm_cache_ttl: int = 3600  # 秒
    
    @classmethod
    def from_env(cls) -> "CacheConfig":
        """从环境变量加载"""
        return cls(
            llm_cache_enabled=os.getenv("LLM_CACHE_ENABLED", "true").lower() == "true",
            llm_cache_ttl=int(os.getenv("LLM_CACHE_TTL_SECONDS", "3600")),
        )


@dataclass
class WorkflowConfig:
    """工作流配置"""
    parallel_analysis: bool = True
    incremental_execution: bool = True
    force_agents: List[str] = field(default_factory=list)
    
    # Agent 相关
    max_chat_round: int = 15
    tool_call_timeout: int = 30000
    
    # 工作流模式配置
    # full: 完整模式，执行所有 11 个 Agent
    # fast: 快速模式，只执行核心 Agent（推荐，预计提速 20-50%）
    # minimal: 最小模式，只执行最核心的 Agent
    mode: str = "full"
    
    # 各模式对应的 Agent 列表
    mode_agents: Dict[str, List[str]] = field(default_factory=lambda: {
        "full": [
            "requirements", "tech_research", "architecture", "risk",
            "spec_gen", "evolution", "planning", "coding",
            "testing", "reflecting", "summary"
        ],
        "fast": [
            "requirements", "architecture", "spec_gen",
            "planning", "coding"
        ],
        "minimal": [
            "requirements", "spec_gen", "planning", "coding"
        ],
    })
    
    @classmethod
    def from_env(cls) -> "WorkflowConfig":
        """从环境变量加载"""
        force_agents_str = os.getenv("FORCE_AGENTS", "")
        force_agents = [a.strip() for a in force_agents_str.split(",") if a.strip()]
        
        # 获取工作流模式
        mode = os.getenv("WORKFLOW_MODE", "full").lower()
        if mode not in ("full", "fast", "minimal"):
            logger.warning(f"[WorkflowConfig] 无效的工作流模式: {mode}，使用默认模式 'full'")
            mode = "full"
        
        return cls(
            parallel_analysis=os.getenv("PARALLEL_ANALYSIS", "true").lower() == "true",
            incremental_execution=os.getenv("INCREMENTAL_EXECUTION", "true").lower() == "true",
            force_agents=force_agents,
            max_chat_round=int(os.getenv("MAX_CHAT_ROUND", "15")),
            tool_call_timeout=int(os.getenv("TOOL_CALL_TIMEOUT", "30000")),
            mode=mode,
        )
    
    def get_active_agents(self) -> List[str]:
        """获取当前模式下需要执行的 Agent 列表"""
        return self.mode_agents.get(self.mode, self.mode_agents["full"])
    
    def should_run_agent(self, agent_name: str) -> bool:
        """检查指定 Agent 是否应该在当前模式下执行"""
        return agent_name in self.get_active_agents()


@dataclass
class PathConfig:
    """路径配置"""
    project_root: Path = field(default_factory=lambda: Path.cwd())
    output_dir: Path = field(default_factory=lambda: Path("output"))
    config_dir: Path = field(default_factory=lambda: Path("src/config"))
    
    @classmethod
    def from_env(cls) -> "PathConfig":
        """从环境变量加载"""
        project_root = Path(os.getenv("PROJECT_ROOT", Path.cwd()))
        output_dir = Path(os.getenv("OUTPUT_DIR", project_root / "output"))
        config_dir = Path(os.getenv("CONFIG_DIR", project_root / "src/config"))
        
        return cls(
            project_root=project_root.resolve(),
            output_dir=output_dir.resolve(),
            config_dir=config_dir.resolve(),
        )
    
    @property
    def agents_dir(self) -> Path:
        """Agent 配置目录"""
        return self.config_dir / "agents"
    
    @property
    def knowledge_base_dir(self) -> Path:
        """知识库目录"""
        return self.output_dir / "knowledge_base"
    
    @property
    def rag_index_dir(self) -> Path:
        """RAG 索引目录"""
        return self.output_dir / "rag_index"
    
    @property
    def cache_dir(self) -> Path:
        """缓存目录"""
        return self.output_dir / "cache"


@dataclass
class SearchConfig:
    """搜索工具配置"""
    provider: str = "exa"
    exa_api_key: str = ""
    max_results: int = 5
    
    @classmethod
    def from_env(cls) -> "SearchConfig":
        """从环境变量加载"""
        return cls(
            provider=os.getenv("SEARCH_PROVIDER", "exa"),
            exa_api_key=os.getenv("EXA_API_KEY", ""),
            max_results=int(os.getenv("SEARCH_MAX_RESULTS", "5")),
        )


# ============================================================
# 统一配置类
# ============================================================

class Settings:
    """统一配置中心（单例）
    
    使用方式：
        from src.config.settings import settings
        
        # 访问配置
        model = settings.llm.model
        chunk_size = settings.rag.chunk_size
        
        # 刷新配置（重新从环境变量加载）
        settings.reload()
    """
    
    _instance: Optional["Settings"] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._load_config()
    
    def _load_config(self):
        """加载所有配置"""
        self._llm = LLMConfig.from_env()
        self._rag = RAGConfig.from_env()
        self._cache = CacheConfig.from_env()
        self._workflow = WorkflowConfig.from_env()
        self._paths = PathConfig.from_env()
        self._search = SearchConfig.from_env()
        
        logger.debug("[Settings] 配置加载完成")
    
    def reload(self):
        """重新加载配置"""
        self._load_config()
        logger.info("[Settings] 配置已重新加载")
    
    @property
    def llm(self) -> LLMConfig:
        """LLM 配置"""
        return self._llm
    
    @property
    def rag(self) -> RAGConfig:
        """RAG 配置"""
        return self._rag
    
    @property
    def cache(self) -> CacheConfig:
        """缓存配置"""
        return self._cache
    
    @property
    def workflow(self) -> WorkflowConfig:
        """工作流配置"""
        return self._workflow
    
    @property
    def paths(self) -> PathConfig:
        """路径配置"""
        return self._paths
    
    @property
    def search(self) -> SearchConfig:
        """搜索配置"""
        return self._search
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于调试）"""
        return {
            "llm": {
                "service": self.llm.service,
                "model": self.llm.model,
                "temperature": self.llm.temperature,
                "max_tokens": self.llm.max_tokens,
                "light_model": self.llm.light_model,
            },
            "rag": {
                "enabled": self.rag.enabled,
                "name": self.rag.name,
                "embedding": self.rag.embedding,
                "chunk_size": self.rag.chunk_size,
                "use_rerank": self.rag.use_rerank,
            },
            "cache": {
                "llm_cache_enabled": self.cache.llm_cache_enabled,
                "llm_cache_ttl": self.cache.llm_cache_ttl,
            },
            "workflow": {
                "parallel_analysis": self.workflow.parallel_analysis,
                "incremental_execution": self.workflow.incremental_execution,
            },
            "paths": {
                "project_root": str(self.paths.project_root),
                "output_dir": str(self.paths.output_dir),
            },
        }
    
    def print_config(self):
        """打印当前配置（用于调试）"""
        import json
        print(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))


# 全局单例
settings = Settings()


# ============================================================
# 便捷函数
# ============================================================

def get_llm_config() -> LLMConfig:
    """获取 LLM 配置"""
    return settings.llm


def get_rag_config() -> RAGConfig:
    """获取 RAG 配置"""
    return settings.rag


def get_path_config() -> PathConfig:
    """获取路径配置"""
    return settings.paths


def is_cache_enabled() -> bool:
    """检查缓存是否启用"""
    return settings.cache.llm_cache_enabled


def is_parallel_enabled() -> bool:
    """检查并行执行是否启用"""
    return settings.workflow.parallel_analysis

