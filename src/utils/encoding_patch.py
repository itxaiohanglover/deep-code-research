"""编码补丁：修复 ms-agent 在 Windows 系统上的编码问题

ms-agent 的 save_history 函数在保存 JSON 文件时没有指定 UTF-8 编码，
导致在 Windows 系统上使用 GBK 编码时无法处理 emoji 等 Unicode 字符。

使用方法：
    from src.utils.encoding_patch import apply_encoding_patch
    apply_encoding_patch()
"""

import os
from pathlib import Path


def apply_encoding_patch():
    """应用编码补丁，修复 ms-agent 的 save_history 函数
    
    需要在导入 ms_agent 模块之前调用，或者在导入后立即调用。
    """
    try:
        # 定义修复后的函数
        def patched_save_history(output_dir: str, task: str, config, messages):
            """修复后的 save_history 函数，使用 UTF-8 编码，并支持按会话分类
            
            注意：如果 output_dir 已经是 session 目录（如 output/{session_id}），
            则直接使用 output_dir/memory。
            如果 output_dir 是全局目录（如 output），则检查环境变量 SESSION_ID，
            如果有则使用 output/{session_id}/memory。
            """
            import json
            from omegaconf import OmegaConf
            from pathlib import Path
            
            # 检查 output_dir 是否已经是 session 目录
            output_path = Path(output_dir)
            session_id = os.getenv("SESSION_ID")
            
            # 如果 output_dir 是全局目录且有 session_id，使用 session 目录
            if session_id and not any(part == session_id for part in output_path.parts):
                # output_dir 是全局目录，需要添加 session_id
                cache_dir = output_path / session_id / 'memory'
            else:
                # output_dir 已经是 session 目录，直接使用
                cache_dir = output_path / 'memory'
            
            os.makedirs(cache_dir, exist_ok=True)
            config_file = os.path.join(str(cache_dir), f'{task}.yaml')
            message_file = os.path.join(str(cache_dir), f'{task}.json')
            
            # 使用 UTF-8 编码保存配置文件
            with open(config_file, 'w', encoding='utf-8') as f:
                OmegaConf.save(config, f)
            
            # 使用 UTF-8 编码保存消息历史
            with open(message_file, 'w', encoding='utf-8') as f:
                json.dump([message.to_dict() for message in messages],
                          f,
                          indent=4,
                          ensure_ascii=False)
        
        # 定义修复后的 read_history 函数
        def patched_read_history(output_dir: str, task: str):
            """修复后的 read_history 函数，支持按会话分类，使用 UTF-8 编码"""
            import json
            from pathlib import Path
            from omegaconf import OmegaConf
            from ms_agent.llm import Message
            from ms_agent.config import Config
            
            # 检查 output_dir 是否已经是 session 目录
            output_path = Path(output_dir)
            session_id = os.getenv("SESSION_ID")
            
            # 如果 output_dir 是全局目录且有 session_id，使用 session 目录
            if session_id and not any(part == session_id for part in output_path.parts):
                # output_dir 是全局目录，需要添加 session_id
                cache_dir = output_path / session_id / 'memory'
            else:
                # output_dir 已经是 session 目录，直接使用
                cache_dir = output_path / 'memory'
            
            os.makedirs(cache_dir, exist_ok=True)
            config_file = cache_dir / f'{task}.yaml'
            message_file = cache_dir / f'{task}.json'
            
            config = None
            messages = None
            if config_file.exists():
                config = OmegaConf.load(str(config_file))
                config = Config.fill_missing_fields(config)
            if message_file.exists():
                with open(message_file, 'r', encoding='utf-8') as f:
                    messages = json.load(f)
                    messages = [Message(**message) for message in messages]
            return config, messages
        
        # 替换 ms_agent.utils.utils 中的函数（原始定义位置）
        import ms_agent.utils.utils as utils_module
        utils_module.save_history = patched_save_history
        utils_module.read_history = patched_read_history
        
        # 替换 ms_agent.utils 包中导出的函数
        import ms_agent.utils as utils_package
        utils_package.save_history = patched_save_history
        utils_package.read_history = patched_read_history
        
        # 替换已经导入的模块中的引用（如果已经导入）
        import sys
        for module_name, module in sys.modules.items():
            if module_name.startswith('ms_agent'):
                # 替换 save_history
                if hasattr(module, 'save_history'):
                    try:
                        import inspect
                        original_func = getattr(module, 'save_history')
                        # 如果是函数且来自 utils.utils，则替换
                        if inspect.isfunction(original_func) and hasattr(original_func, '__module__'):
                            if 'utils.utils' in str(original_func.__module__):
                                setattr(module, 'save_history', patched_save_history)
                    except:
                        pass
                # 替换 read_history
                if hasattr(module, 'read_history'):
                    try:
                        import inspect
                        original_func = getattr(module, 'read_history')
                        # 如果是函数且来自 utils.utils，则替换
                        if inspect.isfunction(original_func) and hasattr(original_func, '__module__'):
                            if 'utils.utils' in str(original_func.__module__):
                                setattr(module, 'read_history', patched_read_history)
                    except:
                        pass
        
        print("[编码补丁] ✅ 已应用 ms-agent 编码补丁，历史记录将使用 UTF-8 编码保存")
        return True
    except Exception as e:
        import traceback
        print(f"[编码补丁] ❌ 应用编码补丁失败: {e}")
        traceback.print_exc()
        return False


def apply_encoding_patch_if_needed():
    """如果需要，应用编码补丁（仅在 Windows 系统上）"""
    if os.name == 'nt':  # Windows 系统
        return apply_encoding_patch()
    return False

