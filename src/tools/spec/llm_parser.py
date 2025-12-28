"""LLM 后备解析器 - 当规则解析失败时使用 LLM 提取结构化信息

解决问题：
- 正则匹配无法覆盖所有格式变体
- LLM 输出格式略有变化就会解析失败
- 中英文混合格式难以处理

设计原则：
1. 作为规则解析的后备方案
2. 使用 LLM 进行结构化提取
3. 输出标准化的 JSON 格式
4. 支持缓存避免重复调用
"""

from __future__ import annotations

import json
import os
from typing import List, Dict, Any, Optional

from ms_agent.utils import get_logger

logger = get_logger()


# 任务提取 Prompt
TASK_EXTRACTION_PROMPT = """请从以下 Markdown 内容中提取任务列表。

## 任务格式说明
任务可能以以下格式出现：
- **Task-X.Y: 任务名称**
- ### Task-X.Y: 任务名称
- #### Task-X.Y 任务名称
- ## 任务 N: 任务名称

## 要提取的信息
对于每个任务，提取：
1. id: 任务 ID（如 Task-1.1）
2. description: 任务描述/目标
3. dependencies: 依赖的任务 ID 列表

## 输出格式
严格按以下 JSON 格式输出，不要包含其他内容：

```json
[
  {
    "id": "Task-1.1",
    "description": "任务描述",
    "dependencies": []
  },
  {
    "id": "Task-1.2",
    "description": "任务描述",
    "dependencies": ["Task-1.1"]
  }
]
```

## 内容

{content}

## 输出
请输出 JSON 格式的任务列表：
"""


# 模块提取 Prompt
MODULE_EXTRACTION_PROMPT = """请从以下 Markdown 内容中提取模块/章节列表。

## 模块格式说明
模块可能以以下格式出现：
- ## N. 模块名称
- ## 功能模块 N: 模块名称
- ### US-XXX: 用户故事

## 要提取的信息
对于每个模块，提取：
1. id: 模块 ID（如 module_1）
2. name: 模块名称

## 输出格式
严格按以下 JSON 格式输出，不要包含其他内容：

```json
[
  {
    "id": "module_1",
    "name": "模块名称"
  }
]
```

## 内容

{content}

## 输出
请输出 JSON 格式的模块列表：
"""


