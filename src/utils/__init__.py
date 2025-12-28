"""工具函数模块"""

# 使用 ms-agent 自带的 logger
from ms_agent.utils import get_logger

from .agent_utils import (
    extract_message_content,
    extract_mapping_from_output,
    load_mapping_from_file,
    save_mapping_to_file,
)
from .artifact_store import ArtifactStore
from .context_manager import ContextManager, truncate_artifact, fit_artifacts_for_prompt
from .llm_cache import LLMCache, llm_cache, get_llm_cache, cache_llm_call, get_cached_llm_result
from .path_manager import PathManager
from .workflow_manager import workflow_manager, WorkflowContext
from .change_detector import ChangeDetector, get_change_detector, AGENT_DEPENDENCIES
from .artifact_versioning import ArtifactVersionManager, ArtifactVersion, get_version_manager
from .exceptions import (
    DeepCodeError,
    RecoverableError,
    FatalError,
    ConfigurationError,
    ServiceUnavailableError,
    ArtifactNotFoundError,
    DocumentProcessingError,
    RAGError,
    AgentExecutionError,
)

logger = get_logger()

__all__ = [
    "logger",
    "ArtifactStore",
    "ContextManager",
    "truncate_artifact",
    "fit_artifacts_for_prompt",
    # LLM 缓存
    "LLMCache",
    "llm_cache",
    "get_llm_cache",
    "cache_llm_call",
    "get_cached_llm_result",
    # 路径管理
    "PathManager",
    "workflow_manager",
    "WorkflowContext",
    # 变更检测和版本管理（Phase 2）
    "ChangeDetector",
    "get_change_detector",
    "AGENT_DEPENDENCIES",
    "ArtifactVersionManager",
    "ArtifactVersion",
    "get_version_manager",
    # Agent 工具
    "extract_message_content",
    "extract_mapping_from_output",
    "load_mapping_from_file",
    "save_mapping_to_file",
    # 异常类
    "DeepCodeError",
    "RecoverableError",
    "FatalError",
    "ConfigurationError",
    "ServiceUnavailableError",
    "ArtifactNotFoundError",
    "DocumentProcessingError",
    "RAGError",
    "AgentExecutionError",
]
