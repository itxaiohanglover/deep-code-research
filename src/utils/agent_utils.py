"""Agent 工具函数

提供 Agent 执行过程中的公共工具函数，简化 Agent 代码。

职责：
1. 从 LLM 响应中提取文本内容
2. 解析和保存映射关系
3. 其他 Agent 执行过程中的公共逻辑
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger

logger = get_logger()


def extract_message_content(result: Any) -> str:
    """从 LLM 响应中提取文本内容
    
    步骤：
    1. 如果是 Message 列表，提取最后一条助手消息的内容
    2. 如果是字符串，直接返回
    3. 否则转换为字符串
    
    Args:
        result: LLM 响应（Message 列表、字符串或其他）
        
    Returns:
        提取的文本内容
    """
    if isinstance(result, list):
        # 如果是 Message 列表，提取最后一条助手消息的内容
        for msg in reversed(result):
            if isinstance(msg, Message) and msg.role == "assistant" and msg.content:
                return msg.content
        return ""
    elif isinstance(result, str):
        return result
    else:
        return str(result)


def extract_mapping_from_output(output: str, tag: str = "") -> Dict[str, List[str]]:
    """从 LLM 输出中提取映射关系
    
    步骤：
    1. 尝试从 JSON 代码块中提取映射
    2. 如果没有找到，尝试从文本中提取
    
    Args:
        output: LLM 输出内容
        tag: Agent 标签（用于日志）
        
    Returns:
        映射字典：task_id -> [code_files]
    """
    mapping = {}
    
    # 1. 尝试从 JSON 代码块中提取映射
    json_pattern = r'```json[:\s]*spec_code_mapping\.json\s*\n(.*?)```'
    matches = re.findall(json_pattern, output, re.DOTALL)
    
    if matches:
        try:
            mapping = json.loads(matches[0])
            if tag:
                logger.info(f"[{tag}] 从输出中提取到映射关系: {len(mapping)} 个任务")
        except Exception as e:
            if tag:
                logger.warning(f"[{tag}] 解析映射 JSON 失败: {e}")
    
    # 2. 如果没有找到 JSON，尝试从文本中提取
    if not mapping:
        # 查找类似 "task_1: [file1.py, file2.py]" 的模式
        pattern = r'(task_\d+)[:：]\s*\[(.*?)\]'
        matches = re.findall(pattern, output)
        for task_id, files_str in matches:
            files = [f.strip().strip('"\'') for f in files_str.split(',') if f.strip()]
            if files:
                mapping[task_id] = files
    
    return mapping


def load_mapping_from_file(mapping_file: Path) -> dict | None:
    """从文件加载映射关系
    
    步骤：
    1. 检查文件是否存在
    2. 读取并解析 JSON
    3. 提取 mapping 字段
    
    Args:
        mapping_file: 映射文件路径
        
    Returns:
        映射字典，如果失败返回 None
    """
    if not mapping_file.exists():
        return None
    
    try:
        mapping_data = json.loads(mapping_file.read_text(encoding="utf-8"))
        return mapping_data.get("mapping", {})
    except Exception as e:
        logger.warning(f"读取映射文件失败: {e}")
        return None


def save_mapping_to_file(mapping: Dict[str, List[str]], mapping_file: Path, tag: str = "") -> None:
    """保存映射关系到文件
    
    步骤：
    1. 构建映射数据（包含版本和时间戳）
    2. 保存到文件
    
    Args:
        mapping: 映射字典
        mapping_file: 映射文件路径
        tag: Agent 标签（用于日志）
    """
    mapping_data = {
        "version": "1.0.0",
        "generated_at": datetime.now().isoformat(),
        "mapping": mapping
    }
    mapping_file.write_text(
        json.dumps(mapping_data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    if tag:
        logger.info(f"[{tag}] 已保存映射关系到: {mapping_file}")