class LLMSpecParser:
    """LLM 后备解析器
    
    当规则解析失败时，使用 LLM 提取结构化信息。
    
    使用示例：
        parser = LLMSpecParser()
        
        # 提取任务
        tasks = await parser.extract_tasks(tasks_content)
        
        # 提取模块
        modules = await parser.extract_modules(spec_content)
    """
    
    def __init__(self, use_cache: bool = True):
        """初始化
        
        Args:
            use_cache: 是否使用缓存（默认 True）
        """
        self.use_cache = use_cache
        self._llm = None
    
    async def _get_llm(self):
        """懒加载 LLM 实例"""
        if self._llm is None:
            try:
                from ms_agent.llm import create_llm
                
                # 使用轻量级模型
                model = os.getenv("SPEC_PARSER_MODEL", "Qwen/Qwen3-8B")
                base_url = os.getenv("MODELSCOPE_BASE_URL")
                api_key = os.getenv("MODELSCOPE_API_KEY")
                
                self._llm = create_llm(
                    service="modelscope",
                    model=model,
                    modelscope_base_url=base_url,
                    modelscope_api_key=api_key,
                )
                logger.debug(f"[LLMSpecParser] 初始化 LLM: {model}")
            except Exception as e:
                logger.error(f"[LLMSpecParser] 初始化 LLM 失败: {e}")
                return None
        
        return self._llm
    
    async def extract_tasks(self, content: str) -> List[Dict[str, Any]]:
        """使用 LLM 提取任务列表
        
        Args:
            content: tasks.md 内容
            
        Returns:
            任务列表
        """
        if not content or not content.strip():
            return []
        
        # 检查缓存
        if self.use_cache:
            from src.utils.llm_cache import llm_cache
            cache_key = f"spec_tasks:{hash(content[:1000])}"
            cached = llm_cache.get(cache_key, "spec_parser")
            if cached:
                try:
                    return json.loads(cached)
                except json.JSONDecodeError:
                    pass
        
        # 截断过长内容
        max_len = 8000
        if len(content) > max_len:
            content = content[:max_len] + "\n\n... [内容已截断] ..."
        
        # 构建 prompt
        prompt = TASK_EXTRACTION_PROMPT.format(content=content)
        
        try:
            llm = await self._get_llm()
            if not llm:
                logger.warning("[LLMSpecParser] LLM 不可用，跳过任务提取")
                return []
            
            # 调用 LLM
            response = await llm.generate(prompt)
            
            # 解析响应
            tasks = self._parse_json_response(response)
            
            if tasks:
                logger.info(f"[LLMSpecParser] ✅ 提取到 {len(tasks)} 个任务")
                
                # 缓存结果
                if self.use_cache:
                    from src.utils.llm_cache import llm_cache
                    llm_cache.set(cache_key, "spec_parser", json.dumps(tasks, ensure_ascii=False))
                
            return tasks
            
        except Exception as e:
            logger.error(f"[LLMSpecParser] 提取任务失败: {e}")
            return []
    
    async def extract_modules(self, content: str) -> List[Dict[str, Any]]:
        """使用 LLM 提取模块列表
        
        Args:
            content: spec.md 内容
            
        Returns:
            模块列表
        """
        if not content or not content.strip():
            return []
        
        # 检查缓存
        if self.use_cache:
            from src.utils.llm_cache import llm_cache
            cache_key = f"spec_modules:{hash(content[:1000])}"
            cached = llm_cache.get(cache_key, "spec_parser")
            if cached:
                try:
                    return json.loads(cached)
                except json.JSONDecodeError:
                    pass
        
        # 截断过长内容
        max_len = 8000
        if len(content) > max_len:
            content = content[:max_len] + "\n\n... [内容已截断] ..."
        
        # 构建 prompt
        prompt = MODULE_EXTRACTION_PROMPT.format(content=content)
        
        try:
            llm = await self._get_llm()
            if not llm:
                logger.warning("[LLMSpecParser] LLM 不可用，跳过模块提取")
                return []
            
            # 调用 LLM
            response = await llm.generate(prompt)
            
            # 解析响应
            modules = self._parse_json_response(response)
            
            if modules:
                logger.info(f"[LLMSpecParser] ✅ 提取到 {len(modules)} 个模块")
                
                # 缓存结果
                if self.use_cache:
                    from src.utils.llm_cache import llm_cache
                    llm_cache.set(cache_key, "spec_parser", json.dumps(modules, ensure_ascii=False))
                
            return modules
            
        except Exception as e:
            logger.error(f"[LLMSpecParser] 提取模块失败: {e}")
            return []
    
    def _parse_json_response(self, response: str) -> List[Dict[str, Any]]:
        """从 LLM 响应中解析 JSON
        
        Args:
            response: LLM 响应文本
            
        Returns:
            解析后的 JSON 列表
        """
        if not response:
            return []
        
        # 尝试直接解析
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass
        
        # 尝试从代码块中提取
        import re
        
        # 匹配 ```json ... ``` 或 ``` ... ```
        code_block_pattern = r'```(?:json)?\s*\n?(.*?)\n?```'
        matches = re.findall(code_block_pattern, response, re.DOTALL)
        
        for match in matches:
            try:
                result = json.loads(match.strip())
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                continue
        
        # 尝试匹配 [ ... ] 数组
        array_pattern = r'\[\s*\{.*?\}\s*\]'
        array_match = re.search(array_pattern, response, re.DOTALL)
        if array_match:
            try:
                return json.loads(array_match.group())
            except json.JSONDecodeError:
                pass
        
        logger.warning(f"[LLMSpecParser] 无法解析 JSON 响应: {response[:200]}...")
        return []


# 全局实例
llm_spec_parser = LLMSpecParser()

