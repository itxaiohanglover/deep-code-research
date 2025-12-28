"""配置生命周期处理器：统一管理 workflow 上下文和配置

职责：
1. 修复 llm_base_url KeyError 问题（环境变量映射）
2. 在 task_begin 时设置 config.output_dir（确保是绝对路径）
3. 管理 workflow 上下文（iteration, step）
4. 确保输出目录存在

注意：
- 路径定义由 PathManager 负责
- 路径规范化由 PathResolver 负责（在 workflow 中处理）
- 本类只负责配置生命周期管理
"""

import os
from pathlib import Path

from ms_agent.config.config import ConfigLifecycleHandler
from omegaconf import DictConfig
from ms_agent.utils import get_logger
from src.utils.path_manager import PathManager
from src.utils.workflow_manager import workflow_manager

logger = get_logger()


class ConfigHandler(ConfigLifecycleHandler):
    """配置生命周期处理器
    
    职责：
    1. 修复 llm_base_url KeyError 问题
    2. 设置 config.output_dir（从环境变量或默认值，确保是绝对路径）
    3. 管理 workflow 上下文（iteration, step）
    4. 确保输出目录存在
    """

    def task_begin(self, config: DictConfig, tag: str) -> DictConfig:
        """任务开始时调用
        
        步骤：
        1. 修复环境变量映射问题（llm_base_url KeyError）
        2. 获取 workflow 上下文（iteration, step）
        3. 设置 config.output_dir（绝对路径，包含 session_id）
        4. 确保输出目录存在
        """
        # Fix: Ensure llm_base_url is available from MODELSCOPE_BASE_URL
        # This fixes KeyError: 'llm_base_url' in ms-agent config system
        # ms-agent's config._update_config() expects LLM_BASE_URL env var
        modelscope_base_url = os.getenv('MODELSCOPE_BASE_URL')
        if modelscope_base_url and not os.getenv('LLM_BASE_URL'):
            os.environ['LLM_BASE_URL'] = modelscope_base_url
            logger.debug(f'[ConfigHandler] 设置 LLM_BASE_URL = {modelscope_base_url}')
        
        modelscope_api_key = os.getenv('MODELSCOPE_API_KEY')
        if modelscope_api_key and not os.getenv('LLM_API_KEY'):
            os.environ['LLM_API_KEY'] = modelscope_api_key
            logger.debug('[ConfigHandler] 设置 LLM_API_KEY')
        
        iteration = workflow_manager.get_iteration()
        step = workflow_manager.get_step()
        
        logger.debug(f'[ConfigHandler] 任务开始: {tag} (迭代 {iteration}, 步骤 {step})')
        
        # 确保 workflow_manager 的迭代设置正确
        workflow_manager.set_iteration(iteration)
        
        # 设置 output_dir（确保是绝对路径）
        # 重要：config.output_dir 必须包含 session_id，确保 LLM 调用 file_system 工具时
        # 文件保存到正确的 session 目录（output/{session_id}/）
        base_output_dir = self._resolve_output_dir(config)
        session_id = os.getenv("SESSION_ID")
        
        if session_id:
            # 包含 session_id 的完整路径：output/{session_id}/
            output_dir = base_output_dir / session_id
        else:
            output_dir = base_output_dir
        
        config.output_dir = str(output_dir)
        
        # 确保所有输出目录存在
        # 注意：config.output_dir 已经包含 session_id，PathManager 应该直接使用
        # 传入 session_id=None 表示不要再添加 session_id
        path_manager = PathManager(output_dir, session_id=None)
        path_manager.ensure_dirs()
        
        logger.debug(f'[ConfigHandler] 设置 output_dir: {config.output_dir} (session_id={session_id})')
        
        return config

    def task_end(self, config: DictConfig, tag: str) -> DictConfig:
        """任务结束时调用"""
        iteration = workflow_manager.get_iteration()
        logger.debug(f'[ConfigHandler] 任务结束: {tag} (迭代 {iteration})')
        return config
    
    def _resolve_output_dir(self, config: DictConfig) -> Path:
        """解析 output_dir 路径（确保是绝对路径）
        
        优先级：
        1. 环境变量 OUTPUT_DIR（如果设置）
        2. config.output_dir（如果已设置）
        3. 默认值 "output"（相对于项目根目录）
        
        Returns:
            绝对路径的 Path 对象
        """
        # 1. 从环境变量获取
        output_dir_env = os.getenv("OUTPUT_DIR")
        if output_dir_env:
            output_dir_path = Path(output_dir_env)
            if output_dir_path.is_absolute():
                return output_dir_path.resolve()
            # 相对路径：基于项目根目录解析
            project_root = self._get_project_root(config)
            return (project_root / output_dir_env).resolve()
        
        # 2. 从 config 获取
        if hasattr(config, 'output_dir') and config.output_dir:
            output_dir_path = Path(config.output_dir)
            if output_dir_path.is_absolute():
                return output_dir_path.resolve()
            # 相对路径：基于项目根目录解析
            project_root = self._get_project_root(config)
            return (project_root / config.output_dir).resolve()
        
        # 3. 默认值
        project_root = self._get_project_root(config)
        return (project_root / "output").resolve()
    
    def _get_project_root(self, config: DictConfig) -> Path:
        """获取项目根目录
        
        规则：
        - 如果 config.local_dir 存在，项目根目录 = local_dir 的父目录的父目录
        - 否则，使用当前工作目录
        """
        if hasattr(config, 'local_dir') and config.local_dir:
            # local_dir 通常是 src/config，向上两级到项目根目录
            return Path(config.local_dir).parent.parent.resolve()
        return Path.cwd().resolve()
