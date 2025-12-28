"""路径解析器：规范化 Agent 配置中的路径

职责：
1. 将配置中的路径（handler、callback、tool plugin、code_file）转换为相对于 local_dir 的路径
2. 确保路径可以被 ms-agent 正确加载

注意：
- 不负责路径定义（由 PathManager 负责）
- 不负责 output_dir 设置（由 ConfigHandler 负责）
- 只负责路径规范化（相对路径转换）
"""

import os
from pathlib import Path
from typing import Any

from ms_agent.utils import get_logger

logger = get_logger()


class PathResolver:
    """路径解析器：规范化 Agent 配置中的路径
    
    职责：
    1. 规范化 handler 路径
    2. 规范化 callback 路径
    3. 规范化 tool plugin 路径
    4. 规范化 code_file 路径
    
    规则：
    - 将绝对路径或项目根目录相对路径转换为相对于 local_dir (src/config) 的路径
    - 确保路径可以被 ms-agent 正确加载
    """

    def __init__(self, project_root: Path, config_dir: Path):
        """初始化路径解析器
        
        Args:
            project_root: 项目根目录
            config_dir: 配置目录（通常是 src/config，即 local_dir）
        """
        self.project_root = project_root
        self.config_dir = config_dir

    def _resolve_to_absolute_path(self, path_str: str) -> Path:
        """将路径字符串解析为绝对路径
        
        规则：
        - 如果以 "src/" 开头，从项目根目录解析
        - 如果以 "callbacks/" 或 "agents/" 开头，从 src/ 目录解析
        - 否则，假设已经在 src/ 下，从项目根目录解析
        
        Args:
            path_str: 路径字符串
            
        Returns:
            绝对路径的 Path 对象
        """
        if path_str.startswith("src/"):
            return self.project_root / path_str[4:]
        elif path_str.startswith("callbacks/") or path_str.startswith("agents/"):
            return self.project_root / "src" / path_str
        else:
            # 假设已经在 src/ 下
            return (self.project_root / "src" / path_str).resolve()
    
    def _to_relative_path(self, absolute_path: Path, base_dir: Path) -> str:
        """将绝对路径转换为相对于 base_dir 的相对路径
        
        Args:
            absolute_path: 绝对路径
            base_dir: 基准目录（通常是 local_dir）
            
        Returns:
            相对路径字符串（使用 / 分隔符）
        """
        try:
            relative_path = os.path.relpath(str(absolute_path.resolve()), str(base_dir.resolve()))
            return relative_path.replace("\\", "/")
        except Exception as e:
            logger.warning(f"[PathResolver] 无法计算相对路径: {e}")
            return str(absolute_path)

    def normalize_handler_path(self, agent_config_obj: Any, step: str) -> None:
        """规范化 handler 路径
        
        步骤：
        1. 解析为绝对路径
        2. 转换为相对于 local_dir 的路径
        3. 转换为模块路径格式（使用 . 分隔符）
        """
        if not hasattr(agent_config_obj, "handler") or not agent_config_obj.handler:
            return

        handler_path = agent_config_obj.handler
        if isinstance(handler_path, str) and not Path(handler_path).is_absolute():
            # 1. 解析为绝对路径
            resolved_path = self._resolve_to_absolute_path(handler_path)
            
            # 2. 转换为相对于 local_dir 的路径
            local_dir = self._get_local_dir(agent_config_obj)
            try:
                relative_path = resolved_path.relative_to(local_dir)
                # 3. 转换为模块路径格式（使用 . 分隔符）
                handler_name = resolved_path.stem
                relative_parent = relative_path.parent
                if str(relative_parent) == ".":
                    normalized_path = handler_name
                else:
                    module_path = str(relative_parent).replace("\\", "/").replace("/", ".")
                    normalized_path = f"{module_path}.{handler_name}" if module_path else handler_name
                agent_config_obj.handler = normalized_path
                logger.debug(f"[PathResolver] 规范化 handler: {handler_path} -> {normalized_path}")
            except ValueError:
                # 如果无法计算相对路径，添加到 sys.path 并使用文件名
                handler_parent = resolved_path.parent
                import sys
                if str(handler_parent) not in sys.path:
                    sys.path.insert(0, str(handler_parent))
                normalized_path = resolved_path.stem
                agent_config_obj.handler = normalized_path
                logger.debug(
                    f"[PathResolver] Handler {handler_path} 无法计算相对路径，"
                    f"已添加 {handler_parent} 到 sys.path，使用: {normalized_path}"
                )
            except Exception as e:
                logger.warning(f"[PathResolver] 无法规范化 handler 路径 {handler_path}: {e}，保持原路径")

    def normalize_callback_paths(self, agent_config_obj: Any, step: str) -> None:
        """规范化 callback 路径
        
        步骤：
        1. 解析为绝对路径
        2. 确保有 .py 后缀
        3. 转换为相对于 local_dir 的路径（目录 + 文件名，不含 .py）
        
        注意：ms-agent 会自动去掉 .py 后缀，所以相对路径应该包含目录和文件名（不含 .py）
        """
        if not hasattr(agent_config_obj, "callbacks") or not agent_config_obj.callbacks:
            return

        normalized_callbacks = []
        local_dir = self._get_local_dir(agent_config_obj)
        
        for callback_path in agent_config_obj.callbacks:
            if isinstance(callback_path, str) and not Path(callback_path).is_absolute():
                # 1. 解析为绝对路径
                resolved_path = self._resolve_to_absolute_path(callback_path)
                
                # 2. 确保有 .py 后缀
                if not resolved_path.suffix:
                    resolved_path = resolved_path.with_suffix('.py')
                elif resolved_path.suffix != '.py':
                    resolved_path = resolved_path.parent / f"{resolved_path.stem}.py"
                
                # 3. 验证路径是否存在
                if not resolved_path.exists():
                    logger.warning(
                        f"[PathResolver] callback 路径不存在: {resolved_path}，"
                        f"原路径: {callback_path}，保持原路径"
                    )
                    normalized_callbacks.append(callback_path)
                    continue
                
                # 4. 转换为相对于 local_dir 的路径
                try:
                    callback_dir = resolved_path.parent
                    relative_dir = os.path.relpath(str(callback_dir.resolve()), str(local_dir.resolve()))
                    callback_name = resolved_path.stem  # 去掉 .py 后缀的文件名
                    
                    # 组合相对路径：如果 relative_dir 是 "."，则只使用文件名
                    if relative_dir == ".":
                        relative_path = callback_name
                    else:
                        relative_path = f"{relative_dir}/{callback_name}".replace("\\", "/")
                    
                    normalized_callbacks.append(relative_path)
                    logger.debug(f"[PathResolver] 规范化 callback: {callback_path} -> {relative_path}")
                except Exception as e:
                    logger.warning(f"[PathResolver] 无法规范化 callback 路径 {callback_path}: {e}，保持原路径")
                    normalized_callbacks.append(callback_path)
            else:
                normalized_callbacks.append(callback_path)
        
        agent_config_obj.callbacks = normalized_callbacks

    def normalize_tool_plugin_paths(self, agent_config_obj: Any, step: str) -> None:
        """规范化 tool plugin 路径
        
        步骤：
        1. 解析为绝对路径
        2. 转换为相对于 local_dir 的路径
        """
        if not hasattr(agent_config_obj, "tools") or not hasattr(agent_config_obj.tools, "plugins"):
            return

        plugins = agent_config_obj.tools.plugins
        if not plugins:
            return

        normalized_plugins = []
        local_dir = self._get_local_dir(agent_config_obj)
        
        for plugin_path in plugins:
            if isinstance(plugin_path, str) and not Path(plugin_path).is_absolute():
                # 1. 解析为绝对路径
                resolved_path = self._resolve_to_absolute_path(plugin_path)
                
                # 2. 转换为相对于 local_dir 的路径
                try:
                    relative_path = self._to_relative_path(resolved_path, local_dir)
                    normalized_plugins.append(relative_path)
                    logger.debug(f"[PathResolver] 规范化 tool plugin: {plugin_path} -> {relative_path}")
                except Exception as e:
                    logger.warning(f"[PathResolver] 无法规范化 tool plugin 路径 {plugin_path}: {e}，保持原路径")
                    normalized_plugins.append(plugin_path)
            else:
                normalized_plugins.append(plugin_path)
        
        agent_config_obj.tools.plugins = normalized_plugins

    def normalize_code_file_path(self, agent_config_obj: Any, step: str) -> None:
        """规范化 code_file 路径
        
        步骤：
        1. 解析为绝对路径
        2. 验证路径是否存在
        3. 转换为相对于 local_dir 的路径
        """
        if not hasattr(agent_config_obj, "code_file") or not agent_config_obj.code_file:
            return

        code_file_path = agent_config_obj.code_file
        local_dir = self._get_local_dir(agent_config_obj)
        
        if isinstance(code_file_path, str) and not Path(code_file_path).is_absolute():
            # 1. 解析为绝对路径
            resolved_path = self._resolve_to_absolute_path(code_file_path)
            
            # 2. 验证路径是否存在
            if not resolved_path.exists():
                logger.warning(
                    f"[PathResolver] code_file 路径不存在: {resolved_path}，"
                    f"原路径: {code_file_path}，保持原路径"
                )
                return
            
            # 3. 转换为相对于 local_dir 的路径
            try:
                relative_path = self._to_relative_path(resolved_path, local_dir)
                agent_config_obj.code_file = relative_path
                logger.debug(f"[PathResolver] 规范化 code_file: {code_file_path} -> {relative_path}")
            except Exception as e:
                logger.warning(f"[PathResolver] 无法规范化 code_file 路径 {code_file_path}: {e}，使用绝对路径")
                agent_config_obj.code_file = str(resolved_path.resolve()).replace("\\", "/")
        elif isinstance(code_file_path, str) and Path(code_file_path).is_absolute():
            # 绝对路径：转换为相对于 local_dir 的路径
            try:
                relative_path = self._to_relative_path(Path(code_file_path), local_dir)
                agent_config_obj.code_file = relative_path
                logger.debug(f"[PathResolver] 规范化绝对路径 code_file: {code_file_path} -> {relative_path}")
            except Exception as e:
                logger.warning(f"[PathResolver] 无法规范化绝对路径 code_file {code_file_path}: {e}，保持原路径")
    
    def _get_local_dir(self, agent_config_obj: Any) -> Path:
        """获取 local_dir（配置目录）
        
        Args:
            agent_config_obj: Agent 配置对象
            
        Returns:
            local_dir 的 Path 对象
        """
        if hasattr(agent_config_obj, "local_dir") and agent_config_obj.local_dir:
            return Path(agent_config_obj.local_dir)
        return self.config_dir

    def normalize_all_paths(self, agent_config_obj: Any, step: str) -> None:
        """规范化所有路径
        
        按顺序规范化：
        1. handler 路径
        2. callback 路径
        3. tool plugin 路径
        4. code_file 路径
        """
        self.normalize_handler_path(agent_config_obj, step)
        self.normalize_callback_paths(agent_config_obj, step)
        self.normalize_tool_plugin_paths(agent_config_obj, step)
        self.normalize_code_file_path(agent_config_obj, step)

