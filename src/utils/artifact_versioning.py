"""产物版本管理 - 支持产物的版本追踪和回滚

解决问题：
1. 无法追踪产物的历史版本
2. 无法比较不同版本的差异
3. 无法回滚到之前的版本

设计原则：
1. 轻量级版本存储（仅保存差异或全量）
2. 自动清理旧版本
3. 支持快速版本切换
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import difflib

from ms_agent.utils import get_logger

logger = get_logger()


class ArtifactVersion:
    """单个产物版本"""
    
    def __init__(
        self,
        version_id: str,
        artifact_name: str,
        content: str,
        content_hash: str,
        timestamp: str,
        metadata: Optional[Dict] = None,
    ):
        self.version_id = version_id
        self.artifact_name = artifact_name
        self.content = content
        self.content_hash = content_hash
        self.timestamp = timestamp
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "version_id": self.version_id,
            "artifact_name": self.artifact_name,
            "content_hash": self.content_hash,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict, content: str = "") -> "ArtifactVersion":
        return cls(
            version_id=data["version_id"],
            artifact_name=data["artifact_name"],
            content=content,
            content_hash=data["content_hash"],
            timestamp=data["timestamp"],
            metadata=data.get("metadata", {}),
        )


class ArtifactVersionManager:
    """产物版本管理器
    
    功能：
    1. 保存产物版本
    2. 获取历史版本
    3. 比较版本差异
    4. 回滚到指定版本
    
    使用示例：
        manager = ArtifactVersionManager(session_dir)
        
        # 保存新版本
        version = manager.save_version("requirements", content)
        
        # 获取历史版本
        versions = manager.get_versions("requirements")
        
        # 比较差异
        diff = manager.compare_versions("requirements", "v1", "v2")
        
        # 回滚
        manager.rollback("requirements", "v1")
    """
    
    def __init__(
        self,
        session_dir: Path,
        versions_dir: str = "versions",
        max_versions: int = 10,
    ):
        """初始化
        
        Args:
            session_dir: 会话目录
            versions_dir: 版本存储子目录
            max_versions: 每个产物最大保留版本数
        """
        self.session_dir = Path(session_dir)
        self.versions_dir = self.session_dir / versions_dir
        self.max_versions = max_versions
        self._index_file = self.versions_dir / "version_index.json"
        self._index: Dict[str, List[Dict]] = {}
        self._load_index()
    
    def _load_index(self) -> None:
        """加载版本索引"""
        if self._index_file.exists():
            try:
                with open(self._index_file, 'r', encoding='utf-8') as f:
                    self._index = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"[VersionManager] 加载索引失败: {e}")
                self._index = {}
    
    def _save_index(self) -> None:
        """保存版本索引"""
        try:
            self.versions_dir.mkdir(parents=True, exist_ok=True)
            with open(self._index_file, 'w', encoding='utf-8') as f:
                json.dump(self._index, f, ensure_ascii=False, indent=2)
        except IOError as e:
            logger.error(f"[VersionManager] 保存索引失败: {e}")
    
    def _compute_hash(self, content: str) -> str:
        """计算内容 hash"""
        import hashlib
        return hashlib.sha256(content.encode('utf-8')).hexdigest()[:12]
    
    def _get_version_path(self, artifact_name: str, version_id: str) -> Path:
        """获取版本文件路径"""
        return self.versions_dir / artifact_name / f"{version_id}.txt"
    
    def save_version(
        self,
        artifact_name: str,
        content: str,
        metadata: Optional[Dict] = None,
    ) -> ArtifactVersion:
        """保存新版本
        
        Args:
            artifact_name: 产物名称
            content: 内容
            metadata: 元数据
            
        Returns:
            版本对象
        """
        content_hash = self._compute_hash(content)
        
        # 检查是否与最新版本相同
        versions = self._index.get(artifact_name, [])
        if versions:
            latest = versions[-1]
            if latest["content_hash"] == content_hash:
                logger.debug(f"[VersionManager] 内容未变更，跳过: {artifact_name}")
                return ArtifactVersion.from_dict(latest, content)
        
        # 生成版本 ID
        version_num = len(versions) + 1
        version_id = f"v{version_num}"
        timestamp = datetime.now().isoformat()
        
        # 保存内容
        version_path = self._get_version_path(artifact_name, version_id)
        version_path.parent.mkdir(parents=True, exist_ok=True)
        with open(version_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # 创建版本对象
        version = ArtifactVersion(
            version_id=version_id,
            artifact_name=artifact_name,
            content=content,
            content_hash=content_hash,
            timestamp=timestamp,
            metadata=metadata,
        )
        
        # 更新索引
        if artifact_name not in self._index:
            self._index[artifact_name] = []
        self._index[artifact_name].append(version.to_dict())
        
        # 清理旧版本
        self._cleanup_old_versions(artifact_name)
        
        self._save_index()
        logger.info(f"[VersionManager] 保存版本: {artifact_name}/{version_id}")
        
        return version
    
    def _cleanup_old_versions(self, artifact_name: str) -> None:
        """清理旧版本"""
        versions = self._index.get(artifact_name, [])
        
        while len(versions) > self.max_versions:
            old_version = versions.pop(0)
            old_path = self._get_version_path(artifact_name, old_version["version_id"])
            if old_path.exists():
                try:
                    old_path.unlink()
                    logger.debug(f"[VersionManager] 清理旧版本: {artifact_name}/{old_version['version_id']}")
                except OSError as e:
                    logger.warning(f"[VersionManager] 删除旧版本失败: {e}")
    
    def get_versions(self, artifact_name: str) -> List[Dict]:
        """获取产物的所有版本
        
        Args:
            artifact_name: 产物名称
            
        Returns:
            版本列表（元数据）
        """
        return self._index.get(artifact_name, [])
    
    def get_version(self, artifact_name: str, version_id: str) -> Optional[ArtifactVersion]:
        """获取指定版本
        
        Args:
            artifact_name: 产物名称
            version_id: 版本 ID
            
        Returns:
            版本对象或 None
        """
        versions = self._index.get(artifact_name, [])
        
        for v in versions:
            if v["version_id"] == version_id:
                version_path = self._get_version_path(artifact_name, version_id)
                if version_path.exists():
                    content = version_path.read_text(encoding='utf-8')
                    return ArtifactVersion.from_dict(v, content)
        
        return None
    
    def get_latest_version(self, artifact_name: str) -> Optional[ArtifactVersion]:
        """获取最新版本
        
        Args:
            artifact_name: 产物名称
            
        Returns:
            最新版本或 None
        """
        versions = self._index.get(artifact_name, [])
        if not versions:
            return None
        
        latest = versions[-1]
        return self.get_version(artifact_name, latest["version_id"])
    
    def compare_versions(
        self,
        artifact_name: str,
        version_id_1: str,
        version_id_2: str,
        context_lines: int = 3,
    ) -> str:
        """比较两个版本的差异
        
        Args:
            artifact_name: 产物名称
            version_id_1: 版本 1 ID
            version_id_2: 版本 2 ID
            context_lines: 上下文行数
            
        Returns:
            差异文本（unified diff 格式）
        """
        v1 = self.get_version(artifact_name, version_id_1)
        v2 = self.get_version(artifact_name, version_id_2)
        
        if not v1 or not v2:
            return "版本不存在"
        
        diff = difflib.unified_diff(
            v1.content.splitlines(keepends=True),
            v2.content.splitlines(keepends=True),
            fromfile=f"{artifact_name}/{version_id_1}",
            tofile=f"{artifact_name}/{version_id_2}",
            n=context_lines,
        )
        
        return ''.join(diff)
    
    def rollback(self, artifact_name: str, version_id: str) -> Optional[str]:
        """回滚到指定版本
        
        Args:
            artifact_name: 产物名称
            version_id: 目标版本 ID
            
        Returns:
            版本内容或 None
        """
        version = self.get_version(artifact_name, version_id)
        if not version:
            logger.warning(f"[VersionManager] 版本不存在: {artifact_name}/{version_id}")
            return None
        
        # 保存当前版本（作为新版本）
        self.save_version(
            artifact_name,
            version.content,
            metadata={"rollback_from": version_id},
        )
        
        logger.info(f"[VersionManager] 回滚成功: {artifact_name} -> {version_id}")
        return version.content
    
    def get_summary(self) -> Dict[str, Any]:
        """获取版本管理摘要"""
        total_versions = sum(len(v) for v in self._index.values())
        
        return {
            "total_artifacts": len(self._index),
            "total_versions": total_versions,
            "artifacts": {
                name: len(versions)
                for name, versions in self._index.items()
            },
        }
    
    def clear_all(self) -> None:
        """清除所有版本"""
        if self.versions_dir.exists():
            shutil.rmtree(self.versions_dir)
        self._index = {}
        logger.info("[VersionManager] 所有版本已清除")


def get_version_manager(session_dir: Path) -> ArtifactVersionManager:
    """获取版本管理器实例
    
    Args:
        session_dir: 会话目录
        
    Returns:
        ArtifactVersionManager 实例
    """
    return ArtifactVersionManager(session_dir)

