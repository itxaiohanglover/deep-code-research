"""DeepCodeResearch 源代码包"""

__version__ = "0.1.0"

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(".env", override=True)

# 设置全局输出目录路径
# 从当前文件位置（src/__init__.py）向上两级到项目根目录
_current_file = Path(__file__).resolve()
_project_root = _current_file.parent.parent  # 从 src/ 到项目根目录
_default_output_dir = _project_root / "output"

# 如果环境变量 OUTPUT_DIR 未设置，设置为项目根目录下的 output
if "OUTPUT_DIR" not in os.environ:
    os.environ["OUTPUT_DIR"] = str(_default_output_dir)
    os.environ["output_dir"] = str(_default_output_dir)  # 小写版本，某些地方可能使用