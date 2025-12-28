"""配置模块

包含工作流配置、Agent 配置和统一配置中心。

使用方式：
    from src.config import settings
    
    # 访问 LLM 配置
    model = settings.llm.model
    
    # 访问 RAG 配置
    chunk_size = settings.rag.chunk_size
"""

from .settings import (
    settings,
    Settings,
    LLMConfig,
    RAGConfig,
    CacheConfig,
    WorkflowConfig,
    PathConfig,
    SearchConfig,
    get_llm_config,
    get_rag_config,
    get_path_config,
    is_cache_enabled,
    is_parallel_enabled,
)

__all__ = [
    # 配置单例
    "settings",
    # 配置类
    "Settings",
    "LLMConfig",
    "RAGConfig",
    "CacheConfig",
    "WorkflowConfig",
    "PathConfig",
    "SearchConfig",
    # 便捷函数
    "get_llm_config",
    "get_rag_config",
    "get_path_config",
    "is_cache_enabled",
    "is_parallel_enabled",
]
