"""搜索结果压缩器

使用小模型（如 Qwen3-8B）对搜索结果进行压缩，提取关键信息。
"""

import os
import asyncio
from typing import List, Dict, Any, Optional

from omegaconf import DictConfig

try:
    from ms_agent.utils import get_logger
    logger = get_logger()
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class SearchResultCompressor:
    """搜索结果压缩器
    
    使用 LLM 小模型对搜索结果进行压缩，提取关键信息。
    
    配置示例 (yaml):
    ```yaml
    SEARCH_ENGINE:
      engine: exa
      compressor:
        enabled: true
        model: Qwen/Qwen3-8B  # 使用小模型
        max_tokens: 512
    ```
    """
    
    # 默认配置
    DEFAULT_MODEL = "Qwen/Qwen3-8B"
    DEFAULT_MAX_TOKENS = 512
    DEFAULT_BASE_URL = "https://api-inference.modelscope.cn/v1"
    
    # 压缩提示词模板
    COMPRESS_PROMPT = """你是一个信息提取专家。请从以下搜索结果中提取与用户查询最相关的关键信息。

用户查询: {query}

搜索结果:
{search_results}

请按以下格式输出压缩后的关键信息（每条不超过100字）:
1. [标题] 关键要点
2. [标题] 关键要点
...

要求:
- 只保留与查询直接相关的信息
- 去除冗余和重复内容
- 保留关键数据、最佳实践、技术细节
- 输出简洁明了，便于 LLM 理解"""

    def __init__(self, config: Optional[DictConfig] = None):
        """初始化压缩器
        
        Args:
            config: 压缩器配置，包含 model, max_tokens, api_key 等
        """
        self.config = config or {}
        
        # 从配置或环境变量获取参数
        self.model = getattr(config, 'model', None) or os.getenv('COMPRESSOR_MODEL') or self.DEFAULT_MODEL
        self.max_tokens = getattr(config, 'max_tokens', None) or self.DEFAULT_MAX_TOKENS
        self.api_key = getattr(config, 'api_key', None) or os.getenv('MODELSCOPE_API_KEY')
        self.base_url = getattr(config, 'base_url', None) or os.getenv('MODELSCOPE_BASE_URL') or self.DEFAULT_BASE_URL
        
        self._client = None
        self._initialized = False
    
    def _init_client(self):
        """懒加载初始化 OpenAI 客户端"""
        if self._initialized:
            return
        
        if not self.api_key:
            logger.warning("[SearchCompressor] 未配置 API Key，压缩功能不可用")
            return
        
        try:
            from openai import OpenAI
            
            # 确保 base_url 以 /v1 结尾
            base_url = self.base_url
            if base_url and not base_url.endswith('/v1'):
                base_url = base_url.rstrip('/') + '/v1'
            
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=base_url
            )
            self._initialized = True
            logger.info(f"[SearchCompressor] 初始化成功: model={self.model}")
            
        except ImportError:
            logger.error("[SearchCompressor] openai 库未安装")
        except Exception as e:
            logger.error(f"[SearchCompressor] 初始化失败: {e}")
    
    async def compress(
        self,
        query: str,
        results: List[Dict[str, Any]],
    ) -> str:
        """压缩搜索结果
        
        Args:
            query: 用户的搜索查询
            results: 搜索结果列表
            
        Returns:
            压缩后的关键信息字符串
        """
        self._init_client()
        
        if not self._client:
            logger.warning("[SearchCompressor] 客户端未初始化，返回原始结果")
            return self._format_raw_results(results)
        
        # 格式化搜索结果
        search_results_text = self._format_results_for_compression(results)
        
        # 构建提示词
        prompt = self.COMPRESS_PROMPT.format(
            query=query,
            search_results=search_results_text
        )
        
        try:
            # 使用线程池执行同步的 OpenAI 调用
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=self.max_tokens,
                    temperature=0.1,  # 低温度，更确定性的输出
                )
            )
            
            compressed = response.choices[0].message.content.strip()
            
            # 计算压缩比
            original_len = len(search_results_text)
            compressed_len = len(compressed)
            ratio = (1 - compressed_len / original_len) * 100 if original_len > 0 else 0
            
            logger.info(f"[SearchCompressor] 压缩完成: {original_len} -> {compressed_len} 字符 (压缩 {ratio:.1f}%)")
            
            return compressed
            
        except Exception as e:
            logger.error(f"[SearchCompressor] 压缩失败: {e}")
            # 失败时返回原始格式化结果
            return self._format_raw_results(results)
    
    def _format_results_for_compression(self, results: List[Dict[str, Any]]) -> str:
        """格式化搜索结果用于压缩"""
        formatted = []
        for i, result in enumerate(results, 1):
            title = result.get('title', 'N/A')
            snippet = result.get('snippet', '')
            url = result.get('url', '')
            
            formatted.append(f"[{i}] {title}")
            if snippet:
                formatted.append(f"    摘要: {snippet}")
            if url:
                formatted.append(f"    来源: {url}")
            formatted.append("")
        
        return "\n".join(formatted)
    
    def _format_raw_results(self, results: List[Dict[str, Any]]) -> str:
        """格式化原始结果（压缩失败时使用）"""
        formatted = []
        for i, result in enumerate(results, 1):
            title = result.get('title', 'N/A')
            snippet = result.get('snippet', '')[:200]  # 截断
            formatted.append(f"{i}. [{title}] {snippet}")
        return "\n".join(formatted)


def create_compressor(config: Optional[DictConfig] = None) -> Optional[SearchResultCompressor]:
    """创建压缩器实例
    
    Args:
        config: 压缩器配置
        
    Returns:
        压缩器实例，如果未启用则返回 None
    """
    if config is None:
        return None
    
    # 检查是否启用压缩
    enabled = getattr(config, 'enabled', False)
    if not enabled:
        return None
    
    return SearchResultCompressor(config)

