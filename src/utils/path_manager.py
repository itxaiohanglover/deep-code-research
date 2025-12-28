"""路径管理器：定义和管理输出路径结构

职责：
1. 定义所有输出目录的结构（artifacts、repo、spec_kit 等）
2. 提供便捷的路径访问接口
3. 确保目录存在

注意：
- 不负责路径解析（由 PathResolver 负责）
- 不负责路径规范化（由 PathResolver 负责）
- 只负责路径定义和管理
"""

import os
from pathlib import Path
from typing import Optional
from omegaconf import DictConfig


class PathManager:
    """路径管理器：定义和管理输出路径结构
    
    职责：
    1. 定义所有输出目录的结构
    2. 提供便捷的路径访问接口
    3. 确保目录存在
    4. 支持按会话分类（session_id）
    
    路径结构：
    - output/
      - skills/              # 常驻，所有会话共享
      - {session_id}/        # 按会话分类
        - artifacts/         # 文本产物
        - repo/              # 生成的代码仓库
        - spec_kit/          # Spec Kit 文档
        - memory/            # 记忆存储
        - uploads/           # 用户上传文档
        - rag_index/         # RAG 索引
    
    不负责：
    - 路径解析（由 PathResolver 负责）
    - 路径规范化（由 PathResolver 负责）
    """
    
    def __init__(self, output_dir: str | Path, session_id: Optional[str] = None, auto_detect_session: bool = False):
        """初始化路径管理器
        
        Args:
            output_dir: 输出根目录（绝对路径或相对路径，会自动转换为绝对路径）
            session_id: 会话 ID（可选，如果提供则路径会按会话分类）
            auto_detect_session: 是否自动从环境变量获取 session_id（默认 False）
            
        注意：
        - 如果 output_dir 已经包含 session_id（如 output/xxx），则不要传 session_id
        - session_id=None 时不会自动从环境变量获取，除非 auto_detect_session=True
        """
        self.output_dir = Path(output_dir).resolve()
        # 只有明确要求时才从环境变量获取 session_id
        if session_id is not None:
            self.session_id = session_id
        elif auto_detect_session:
            self.session_id = os.getenv("SESSION_ID")
        else:
            self.session_id = None
        
        # Skills 目录：常驻，不按会话分类
        self.skills_dir = self.output_dir / "skills"
        
        # 如果提供了 session_id，路径按会话分类
        if self.session_id:
            session_dir = self.output_dir / self.session_id
            self.artifacts_dir = session_dir / "artifacts"
            self.repo_dir = session_dir / "repo"
            self.spec_kit_dir = session_dir / "spec_kit"
            self.uploads_dir = session_dir / "uploads"
            self.memory_dir = session_dir / "memory"
            self.rag_index_dir = session_dir / "rag_index"
        else:
            # 兼容旧版本：如果没有 session_id，使用全局路径
            self.artifacts_dir = self.output_dir / "artifacts"
            self.repo_dir = self.output_dir / "repo"
            self.spec_kit_dir = self.output_dir / "spec_kit"
            self.uploads_dir = self.output_dir / "uploads"
            self.memory_dir = self.output_dir / "memory"
            self.rag_index_dir = self.output_dir / "rag_index"
    
    @classmethod
    def from_config(cls, config: DictConfig, session_id: Optional[str] = None) -> 'PathManager':
        """从 config 创建 PathManager
        
        优先级：
        1. config.output_dir（如果已设置）
        2. 环境变量 OUTPUT_DIR
        3. 默认值 "output"
        
        注意：
        - 如果 config.output_dir 已经包含 session_id（由 ConfigHandler 设置），
          则不要再添加 session_id，避免路径重复！
        - 例如：config.output_dir = "output/fa2fecaad82b"，
          如果再传 session_id，会变成 "output/fa2fecaad82b/fa2fecaad82b/" 错误！
        
        Args:
            config: Agent 配置
            session_id: 会话 ID（可选，显式传递 None 表示不要添加 session_id）
            
        Returns:
            PathManager 实例
        """
        # 优先从 config.output_dir 获取
        output_dir = getattr(config, "output_dir", None)
        
        # 如果 config 中没有，从环境变量获取
        if not output_dir:
            output_dir = os.getenv("OUTPUT_DIR", "output")
        
        # 关键：检测 output_dir 是否已经包含 session_id
        # ConfigHandler.task_begin 会设置 config.output_dir = "output/{session_id}"
        # 此时不应再添加 session_id
        env_session_id = os.getenv("SESSION_ID")
        output_dir_str = str(output_dir)
        
        # 如果 output_dir 已经包含 session_id，不要再添加
        if env_session_id and env_session_id in output_dir_str:
            # output_dir 已经是完整路径（包含 session_id），直接使用，不传 session_id
            return cls(output_dir, session_id=None)
        
        # 否则，使用传入的 session_id 或从环境变量获取
        if session_id is None:
            session_id = env_session_id
        
        return cls(output_dir, session_id=session_id)
    
    @classmethod
    def from_env(cls, default: str = "output", session_id: Optional[str] = None, auto_detect_session: bool = True) -> 'PathManager':
        """从环境变量创建 PathManager
        
        Args:
            default: 默认输出目录（如果环境变量未设置）
            session_id: 会话 ID（可选）
            auto_detect_session: 是否自动从环境变量获取 session_id（默认 True）
            
        Returns:
            PathManager 实例
        """
        output_dir = os.getenv("OUTPUT_DIR", default)
        if session_id is None and auto_detect_session:
            session_id = os.getenv("SESSION_ID")
        return cls(output_dir, session_id=session_id)
    
    def get_artifact_path(self, session_id: Optional[str] = None, iteration: Optional[int] = None) -> Path:
        """获取产物目录路径
        
        Args:
            session_id: Session ID（可选，如果不提供则使用当前 PathManager 的 session_id）
            iteration: 迭代次数（可选）
            
        Returns:
            产物目录路径
        """
        # 如果 artifacts_dir 已经包含 session_id，直接使用
        base_dir = self.artifacts_dir
        
        # 如果提供了不同的 session_id，需要重新计算路径（向后兼容）
        if session_id and session_id != self.session_id:
            if self.session_id:
                # 当前有 session_id，需要重新计算
                base_dir = self.output_dir / session_id / "artifacts"
            else:
                # 当前没有 session_id，添加新的 session_id
                base_dir = self.output_dir / session_id / "artifacts"
        
        if iteration is not None:
            return base_dir / f"iteration_{int(iteration):02d}"
        return base_dir
    
    def ensure_dirs(self):
        """确保所有输出目录存在"""
        # Skills 目录：常驻，不按会话分类
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        
        # 其他目录：按会话分类（如果有 session_id）
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        self.spec_kit_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.rag_index_dir.mkdir(parents=True, exist_ok=True)
    
    def __repr__(self) -> str:
        return f"PathManager(output_dir={self.output_dir})"

