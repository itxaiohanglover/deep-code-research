"""Web 搜索工具

基于 ms-agent ToolBase 实现的 Web 搜索工具，支持 EXA 和 SERPAPI。
支持使用小模型压缩搜索结果，减少上下文长度。
"""

import os
from typing import Optional, List, Dict, Any

from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils import get_logger
from omegaconf import DictConfig

from src.tools.search.engine import create_search_engine, SearchEngine
from src.tools.search.compressor import create_compressor, SearchResultCompressor

logger = get_logger()


class WebSearchTool(ToolBase):
    """Web 搜索工具
    
    功能：
    - 支持使用 EXA 或 SERPAPI 进行 Web 搜索
    - 返回搜索结果（标题、URL、摘要等）
    - 可在 Agent 配置中通过 plugins 注册使用
    
    配置：
    - 在 src/config/search/conf.yaml 中配置搜索引擎类型和 API Key
    - 或在环境变量中设置 EXA_API_KEY 或 SERPAPI_API_KEY
    
    使用示例（由 LLM 通过 tool-calling 发起）：
    - 搜索技术信息：query="Python FastAPI 最佳实践", num_results=5
    - 搜索市场数据：query="2024年 AI 编程工具市场趋势", num_results=3
    """
    
    def __init__(self, config: DictConfig, **kwargs):
        super(WebSearchTool, self).__init__(config)
        
        # 支持通过 config.tools.web_search.exclude_functions 屏蔽部分工具
        self.exclude_func(getattr(config.tools, "web_search", None))
        
        # 初始化搜索引擎
        self._search_engine: Optional[SearchEngine] = None
        
        # 初始化搜索结果压缩器（可选）
        self._compressor: Optional[SearchResultCompressor] = None
    
    async def connect(self):
        """初始化搜索引擎和压缩器（懒加载）
        
        与 FileSystemTool 保持接口一致：agent 初始化时会调用一次 connect()。
        """
        if self._search_engine is None:
            try:
                # 从配置中获取搜索配置，或使用默认配置
                search_config = getattr(self.config, "search", None)
                if search_config is None:
                    # 尝试从全局配置加载
                    from omegaconf import OmegaConf
                    from pathlib import Path
                    
                    # 尝试从项目根目录加载配置文件
                    project_root = Path(__file__).parent.parent.parent.parent
                    config_path = project_root / "src" / "config" / "search" / "conf.yaml"
                    
                    if config_path.exists():
                        global_config = OmegaConf.load(config_path)
                        search_config = global_config.get("SEARCH_ENGINE", {})
                    else:
                        # 使用环境变量
                        search_config = {}
                
                self._search_engine = create_search_engine(search_config)
                logger.info(f"[WebSearchTool] 搜索引擎已初始化: {type(self._search_engine).__name__}")
                
                # 初始化压缩器（如果配置了）
                compressor_config = getattr(search_config, 'compressor', None)
                if compressor_config:
                    self._compressor = create_compressor(compressor_config)
                    if self._compressor:
                        logger.info(f"[WebSearchTool] 搜索结果压缩器已启用: model={self._compressor.model}")
                
            except Exception as e:
                logger.error(f"[WebSearchTool] 初始化搜索引擎失败: {e}")
                raise
    
    async def cleanup(self):
        """清理资源"""
        self._search_engine = None
    
    async def get_tools(self):
        """返回工具声明，供 LLM 调用"""
        tools = {
            "web_search": [
                Tool(
                    tool_name="search_web",
                    server_name="web_search",
                    description=(
                        "Search the web for information using EXA or SERPAPI. "
                        "Use this tool when you need to find current information, "
                        "technical documentation, market data, or any information "
                        "that requires real-time web search.\n\n"
                        "Typical usage:\n"
                        "- Search for technical best practices: query='Python FastAPI best practices', num_results=5\n"
                        "- Search for market trends: query='2024 AI coding tools market trends', num_results=3\n"
                        "- Search for documentation: query='React hooks documentation', num_results=5\n\n"
                        "The tool returns a list of search results, each containing:\n"
                        "- title: The title of the search result\n"
                        "- url: The URL of the result\n"
                        "- snippet: A brief summary or excerpt from the result\n"
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": (
                                    "The search query string. "
                                    "Be specific and include relevant keywords. "
                                    "Examples: 'Python async programming best practices', "
                                    "'React state management patterns 2024'"
                                ),
                            },
                            "num_results": {
                                "type": "integer",
                                "description": (
                                    "Number of search results to return. "
                                    "Default is 5. Maximum recommended is 10."
                                ),
                                "default": 5,
                                "minimum": 1,
                                "maximum": 10,
                            },
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                ),
            ]
        }
        
        return {
            "web_search": [
                t
                for t in tools["web_search"]
                if t["tool_name"] not in self.exclude_functions
            ]
        }
    
    async def call_tool(
        self, server_name: str, *, tool_name: str, tool_args: dict
    ) -> str:
        """工具调用入口"""
        if server_name != "web_search":
            raise ValueError(f"Unsupported server_name: {server_name}")
        
        return await getattr(self, tool_name)(**tool_args)
    
    async def search_web(
        self,
        query: str,
        num_results: int = 5,
    ) -> str:
        """执行 Web 搜索
        
        Args:
            query: 搜索查询字符串
            num_results: 返回结果数量（默认 5，最大 10）
            
        Returns:
            格式化的搜索结果字符串（如果启用压缩器则返回压缩后的结果）
        """
        await self.connect()
        
        if self._search_engine is None:
            return "[WebSearchTool] 搜索引擎未初始化，无法执行搜索"
        
        # 限制结果数量
        num_results = min(max(1, num_results), 10)
        
        try:
            logger.info(f"[WebSearchTool] 执行搜索: query='{query}', num_results={num_results}")
            results = await self._search_engine.search(query, num_results=num_results)
            
            if not results:
                return f"未找到与 '{query}' 相关的搜索结果。"
            
            # 如果启用了压缩器，使用小模型压缩结果
            if self._compressor:
                logger.info(f"[WebSearchTool] 使用压缩器处理 {len(results)} 个搜索结果")
                compressed = await self._compressor.compress(query, results)
                return f"搜索查询: {query}\n压缩后的关键信息:\n\n{compressed}"
            
            # 未启用压缩器时，返回原始格式化结果
            formatted_results = []
            formatted_results.append(f"搜索查询: {query}\n")
            formatted_results.append(f"找到 {len(results)} 个结果:\n")
            formatted_results.append("=" * 60 + "\n")
            
            for i, result in enumerate(results, 1):
                formatted_results.append(f"\n结果 {i}:\n")
                formatted_results.append(f"标题: {result.get('title', 'N/A')}\n")
                formatted_results.append(f"URL: {result.get('url', 'N/A')}\n")
                snippet = result.get('snippet', '')
                if snippet:
                    formatted_results.append(f"摘要: {snippet}\n")
                if result.get('published_date'):
                    formatted_results.append(f"发布日期: {result.get('published_date')}\n")
                formatted_results.append("-" * 60 + "\n")
            
            return "".join(formatted_results)
            
        except Exception as e:
            error_msg = f"[WebSearchTool] 搜索失败: {e}"
            logger.error(error_msg)
            return error_msg
