"""Agent 类型定义

提供统一的类型定义，增强代码可读性和类型安全性。
"""

from typing import Union, List, Dict, Any, TypeAlias
from dataclasses import dataclass
from ms_agent.llm.utils import Message


# -----------------------------------------------------------------
# 基础类型别名
# -----------------------------------------------------------------

# Agent 输入类型：字符串或 Message 列表
AgentInput: TypeAlias = Union[str, List[Message]]

# Agent 输出类型：Message 列表（统一格式）
AgentOutput: TypeAlias = List[Message]

# 产物字典类型：名称 -> 内容
ArtifactDict: TypeAlias = Dict[str, str]

# 产物名称列表
ArtifactNames: TypeAlias = List[str]


# -----------------------------------------------------------------
# 数据类
# -----------------------------------------------------------------

@dataclass
class AgentResult:
    """Agent 执行结果
    
    Attributes:
        success: 是否成功
        messages: 输出消息列表
        artifacts: 生成的产物（可选）
        error: 错误信息（如果失败）
    """
    success: bool
    messages: AgentOutput
    artifacts: Dict[str, Any] = None
    error: str = None
    
    @property
    def content(self) -> str:
        """获取最后一条 assistant 消息的内容"""
        for msg in reversed(self.messages):
            if msg.role == "assistant" and msg.content:
                return msg.content
        return ""
    
    @classmethod
    def from_messages(cls, messages: AgentOutput) -> "AgentResult":
        """从消息列表创建成功结果"""
        return cls(success=True, messages=messages)
    
    @classmethod
    def from_error(cls, error: str) -> "AgentResult":
        """创建错误结果"""
        return cls(success=False, messages=[], error=error)


@dataclass
class DocumentResult:
    """文档生成结果
    
    用于 SpecGenAgent 等生成多个文档的 Agent。
    
    Attributes:
        name: 文档名称
        content: 文档内容
        success: 是否成功生成
        error: 错误信息（如果失败）
    """
    name: str
    content: str
    success: bool = True
    error: str = None


# -----------------------------------------------------------------
# 协议定义（用于类型检查）
# -----------------------------------------------------------------

from typing import Protocol, runtime_checkable


@runtime_checkable
class PromptBuilder(Protocol):
    """提示词构建函数协议"""
    
    def __call__(self, user_input: str, **kwargs: Any) -> str:
        """构建提示词
        
        Args:
            user_input: 用户输入
            **kwargs: 额外参数（如前序产物）
            
        Returns:
            构建后的提示词
        """
        ...


@runtime_checkable
class ArtifactProvider(Protocol):
    """产物提供者协议"""
    
    def _get_previous_artifact(self, name: str, default: str = "") -> str:
        """获取前序产物"""
        ...
    
    def _get_artifacts(self) -> ArtifactDict:
        """获取所有声明的产物"""
        ...

