"""搜索工具模块

提供 Web 搜索功能，支持多种搜索引擎（EXA、SERPAPI）。
支持搜索结果压缩（使用小模型提取关键信息）。
"""

from src.tools.search.engine import (
    SearchEngine,
    ExaSearchEngine,
    SerpApiSearchEngine,
    create_search_engine,
)
from src.tools.search.service import WebSearchTool
from src.tools.search.compressor import (
    SearchResultCompressor,
    create_compressor,
)

__all__ = [
    "SearchEngine",
    "ExaSearchEngine",
    "SerpApiSearchEngine",
    "create_search_engine",
    "WebSearchTool",
    "SearchResultCompressor",
    "create_compressor",
]
