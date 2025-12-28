"""文件解析工具 - 从 LLM 输出中提取代码块

参考 ms-agent/projects/code_scratch/callbacks/file_parser.py
"""

import re
from typing import List, Optional, Tuple


def _extract_nested_code_block(text: str, start_pos: int) -> Tuple[str, str, int]:
    """提取支持嵌套的代码块
    
    从 start_pos 开始，找到匹配的结束标记（处理嵌套情况）。
    
    Args:
        text: 完整文本
        start_pos: 开头标记 ``` 的位置
        
    Returns:
        Tuple: (filename, code_content, end_pos)
    """
    # 找到文件名行的结束
    first_newline = text.find('\n', start_pos)
    if first_newline == -1:
        return '', '', -1
    
    # 提取文件名（格式：```language:filename 或 ```language: filename）
    header = text[start_pos:first_newline]
    match = re.match(r'```[a-zA-Z]*:\s*(.+)', header)
    if not match:
        return '', '', -1
    
    filename = match.group(1).strip()
    
    # 从文件名行之后开始扫描
    content_start = first_newline + 1
    pos = content_start
    depth = 1  # 当前代码块深度
    
    while pos < len(text) and depth > 0:
        # 找下一个 ``` 
        next_fence = text.find('```', pos)
        if next_fence == -1:
            # 没有找到结束标记，返回剩余所有内容
            return filename, text[content_start:].strip(), len(text)
        
        # 检查这个 ``` 是开始标记还是结束标记
        # 开始标记：``` 后面跟着语言标识符（字母）
        # 结束标记：``` 后面是换行、空白或文件结尾
        after_fence = text[next_fence + 3:next_fence + 4] if next_fence + 3 < len(text) else ''
        
        if after_fence and after_fence.isalpha():
            # 这是一个嵌套的开始标记
            depth += 1
            pos = next_fence + 3
        else:
            # 这是一个结束标记
            depth -= 1
            if depth == 0:
                # 找到匹配的结束标记
                code_content = text[content_start:next_fence].strip()
                # 跳过结束标记和可能的换行
                end_pos = next_fence + 3
                if end_pos < len(text) and text[end_pos] == '\n':
                    end_pos += 1
                return filename, code_content, end_pos
            pos = next_fence + 3
    
    # 没有找到匹配的结束标记
    return filename, text[content_start:].strip(), len(text)


def extract_code_blocks(
    text: str,
    target_filename: Optional[str] = None
) -> Tuple[List[dict], str]:
    """从文本中提取代码块
    
    支持的格式：
    ```python:path/to/file.py     （冒号后无空格）
    code content
    ```
    
    或:
    ```python: path/to/file.py    （冒号后有空格）
    code content
    ```
    
    注意：支持嵌套代码块（如 plan.md 中包含 ```text 显示目录结构）。
    使用深度跟踪来正确匹配开始和结束标记。
    
    Args:
        text: 要提取代码块的文本
        target_filename: 目标文件名（如果指定，只提取匹配的文件）
    
    Returns:
        Tuple:
            0: 提取的代码块列表，每个元素为 {'filename': str, 'code': str}
            1: 剩余文本内容
    """
    result = []
    remaining_parts = []
    
    # 找所有带文件名的代码块开头
    pattern = r'```[a-zA-Z]*:\s*[^\n\r`]+'
    pos = 0
    
    while pos < len(text):
        # 找下一个带文件名的代码块
        match = re.search(pattern, text[pos:])
        if not match:
            # 没有更多代码块，保留剩余文本
            remaining_parts.append(text[pos:])
            break
        
        # 保留代码块之前的文本
        block_start = pos + match.start()
        remaining_parts.append(text[pos:block_start])
        
        # 提取代码块（处理嵌套）
        filename, code, end_pos = _extract_nested_code_block(text, block_start)
        
        if filename and code:
            if target_filename is None or filename == target_filename:
                result.append({'filename': filename, 'code': code})
            else:
                # 不是目标文件，保留原样
                remaining_parts.append(text[block_start:end_pos])
        
        pos = end_pos if end_pos > block_start else block_start + 1
    
    # 组装剩余文本
    remaining_text = ''.join(remaining_parts)
    # 清理多余的空行
    remaining_text = re.sub(r'\n\s*\n\s*\n', '\n\n', remaining_text)
    remaining_text = remaining_text.strip()

    return result, remaining_text

