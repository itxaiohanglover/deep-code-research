"""变更检测器 - 检测输入变更，支持增量执行

解决问题：
1. 相同输入重复执行浪费资源
2. 无法判断哪些 Agent 需要重新执行
3. 缺少版本追踪能力

设计原则：
1. 基于内容 hash 检测变更
2. 支持细粒度依赖追踪
3. 持久化变更历史
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Any, Tuple

from ms_agent.utils import get_logger

logger = get_logger()


class ChangeDetector:
    """变更检测器
    
    功能：
    1. 检测输入内容是否变更
    2. 追踪 Agent 执行依赖
    3. 判断哪些 Agent 需要重新执行
    
    使用示例：
        detector = ChangeDetector(session_dir)
        
        # 检测输入变更
        if detector.has_changed("user_input", new_input):
            # 执行 Agent
            result = await agent.run(new_input)
            detector.mark_executed("agent_name", input_hash, output_hash)
    """
    
    def __init__(self, session_dir: Path, config_file: str = "change_history.json"):
        """初始化
        
        Args:
            session_dir: 会话目录
            config_file: 变更历史文件名
        """
        self.session_dir = Path(session_dir)
        self.history_file = self.session_dir / config_file
        self._history: Dict[str, Any] = {}
        self._load_history()
    
    def _load_history(self) -> None:
        """加载变更历史"""
        if self.history_file.exists():
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    self._history = json.load(f)
                logger.debug(f"[ChangeDetector] 加载变更历史: {len(self._history.get('executions', {}))} 条记录")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"[ChangeDetector] 加载历史失败: {e}")
                self._history = {}
        
        # 确保必要的结构
        if "executions" not in self._history:
            self._history["executions"] = {}
        if "dependencies" not in self._history:
            self._history["dependencies"] = {}
        if "inputs" not in self._history:
            self._history["inputs"] = {}
    
    def _save_history(self) -> None:
        """保存变更历史"""
        try:
            self.session_dir.mkdir(parents=True, exist_ok=True)
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self._history, f, ensure_ascii=False, indent=2)
        except IOError as e:
            logger.error(f"[ChangeDetector] 保存历史失败: {e}")
    
    @staticmethod
    def compute_hash(content: str) -> str:
        """计算内容 hash
        
        Args:
            content: 内容字符串
            
        Returns:
            SHA256 hash 前 16 位
        """
        if not content:
            return "empty"
        return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]
    
    def has_changed(self, key: str, content: str) -> bool:
        """检测内容是否变更
        
        Args:
            key: 内容标识（如 "user_input", "requirements"）
            content: 内容字符串
            
        Returns:
            True 如果内容变更或首次出现
        """
        new_hash = self.compute_hash(content)
        old_hash = self._history["inputs"].get(key)
        
        if old_hash is None:
            logger.debug(f"[ChangeDetector] 首次检测 {key}")
            return True
        
        changed = new_hash != old_hash
        if changed:
            logger.info(f"[ChangeDetector] 检测到变更: {key} ({old_hash} -> {new_hash})")
        else:
            logger.debug(f"[ChangeDetector] 未变更: {key}")
        
        return changed
    
    def update_input_hash(self, key: str, content: str) -> str:
        """更新输入 hash
        
        Args:
            key: 内容标识
            content: 内容字符串
            
        Returns:
            新的 hash 值
        """
        new_hash = self.compute_hash(content)
        self._history["inputs"][key] = new_hash
        self._save_history()
        return new_hash
    
    def mark_executed(
        self,
        agent_name: str,
        input_hash: str,
        output_hash: str,
        dependencies: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
    ) -> None:
        """标记 Agent 执行完成
        
        Args:
            agent_name: Agent 名称
            input_hash: 输入 hash
            output_hash: 输出 hash
            dependencies: 依赖的 Agent 列表
            metadata: 额外元数据
        """
        execution_record = {
            "input_hash": input_hash,
            "output_hash": output_hash,
            "timestamp": datetime.now().isoformat(),
            "dependencies": dependencies or [],
            "metadata": metadata or {},
        }
        
        self._history["executions"][agent_name] = execution_record
        
        # 更新依赖关系
        if dependencies:
            self._history["dependencies"][agent_name] = dependencies
        
        self._save_history()
        logger.debug(f"[ChangeDetector] 标记执行: {agent_name} (in={input_hash}, out={output_hash})")
    
    def get_last_execution(self, agent_name: str) -> Optional[Dict]:
        """获取 Agent 上次执行记录
        
        Args:
            agent_name: Agent 名称
            
        Returns:
            执行记录或 None
        """
        return self._history["executions"].get(agent_name)
    
    def should_execute(
        self,
        agent_name: str,
        input_content: str,
        force: bool = False,
    ) -> Tuple[bool, str]:
        """判断 Agent 是否需要执行
        
        Args:
            agent_name: Agent 名称
            input_content: 输入内容
            force: 强制执行
            
        Returns:
            (是否需要执行, 原因)
        """
        if force:
            return True, "强制执行"
        
        # 检查是否有执行记录
        last_exec = self.get_last_execution(agent_name)
        if not last_exec:
            return True, "首次执行"
        
        # 检查输入是否变更
        new_input_hash = self.compute_hash(input_content)
        if new_input_hash != last_exec.get("input_hash"):
            return True, f"输入变更 ({last_exec.get('input_hash')} -> {new_input_hash})"
        
        # 检查依赖是否变更
        dependencies = self._history["dependencies"].get(agent_name, [])
        for dep in dependencies:
            dep_exec = self.get_last_execution(dep)
            if dep_exec:
                dep_time = datetime.fromisoformat(dep_exec["timestamp"])
                my_time = datetime.fromisoformat(last_exec["timestamp"])
                if dep_time > my_time:
                    return True, f"依赖 {dep} 已更新"
        
        return False, "无需执行"
    
    def get_affected_agents(self, changed_agent: str) -> Set[str]:
        """获取受影响的下游 Agent
        
        当一个 Agent 的输出变更时，找出所有依赖它的 Agent。
        
        Args:
            changed_agent: 变更的 Agent 名称
            
        Returns:
            受影响的 Agent 集合
        """
        affected = set()
        
        for agent, deps in self._history["dependencies"].items():
            if changed_agent in deps:
                affected.add(agent)
                # 递归查找
                affected.update(self.get_affected_agents(agent))
        
        return affected
    
    def get_execution_order(self, agents: List[str]) -> List[str]:
        """根据依赖关系计算执行顺序（拓扑排序）
        
        Args:
            agents: 待执行的 Agent 列表
            
        Returns:
            排序后的执行顺序
        """
        # 构建依赖图
        deps_map = {}
        for agent in agents:
            deps_map[agent] = set(self._history["dependencies"].get(agent, [])) & set(agents)
        
        # 拓扑排序
        result = []
        remaining = set(agents)
        
        while remaining:
            # 找到没有依赖的节点
            ready = [a for a in remaining if not deps_map[a] - set(result)]
            if not ready:
                # 有循环依赖，取第一个
                ready = [next(iter(remaining))]
                logger.warning(f"[ChangeDetector] 检测到循环依赖，强制执行: {ready[0]}")
            
            result.extend(ready)
            remaining -= set(ready)
        
        return result
    
    def clear_history(self) -> None:
        """清除所有历史"""
        self._history = {
            "executions": {},
            "dependencies": {},
            "inputs": {},
        }
        self._save_history()
        logger.info("[ChangeDetector] 历史已清除")
    
    def get_summary(self) -> Dict[str, Any]:
        """获取变更检测摘要"""
        return {
            "total_agents": len(self._history["executions"]),
            "total_inputs": len(self._history["inputs"]),
            "agents": list(self._history["executions"].keys()),
            "last_update": max(
                (e.get("timestamp", "") for e in self._history["executions"].values()),
                default=""
            ),
        }


# 标准 Agent 依赖关系定义
AGENT_DEPENDENCIES = {
    "requirements": [],  # 无依赖
    "tech_research": ["requirements"],
    "architecture": ["requirements"],
    "risk": ["requirements"],
    "planning": ["requirements", "tech_research", "architecture", "risk"],
    "spec_gen": ["requirements", "tech_research", "architecture", "risk", "planning"],
    "coding": ["spec_gen"],
    "testing": ["coding"],
    "evolution": ["coding", "testing"],
    "review": ["evolution"],
}


def get_change_detector(session_dir: Path) -> ChangeDetector:
    """获取 ChangeDetector 实例
    
    Args:
        session_dir: 会话目录
        
    Returns:
        ChangeDetector 实例
    """
    return ChangeDetector(session_dir)

