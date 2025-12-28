"""上下文管理器 - 动态管理 LLM 上下文长度

解决问题：
- Prompt 中硬编码截断长度（如 2000, 800 字符）
- 不同 Agent 截断长度不一致
- 可能丢失重要信息

设计原则：
1. 根据优先级动态分配 token 预算
2. 高优先级产物获得更多空间
3. 支持智能摘要和结构化截断
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import re

from ms_agent.utils import get_logger

logger = get_logger()


@dataclass
class ArtifactConfig:
    """产物配置"""
    name: str
    priority: int = 1  # 优先级：1-5，5 最高
    max_chars: Optional[int] = None  # 最大字符数（可选）
    preserve_start: bool = True  # 截断时保留开头
    preserve_end: bool = False  # 截断时保留结尾
    smart_truncate: bool = True  # 使用智能截断（保留结构）


class ContextManager:
    """上下文管理器
    
    动态管理 LLM 上下文长度，避免硬编码截断。
    
    使用示例：
        cm = ContextManager(max_chars=16000)  # 约 8000 tokens
        
        # 方式1：简单使用（按优先级自动分配）
        result = cm.fit_artifacts({
            "requirements": req_content,
            "tech_research": tech_content,
        }, priorities=["requirements", "tech_research"])
        
        # 方式2：精细控制
        result = cm.fit_artifacts_with_config({
            "requirements": ArtifactConfig(name="requirements", priority=5),
            "tech_research": ArtifactConfig(name="tech_research", priority=3),
        }, artifacts={"requirements": req_content, "tech_research": tech_content})
    """
    
    # 默认最大字符数（约 8000 tokens，适应大多数模型）
    DEFAULT_MAX_CHARS = 16000
    
    # 截断标记
    TRUNCATION_MARKER = "\n\n... [内容已截断] ...\n\n"
    
    def __init__(self, max_chars: int = DEFAULT_MAX_CHARS):
        """初始化上下文管理器
        
        Args:
            max_chars: 最大总字符数
        """
        self.max_chars = max_chars
    
    def fit_artifacts(
        self,
        artifacts: Dict[str, str],
        priorities: Optional[List[str]] = None,
        reserved_chars: int = 0,
        smart_truncate: bool = True
    ) -> Dict[str, str]:
        """根据优先级动态分配产物空间
        
        Args:
            artifacts: 产物字典 {name: content}
            priorities: 优先级列表（靠前的优先级高）
            reserved_chars: 预留字符数（给其他 prompt 内容）
            smart_truncate: 使用智能截断（保留 Markdown 结构）
            
        Returns:
            截断后的产物字典
        """
        if not artifacts:
            return {}
        
        # 可用空间
        available_chars = self.max_chars - reserved_chars
        if available_chars <= 0:
            logger.warning(f"[ContextManager] 可用空间不足: {available_chars}")
            return {k: "" for k in artifacts}
        
        # 如果未指定优先级，按字典顺序
        if priorities is None:
            priorities = list(artifacts.keys())
        
        # 计算总字符数
        total_chars = sum(len(v) for v in artifacts.values() if v)
        
        # 如果总字符数在限制内，直接返回
        if total_chars <= available_chars:
            logger.debug(f"[ContextManager] 无需截断: {total_chars} <= {available_chars} 字符")
            return artifacts
        
        logger.info(f"[ContextManager] 需要截断: {total_chars} -> {available_chars} 字符")
        
        # 按优先级分配空间
        result = {}
        remaining_chars = available_chars
        
        # 计算每个产物的权重
        n = len(priorities)
        weights = {name: n - i for i, name in enumerate(priorities)}
        total_weight = sum(weights.values())
        
        for name in priorities:
            content = artifacts.get(name, "")
            if not content:
                result[name] = ""
                continue
            
            # 按权重分配空间
            weight = weights[name]
            allocated_chars = int(remaining_chars * weight / total_weight)
            
            # 确保至少有一些空间（最少 500 字符）
            allocated_chars = max(allocated_chars, 500)
            
            # 截断内容
            if len(content) <= allocated_chars:
                result[name] = content
            else:
                if smart_truncate:
                    result[name] = self._smart_truncate(content, allocated_chars)
                else:
                    result[name] = self._truncate(content, allocated_chars)
                logger.debug(f"[ContextManager] 截断 {name}: {len(content)} -> {len(result[name])} 字符")
            
            # 更新剩余空间
            remaining_chars -= len(result[name])
            total_weight -= weight
        
        return result
    
    def truncate_single(
        self,
        content: str,
        max_chars: int,
        preserve_start: bool = True,
        preserve_end: bool = False,
        smart_truncate: bool = True
    ) -> str:
        """截断单个内容
        
        Args:
            content: 原始内容
            max_chars: 最大字符数
            preserve_start: 保留开头
            preserve_end: 保留结尾
            smart_truncate: 使用智能截断
            
        Returns:
            截断后的内容
        """
        if not content or len(content) <= max_chars:
            return content
        
        if smart_truncate:
            return self._smart_truncate(content, max_chars, preserve_start, preserve_end)
        else:
            return self._truncate(content, max_chars, preserve_start, preserve_end)
    
    def _smart_truncate(
        self,
        content: str,
        max_chars: int,
        preserve_start: bool = True,
        preserve_end: bool = False
    ) -> str:
        """智能截断：保留 Markdown 结构
        
        策略：
        1. 保留一级标题和二级标题
        2. 截断各章节内容，保留框架
        3. 保留表格标题（截断表格内容）
        """
        marker_len = len(self.TRUNCATION_MARKER)
        usable_chars = max_chars - marker_len
        
        if usable_chars <= 0:
            return content[:max_chars]
        
        # 分割章节（按一级和二级标题）
        sections = re.split(r'(^#{1,2}\s+.+$)', content, flags=re.MULTILINE)
        
        if len(sections) <= 1:
            # 没有 Markdown 结构，使用普通截断
            return self._truncate(content, max_chars, preserve_start, preserve_end)
        
        # 重组章节
        result_parts = []
        current_length = 0
        
        for i, section in enumerate(sections):
            if not section.strip():
                continue
            
            # 检查是否是标题
            is_header = re.match(r'^#{1,2}\s+', section)
            
            if is_header:
                # 标题总是保留
                result_parts.append(section)
                current_length += len(section)
            else:
                # 内容部分：根据剩余空间决定保留多少
                remaining = usable_chars - current_length
                
                if remaining <= 100:
                    # 空间不足，添加截断标记后退出
                    result_parts.append(self.TRUNCATION_MARKER)
                    break
                
                if len(section) <= remaining:
                    # 完整保留
                    result_parts.append(section)
                    current_length += len(section)
                else:
                    # 截断此章节内容
                    truncated = self._truncate_section_content(section, remaining)
                    result_parts.append(truncated)
                    current_length += len(truncated)
                    
                    # 如果还有更多章节，添加提示
                    if i < len(sections) - 1:
                        result_parts.append(self.TRUNCATION_MARKER)
                    break
        
        return ''.join(result_parts)
    
    def _truncate_section_content(self, content: str, max_chars: int) -> str:
        """截断章节内容，保留重要信息"""
        # 保留列表项开头
        lines = content.split('\n')
        result_lines = []
        current_length = 0
        
        for line in lines:
            line_len = len(line) + 1  # +1 for newline
            
            if current_length + line_len > max_chars:
                break
            
            result_lines.append(line)
            current_length += line_len
        
        return '\n'.join(result_lines)
    
    def _truncate(
        self,
        content: str,
        max_chars: int,
        preserve_start: bool = True,
        preserve_end: bool = False
    ) -> str:
        """执行简单截断
        
        Args:
            content: 原始内容
            max_chars: 最大字符数
            preserve_start: 保留开头
            preserve_end: 保留结尾
            
        Returns:
            截断后的内容
        """
        marker_len = len(self.TRUNCATION_MARKER)
        usable_chars = max_chars - marker_len
        
        if usable_chars <= 0:
            return content[:max_chars]
        
        if preserve_start and preserve_end:
            # 保留开头和结尾
            half = usable_chars // 2
            return content[:half] + self.TRUNCATION_MARKER + content[-half:]
        elif preserve_end:
            # 只保留结尾
            return self.TRUNCATION_MARKER + content[-usable_chars:]
        else:
            # 只保留开头（默认）
            return content[:usable_chars] + self.TRUNCATION_MARKER
    
    def estimate_tokens(self, text: str) -> int:
        """估算 token 数量（粗略估计）
        
        中文约 1-2 字符/token，英文约 4 字符/token
        这里使用保守估计：2 字符/token
        
        Args:
            text: 文本内容
            
        Returns:
            估算的 token 数量
        """
        if not text:
            return 0
        return len(text) // 2


# 便捷函数
def truncate_artifact(content: str, max_chars: int = 2000, smart: bool = True) -> str:
    """便捷函数：截断单个产物
    
    替代硬编码的截断逻辑：
    - 旧: content[:2000] + "..."
    - 新: truncate_artifact(content, 2000)
    
    Args:
        content: 原始内容
        max_chars: 最大字符数
        smart: 使用智能截断
        
    Returns:
        截断后的内容
    """
    cm = ContextManager()
    return cm.truncate_single(content, max_chars, smart_truncate=smart)


def fit_artifacts_for_prompt(
    artifacts: Dict[str, str],
    max_total_chars: int = 16000,
    priorities: Optional[List[str]] = None,
    smart_truncate: bool = True
) -> Dict[str, str]:
    """便捷函数：为 prompt 拟合产物
    
    Args:
        artifacts: 产物字典
        max_total_chars: 最大总字符数
        priorities: 优先级列表
        smart_truncate: 使用智能截断
        
    Returns:
        截断后的产物字典
    """
    cm = ContextManager(max_chars=max_total_chars)
    return cm.fit_artifacts(artifacts, priorities, smart_truncate=smart_truncate)
