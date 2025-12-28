"""搜索引擎封装

支持 EXA 和 SERPAPI 两种搜索引擎。
"""

import os
from typing import List, Dict, Any, Optional
from omegaconf import DictConfig

from ms_agent.utils import get_logger

logger = get_logger()


class SearchEngine:
    """搜索引擎基类"""
    
    def __init__(self, config: DictConfig):
        self.config = config
    
    async def search(self, query: str, num_results: int = 5) -> List[Dict[str, Any]]:
        """执行搜索
        
        Args:
            query: 搜索查询
            num_results: 返回结果数量
            
        Returns:
            搜索结果列表，每个结果包含 title, url, snippet 等字段
        """
        raise NotImplementedError


class ExaSearchEngine(SearchEngine):
    """EXA 搜索引擎"""
    
    def __init__(self, config: DictConfig):
        super().__init__(config)
        api_key = config.get("exa_api_key") or os.getenv("EXA_API_KEY")
        if not api_key:
            raise ValueError("EXA_API_KEY 未配置，请在环境变量或配置文件中设置")
        
        try:
            from exa_py import Exa
            self.client = Exa(api_key=api_key)
        except ImportError:
            raise ImportError("请安装 exa-py: pip install exa-py")
    
    # 最大 snippet 长度（字符数），避免上下文过长
    MAX_SNIPPET_LENGTH = 500
    
    async def search(self, query: str, num_results: int = 5) -> List[Dict[str, Any]]:
        """使用 EXA 执行搜索"""
        try:
            # EXA 的 search 方法是同步的，需要在异步上下文中运行
            import asyncio
            loop = asyncio.get_event_loop()
            
            # 使用基本的 search 方法，不获取内容（避免上下文爆炸）
            response = await loop.run_in_executor(
                None,
                lambda: self.client.search(
                    query=query,
                    num_results=num_results,
                    type="neural",  # 使用神经搜索
                )
            )
            
            results = []
            for result in response.results:
                # 安全地访问结果属性
                title = getattr(result, "title", None) or ""
                url = getattr(result, "url", None) or ""
                
                # EXA search 基本模式不返回文本内容，只返回元数据
                # 优先使用 snippet/description，避免使用完整 text
                snippet = ""
                if hasattr(result, "snippet") and result.snippet:
                    snippet = result.snippet
                elif hasattr(result, "description") and result.description:
                    snippet = result.description
                elif hasattr(result, "text") and result.text:
                    # 如果有 text，截取前 500 字符作为摘要
                    snippet = result.text[:self.MAX_SNIPPET_LENGTH]
                
                # 截断 snippet，避免上下文过长
                if len(snippet) > self.MAX_SNIPPET_LENGTH:
                    snippet = snippet[:self.MAX_SNIPPET_LENGTH] + "..."
                
                published_date = getattr(result, "published_date", None)
                
                results.append({
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "published_date": published_date,
                })
            
            if results:
                logger.info(f"[ExaSearch] 搜索结果预览: title={results[0].get('title', '')[:50]}, snippet_len={len(results[0].get('snippet', ''))}")

            return results
        except Exception as e:
            logger.error(f"[ExaSearch] 搜索失败: {e}")
            import traceback
            logger.debug(f"[ExaSearch] 错误详情: {traceback.format_exc()}")
            return []


class SerpApiSearchEngine(SearchEngine):
    """SERPAPI 搜索引擎（Google 搜索）"""
    
    def __init__(self, config: DictConfig):
        super().__init__(config)
        api_key = config.get("serpapi_api_key") or os.getenv("SERPAPI_API_KEY")
        if not api_key:
            raise ValueError("SERPAPI_API_KEY 未配置，请在环境变量或配置文件中设置")
        
        self.api_key = api_key
        self.provider = config.get("provider", "google")
    
    async def search(self, query: str, num_results: int = 5) -> List[Dict[str, Any]]:
        """使用 SERPAPI 执行搜索"""
        try:
            from serpapi import GoogleSearch
            import asyncio
            
            params = {
                "q": query,
                "api_key": self.api_key,
                "num": num_results,
                "hl": "zh-cn",  # 中文结果
            }
            
            # SERPAPI 的搜索是同步的，需要在异步上下文中运行
            loop = asyncio.get_event_loop()
            results_data = await loop.run_in_executor(
                None,
                lambda: GoogleSearch(params).get_dict()
            )
            
            results = []
            organic_results = results_data.get("organic_results", [])
            
            for result in organic_results[:num_results]:
                results.append({
                    "title": result.get("title", ""),
                    "url": result.get("link", ""),
                    "snippet": result.get("snippet", ""),
                    "published_date": None,
                })
            
            logger.info(f"[SerpApiSearch] 搜索结果预览: {results[0]}")
            return results
        except Exception as e:
            logger.error(f"[SerpApiSearch] 搜索失败: {e}")
            import traceback
            logger.debug(f"[SerpApiSearch] 错误详情: {traceback.format_exc()}")
            return []


def create_search_engine(config: Optional[DictConfig] = None) -> SearchEngine:
    """创建搜索引擎实例
    
    Args:
        config: 搜索配置，如果为 None 则从配置文件加载
        
    Returns:
        搜索引擎实例
    """
    if config is None:
        from omegaconf import OmegaConf
        from pathlib import Path
        
        # 尝试从项目根目录加载配置文件
        project_root = Path(__file__).parent.parent.parent.parent
        config_path = project_root / "src" / "config" / "search" / "conf.yaml"
        
        if config_path.exists():
            config = OmegaConf.load(config_path)
            search_config = config.get("SEARCH_ENGINE", {})
        else:
            # 如果配置文件不存在，使用环境变量
            search_config = {}
    else:
        search_config = config
    
    engine_type = search_config.get("engine", "exa").lower()
    
    if engine_type == "exa":
        return ExaSearchEngine(search_config)
    elif engine_type == "serpapi":
        return SerpApiSearchEngine(search_config)
    else:
        raise ValueError(f"不支持的搜索引擎类型: {engine_type}，支持的类型: exa, serpapi")
