"""产物存储服务

统一管理 Agent 间的数据传递（通过文件系统），支持 Session / Iteration。

设计原则：
1. 支持跨迭代查找：当前迭代找不到时，自动回退到上一迭代查找
2. 这解决了工作流回退时新迭代目录没有前序产物的问题
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional, Any, List


class ArtifactStore:
    """产物存储服务（统一管理）
    
    支持跨迭代查找功能：
    - 当在当前迭代找不到产物时，会自动回退到上一迭代查找
    - 这解决了 ReflectingAgent 触发回退后新迭代目录没有前序产物的问题
    """

    def __init__(
        self,
        base_dir: str | Path = "output/artifacts",
        session_id: Optional[str] = None,
        fallback_iterations: bool = True,
    ):
        """初始化 ArtifactStore
        
        Args:
            base_dir: 基础目录（通常已经是 output/{session_id}/artifacts/）
            session_id: 会话 ID（可选，如果 base_dir 已经包含 session_id，则不需要）
            fallback_iterations: 是否启用跨迭代查找（默认启用）
        """
        self.base_dir = Path(base_dir)
        self.session_id = session_id
        self.fallback_iterations = fallback_iterations
        # 如果 base_dir 已经包含 session_id（如 output/{session_id}/artifacts/），
        # 则直接使用 base_dir 作为 session_dir，不再添加 session_id 子目录
        if session_id and not str(self.base_dir).endswith(session_id):
            self.session_dir = self.base_dir / session_id
        else:
            self.session_dir = self.base_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.current_iteration: Optional[int] = None

    def set_iteration(self, iteration: int) -> None:
        """设置当前迭代目录"""
        self.current_iteration = iteration
        iteration_dir = self._iteration_dir(iteration)
        iteration_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        name: str,
        content: str,
        iteration: Optional[int] = None,
        encoding: str = "utf-8",
    ) -> Path:
        """保存产物（文本）"""
        target_path = self._prepare_path(name, iteration)
        target_path.write_text(content, encoding=encoding)
        return target_path

    def save_json(
        self,
        name: str,
        data: Dict[str, Any],
        iteration: Optional[int] = None,
        encoding: str = "utf-8",
    ) -> Path:
        """保存 JSON 产物"""
        content = json.dumps(data, ensure_ascii=False, indent=2)
        return self.save(name, content, iteration=iteration, encoding=encoding)

    def get(
        self,
        name: str,
        iteration: Optional[int] = None,
        default: str = "",
        encoding: str = "utf-8",
    ) -> str:
        """获取产物（支持跨迭代查找）
        
        查找策略：
        1. 首先在指定迭代（或当前迭代）中查找
        2. 如果启用了 fallback_iterations 且未找到，则回退到上一迭代查找
        3. 重复直到找到或遍历完所有迭代
        
        这解决了工作流回退时新迭代目录没有前序产物的问题。
        """
        target_iteration = iteration if iteration is not None else self.current_iteration
        
        # 首先尝试在指定迭代中查找
        target_path = self._prepare_path(name, target_iteration, create=False)
        if target_path.exists():
            return target_path.read_text(encoding=encoding)
        
        # 如果启用了跨迭代查找，尝试从上一迭代回退查找
        if self.fallback_iterations and target_iteration is not None and target_iteration > 1:
            for prev_iteration in range(target_iteration - 1, 0, -1):
                prev_path = self._prepare_path(name, prev_iteration, create=False)
                if prev_path.exists():
                    # 记录跨迭代查找的情况（便于调试）
                    return prev_path.read_text(encoding=encoding)
        
        return default

    def get_json(
        self,
        name: str,
        iteration: Optional[int] = None,
        default: Optional[Dict[str, Any]] = None,
        encoding: str = "utf-8",
    ) -> Optional[Dict[str, Any]]:
        """获取 JSON 产物"""
        content = self.get(name, iteration=iteration, default="", encoding=encoding)
        if not content:
            return default
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return default

    def list_iteration_artifacts(self, iteration: int) -> Dict[str, Path]:
        """列出某次迭代的所有产物"""
        iteration_dir = self._iteration_dir(iteration)
        if not iteration_dir.exists():
            return {}
        return {
            str(path.relative_to(iteration_dir)): path
            for path in iteration_dir.rglob("*")
            if path.is_file()
        }
    
    def get_all_iterations(self) -> List[int]:
        """获取所有迭代目录的迭代号列表（按升序排列）
        
        Returns:
            迭代号列表，如 [1, 2, 3]
        """
        iterations = []
        if not self.session_dir.exists():
            return iterations
        
        for item in self.session_dir.iterdir():
            if item.is_dir() and item.name.startswith("iteration_"):
                try:
                    iteration_num = int(item.name.replace("iteration_", ""))
                    iterations.append(iteration_num)
                except ValueError:
                    continue
        
        return sorted(iterations)
    
    def find_artifact_iteration(self, name: str, start_iteration: Optional[int] = None) -> Optional[int]:
        """查找产物所在的迭代号
        
        从 start_iteration 开始向前查找，返回第一个找到产物的迭代号。
        
        Args:
            name: 产物名称
            start_iteration: 起始迭代号（默认使用当前迭代）
            
        Returns:
            产物所在的迭代号，如果未找到返回 None
        """
        target_iteration = start_iteration if start_iteration is not None else self.current_iteration
        
        if target_iteration is None:
            return None
        
        for iteration in range(target_iteration, 0, -1):
            target_path = self._prepare_path(name, iteration, create=False)
            if target_path.exists():
                return iteration
        
        return None

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #
    def _iteration_dir(self, iteration: Optional[int]) -> Path:
        if iteration is None:
            return self.session_dir
        return self.session_dir / f"iteration_{int(iteration):02d}"

    def _prepare_path(
        self,
        name: str,
        iteration: Optional[int],
        create: bool = True,
    ) -> Path:
        """根据名称和迭代生成目标路径"""
        if iteration is None:
            iteration = self.current_iteration
        iteration_dir = self._iteration_dir(iteration)
        if create:
            iteration_dir.mkdir(parents=True, exist_ok=True)
        relative_path = Path(name)
        target_path = iteration_dir / relative_path
        if create:
            target_path.parent.mkdir(parents=True, exist_ok=True)
        return target_path

