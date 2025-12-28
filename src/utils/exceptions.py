"""自定义异常类

定义项目中使用的异常类型，区分可恢复错误和致命错误。

使用原则：
1. RecoverableError: 可以继续执行的错误（如单个文件处理失败）
2. FatalError: 必须终止流程的错误（如配置错误、服务不可用）
3. 在关键位置捕获异常并适当处理
"""

from typing import Optional


class DeepCodeError(Exception):
    """DeepCode 基础异常类"""
    
    def __init__(self, message: str, details: Optional[str] = None):
        self.message = message
        self.details = details
        super().__init__(self.message)
    
    def __str__(self):
        if self.details:
            return f"{self.message}\n详情: {self.details}"
        return self.message


class RecoverableError(DeepCodeError):
    """可恢复错误
    
    这类错误不会导致整个工作流失败，可以继续执行。
    例如：
    - 单个文件处理失败
    - 单个 Agent 执行失败但有回退方案
    - RAG 检索失败但可以使用默认行为
    """
    pass


class FatalError(DeepCodeError):
    """致命错误
    
    这类错误会导致工作流终止，需要用户介入。
    例如：
    - 配置错误（缺少必要配置）
    - LLM 服务不可用
    - 必要的依赖缺失
    """
    pass


class ConfigurationError(FatalError):
    """配置错误"""
    pass


class ServiceUnavailableError(FatalError):
    """服务不可用错误"""
    pass


class ArtifactNotFoundError(RecoverableError):
    """产物未找到错误"""
    pass


class DocumentProcessingError(RecoverableError):
    """文档处理错误"""
    pass


class RAGError(RecoverableError):
    """RAG 相关错误"""
    pass


class AgentExecutionError(DeepCodeError):
    """Agent 执行错误
    
    根据具体情况可以是可恢复或致命的。
    """
    
    def __init__(self, message: str, agent_name: str, recoverable: bool = True, details: Optional[str] = None):
        self.agent_name = agent_name
        self.recoverable = recoverable
        super().__init__(message, details)
    
    def __str__(self):
        base = f"[{self.agent_name}] {self.message}"
        if self.details:
            base += f"\n详情: {self.details}"
        return base

