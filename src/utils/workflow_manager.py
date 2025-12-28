"""工作流管理器

职责：
1. 管理 workflow 上下文（迭代、步骤等）
2. 提供工作流索引解析功能（从 workflow.yaml 动态获取 Agent 索引）
3. 提供 WorkflowContext 统一管理状态传递

设计原则：
- 产物数据通过文件系统（ArtifactCallback）传递
- 工作流状态通过 WorkflowContext 集中管理
- 工作流索引通过配置动态解析，避免硬编码
"""

from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from datetime import datetime
import os
import json


@dataclass
class WorkflowContext:
    """工作流上下文
    
    集中管理工作流执行期间的状态信息，避免状态分散在多个文件中。
    
    Attributes:
        session_id: 会话 ID
        iteration: 当前迭代号
        current_agent: 当前执行的 Agent 名称
        agent_results: 各 Agent 的执行状态
        flow_decisions: 流程跳转决策记录
        rollback_context: 回退时的错误上下文（供目标 Agent 读取）
        metadata: 其他元数据
    """
    session_id: str = ""
    iteration: int = 1
    current_agent: str = ""
    agent_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    flow_decisions: List[Dict[str, Any]] = field(default_factory=list)
    rollback_context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def record_agent_result(
        self,
        agent_name: str,
        success: bool,
        duration_ms: int = 0,
        error: str = None
    ):
        """记录 Agent 执行结果
        
        Args:
            agent_name: Agent 名称
            success: 是否成功
            duration_ms: 执行耗时（毫秒）
            error: 错误信息
        """
        self.agent_results[agent_name] = {
            "success": success,
            "duration_ms": duration_ms,
            "error": error,
            "timestamp": datetime.now().isoformat()
        }
    
    def record_flow_decision(
        self,
        from_agent: str,
        to_agent: str,
        reason: str,
        decision_type: str = "normal"
    ):
        """记录流程跳转决策
        
        Args:
            from_agent: 来源 Agent
            to_agent: 目标 Agent
            reason: 跳转原因
            decision_type: 决策类型（normal/rollback/skip）
        """
        self.flow_decisions.append({
            "from": from_agent,
            "to": to_agent,
            "reason": reason,
            "type": decision_type,
            "iteration": self.iteration,
            "timestamp": datetime.now().isoformat()
        })
    
    def get_agent_status(self, agent_name: str) -> Optional[Dict[str, Any]]:
        """获取指定 Agent 的执行状态"""
        return self.agent_results.get(agent_name)
    
    def is_agent_completed(self, agent_name: str) -> bool:
        """检查 Agent 是否已完成"""
        result = self.agent_results.get(agent_name)
        return result is not None and result.get("success", False)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于序列化）"""
        return {
            "session_id": self.session_id,
            "iteration": self.iteration,
            "current_agent": self.current_agent,
            "agent_results": self.agent_results,
            "flow_decisions": self.flow_decisions,
            "rollback_context": self.rollback_context,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowContext":
        """从字典创建实例"""
        return cls(
            session_id=data.get("session_id", ""),
            iteration=data.get("iteration", 1),
            current_agent=data.get("current_agent", ""),
            agent_results=data.get("agent_results", {}),
            flow_decisions=data.get("flow_decisions", []),
            rollback_context=data.get("rollback_context", {}),
            metadata=data.get("metadata", {})
        )
    
    def save(self, path: Path):
        """保存到文件"""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    
    @classmethod
    def load(cls, path: Path) -> Optional["WorkflowContext"]:
        """从文件加载"""
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except Exception:
            return None


class WorkflowManager:
    """工作流管理器
    
    功能：
    1. 上下文管理（迭代、步骤）
    2. 工作流索引解析（从 workflow.yaml 获取 Agent 索引）
    """
    
    _instance: Optional['WorkflowManager'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._reset()
        return cls._instance
    
    def _reset(self):
        """重置管理器"""
        self.current_iteration: int = 1
        self.current_step: str = ""
        self.current_step_index: int = 0
        self.current_message_id: Optional[str] = None
        # 工作流配置缓存
        self._workflow_config: Optional[Dict] = None
        self._agent_order: Optional[List[str]] = None
        # 工作流上下文
        self._context: Optional[WorkflowContext] = None
        self._context_path: Optional[Path] = None
    
    # ----------------------------------------------------------------
    # 上下文管理
    # ----------------------------------------------------------------
    
    def set_iteration(self, iteration: int):
        """设置当前迭代次数"""
        self.current_iteration = iteration
    
    def set_step(self, step: str, step_index: int = 0):
        """设置当前步骤"""
        self.current_step = step
        self.current_step_index = step_index
    
    def get_iteration(self) -> int:
        """获取当前迭代次数"""
        return self.current_iteration
    
    def get_step(self) -> str:
        """获取当前步骤"""
        return self.current_step
    
    def get_step_index(self) -> int:
        """获取当前步骤索引"""
        return self.current_step_index
    
    def set_message_id(self, message_id: str):
        """设置当前消息 ID"""
        self.current_message_id = message_id
    
    def get_message_id(self) -> Optional[str]:
        """获取当前消息 ID"""
        return self.current_message_id
    
    def clear(self):
        """清空所有数据"""
        self._reset()
    
    # ----------------------------------------------------------------
    # WorkflowContext 管理
    # ----------------------------------------------------------------
    
    def init_context(self, session_id: str, output_dir: Path = None) -> WorkflowContext:
        """初始化工作流上下文
        
        Args:
            session_id: 会话 ID
            output_dir: 输出目录（用于保存上下文文件）
            
        Returns:
            WorkflowContext 实例
        """
        self._context = WorkflowContext(
            session_id=session_id,
            iteration=self.current_iteration
        )
        
        if output_dir:
            self._context_path = output_dir / session_id / "workflow_context.json"
            # 尝试加载已有上下文
            existing = WorkflowContext.load(self._context_path)
            if existing:
                self._context = existing
        
        return self._context
    
    @property
    def context(self) -> Optional[WorkflowContext]:
        """获取当前工作流上下文"""
        return self._context
    
    def save_context(self):
        """保存工作流上下文到文件"""
        if self._context and self._context_path:
            self._context.save(self._context_path)
    
    def record_agent_start(self, agent_name: str):
        """记录 Agent 开始执行"""
        if self._context:
            self._context.current_agent = agent_name
            self.save_context()
    
    def record_agent_end(self, agent_name: str, success: bool, duration_ms: int = 0, error: str = None):
        """记录 Agent 执行结束"""
        if self._context:
            self._context.record_agent_result(agent_name, success, duration_ms, error)
            self.save_context()
    
    def record_flow_decision(self, from_agent: str, to_agent: str, reason: str, decision_type: str = "normal"):
        """记录流程跳转决策"""
        if self._context:
            self._context.record_flow_decision(from_agent, to_agent, reason, decision_type)
            self.save_context()
    
    def set_rollback_context(self, context: Dict[str, Any]):
        """设置回退上下文（供目标 Agent 读取错误信息）
        
        Args:
            context: 回退上下文，包含：
                - target_agent: 目标 Agent
                - reason: 回退原因
                - failed_tests: 失败的测试列表
                - error_analysis: 错误分析
                - suggestions: 修复建议
        """
        if self._context:
            self._context.rollback_context = context
            self.save_context()
    
    def get_rollback_context(self) -> Dict[str, Any]:
        """获取回退上下文
        
        Returns:
            回退上下文字典，如果没有则返回空字典
        """
        if self._context:
            return self._context.rollback_context
        return {}
    
    def clear_rollback_context(self):
        """清除回退上下文（任务成功完成后调用）"""
        if self._context:
            self._context.rollback_context = {}
            self.save_context()
    
    # ----------------------------------------------------------------
    # 工作流索引解析
    # ----------------------------------------------------------------
    
    def _load_workflow_config(self) -> Dict:
        """加载 workflow.yaml 配置（懒加载，缓存结果）"""
        if self._workflow_config is not None:
            return self._workflow_config
        
        # 查找 workflow.yaml
        config_paths = [
            Path(__file__).parent.parent / "config" / "workflow.yaml",
            Path(os.getcwd()) / "src" / "config" / "workflow.yaml",
        ]
        
        for config_path in config_paths:
            if config_path.exists():
                try:
                    import yaml
                    with open(config_path, 'r', encoding='utf-8') as f:
                        self._workflow_config = yaml.safe_load(f) or {}
                    return self._workflow_config
                except Exception:
                    pass
        
        self._workflow_config = {}
        return self._workflow_config
    
    def get_agent_order(self) -> List[str]:
        """获取 Agent 执行顺序列表
        
        从 workflow.yaml 解析 Agent 顺序（基于 next 字段构建依赖图）。
        
        Returns:
            Agent 名称列表，按执行顺序排列
        """
        if self._agent_order is not None:
            return self._agent_order
        
        config = self._load_workflow_config()
        if not config:
            return []
        
        # 构建顺序：从没有入边的节点开始，按 next 字段遍历
        # 首先找到所有被引用的 agent（作为 next 目标）
        referenced = set()
        for agent_name, agent_config in config.items():
            if isinstance(agent_config, dict):
                next_agents = agent_config.get('next', [])
                if isinstance(next_agents, list):
                    referenced.update(next_agents)
        
        # 找到起始节点（不被任何 agent 引用的节点）
        all_agents = set(config.keys())
        start_agents = all_agents - referenced
        
        # 如果没有明确的起始节点，使用配置中的第一个
        if not start_agents:
            start_agents = {list(config.keys())[0]} if config else set()
        
        # 按 next 字段构建顺序
        order = []
        visited = set()
        
        def visit(agent_name: str):
            if agent_name in visited or agent_name not in config:
                return
            visited.add(agent_name)
            order.append(agent_name)
            
            agent_config = config.get(agent_name, {})
            if isinstance(agent_config, dict):
                next_agents = agent_config.get('next', [])
                if isinstance(next_agents, list):
                    for next_agent in next_agents:
                        visit(next_agent)
        
        for start in sorted(start_agents):
            visit(start)
        
        self._agent_order = order
        return self._agent_order
    
    def get_agent_index(self, agent_name: str) -> int:
        """获取 Agent 在工作流中的索引
        
        Args:
            agent_name: Agent 名称（如 "requirements", "coding"）
            
        Returns:
            索引值，如果未找到返回 -1
        """
        order = self.get_agent_order()
        try:
            return order.index(agent_name)
        except ValueError:
            return -1
    
    def get_agent_by_index(self, index: int) -> Optional[str]:
        """根据索引获取 Agent 名称
        
        Args:
            index: 索引值
            
        Returns:
            Agent 名称，如果索引无效返回 None
        """
        order = self.get_agent_order()
        if 0 <= index < len(order):
            return order[index]
        return None


# 全局单例实例
workflow_manager = WorkflowManager()
