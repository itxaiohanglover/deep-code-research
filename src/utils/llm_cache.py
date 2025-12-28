"""LLM 调用缓存模块

解决问题：
- 相同 prompt 重复调用 LLM 浪费 Token
- 迭代开发时效率低下
- 调试时需要频繁重跑

设计原则：
1. 基于 prompt + model 的 hash 进行缓存
2. 支持缓存过期和手动清理
3. 支持禁用缓存（调试模式）
4. 线程安全
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional, Dict, Any, Callable, Awaitable
from threading import Lock
from dataclasses import dataclass, asdict

from ms_agent.utils import get_logger

logger = get_logger()


@dataclass
class CacheEntry:
    """缓存条目"""
    content: str
    model: str
    prompt_hash: str
    created_at: float
    ttl: int  # 生存时间（秒），0 表示永不过期
    
    def is_expired(self) -> bool:
        """检查是否过期"""
        if self.ttl == 0:
            return False
        return time.time() - self.created_at > self.ttl


class LLMCache:
    """LLM 调用缓存
    
    使用示例：
        cache = LLMCache(cache_dir=Path("output/.llm_cache"))
        
        # 方式1：手动使用
        result = cache.get(prompt, model)
        if result is None:
            result = await llm_call(prompt)
            cache.set(prompt, model, result)
        
        # 方式2：装饰器模式（推荐）
        @cache.cached(model="qwen")
        async def my_llm_call(prompt: str) -> str:
            return await actual_llm_call(prompt)
    """
    
    # 默认缓存目录
    DEFAULT_CACHE_DIR = Path("output/.llm_cache")
    
    # 默认 TTL（秒），0 表示永不过期
    DEFAULT_TTL = 0
    
    # 单例实例
    _instance: Optional['LLMCache'] = None
    _lock = Lock()
    
    def __new__(cls, *args, **kwargs):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        ttl: int = DEFAULT_TTL,
        enabled: bool = True,
    ):
        """初始化缓存
        
        Args:
            cache_dir: 缓存目录
            ttl: 缓存过期时间（秒），0 表示永不过期
            enabled: 是否启用缓存
        """
        if self._initialized:
            return
            
        self._initialized = True
        
        # 从环境变量获取缓存目录
        env_cache_dir = os.getenv("LLM_CACHE_DIR")
        if env_cache_dir:
            self.cache_dir = Path(env_cache_dir)
        elif cache_dir:
            self.cache_dir = cache_dir
        else:
            # 使用 OUTPUT_DIR 下的 .llm_cache
            output_dir = os.getenv("OUTPUT_DIR", "output")
            self.cache_dir = Path(output_dir) / ".llm_cache"
        
        self.ttl = ttl
        self.enabled = enabled
        
        # 从环境变量控制缓存开关
        env_enabled = os.getenv("LLM_CACHE_ENABLED", "true").lower()
        if env_enabled in ("false", "0", "no"):
            self.enabled = False
        
        # 确保缓存目录存在
        if self.enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"[LLMCache] 初始化完成: cache_dir={self.cache_dir}, enabled={self.enabled}")
        
        # 内存缓存（加速频繁访问）
        self._memory_cache: Dict[str, CacheEntry] = {}
        self._memory_lock = Lock()
        
        # 统计信息
        self._stats = {
            "hits": 0,
            "misses": 0,
            "saves": 0,
        }
    
    def _hash_prompt(self, prompt: str, model: str) -> str:
        """生成 prompt 的 hash 值
        
        Args:
            prompt: 提示词
            model: 模型名称
            
        Returns:
            16 字符的 hash 值
            
        注意：
            - 缓存 key 包含 session_id，确保不同项目的缓存隔离
            - 避免不同用户需求共用同一缓存导致输出错误
        """
        # 规范化 prompt（去除首尾空白、统一换行符）
        normalized_prompt = prompt.strip().replace('\r\n', '\n')
        
        # 获取 session_id（用于隔离不同项目的缓存）
        session_id = os.getenv("SESSION_ID", "default")
        
        # 组合 session_id + model + prompt
        content = f"{session_id}:::{model}:::{normalized_prompt}"
        
        # 生成 SHA256 hash
        return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]
    
    def _get_cache_path(self, prompt_hash: str) -> Path:
        """获取缓存文件路径
        
        使用两级目录结构避免单目录文件过多：
        .llm_cache/ab/abcdef1234567890.json
        """
        return self.cache_dir / prompt_hash[:2] / f"{prompt_hash}.json"
    
    def get(self, prompt: str, model: str) -> Optional[str]:
        """从缓存获取结果
        
        Args:
            prompt: 提示词
            model: 模型名称
            
        Returns:
            缓存的结果，如果未命中返回 None
        """
        if not self.enabled:
            return None
        
        prompt_hash = self._hash_prompt(prompt, model)
        
        # 1. 先检查内存缓存
        with self._memory_lock:
            if prompt_hash in self._memory_cache:
                entry = self._memory_cache[prompt_hash]
                if not entry.is_expired():
                    self._stats["hits"] += 1
                    logger.debug(f"[LLMCache] 内存缓存命中: {prompt_hash}")
                    return entry.content
                else:
                    # 过期，删除
                    del self._memory_cache[prompt_hash]
        
        # 2. 检查文件缓存
        cache_path = self._get_cache_path(prompt_hash)
        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text(encoding='utf-8'))
                entry = CacheEntry(**data)
                
                if entry.is_expired():
                    # 过期，删除文件
                    cache_path.unlink()
                    self._stats["misses"] += 1
                    return None
                
                # 加载到内存缓存
                with self._memory_lock:
                    self._memory_cache[prompt_hash] = entry
                
                self._stats["hits"] += 1
                logger.debug(f"[LLMCache] 文件缓存命中: {prompt_hash}")
                return entry.content
                
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                logger.warning(f"[LLMCache] 读取缓存失败: {cache_path}, error: {e}")
                # 损坏的缓存文件，删除
                cache_path.unlink(missing_ok=True)
        
        self._stats["misses"] += 1
        return None
    
    def set(
        self,
        prompt: str,
        model: str,
        content: str,
        ttl: Optional[int] = None,
    ) -> None:
        """保存结果到缓存
        
        Args:
            prompt: 提示词
            model: 模型名称
            content: 结果内容
            ttl: 缓存过期时间（秒），None 使用默认值
        """
        if not self.enabled:
            return
        
        if not content or not content.strip():
            logger.debug("[LLMCache] 跳过空内容缓存")
            return
        
        prompt_hash = self._hash_prompt(prompt, model)
        entry = CacheEntry(
            content=content,
            model=model,
            prompt_hash=prompt_hash,
            created_at=time.time(),
            ttl=ttl if ttl is not None else self.ttl,
        )
        
        # 1. 保存到内存缓存
        with self._memory_lock:
            self._memory_cache[prompt_hash] = entry
        
        # 2. 保存到文件缓存
        cache_path = self._get_cache_path(prompt_hash)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            cache_path.write_text(
                json.dumps(asdict(entry), ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
            self._stats["saves"] += 1
            logger.debug(f"[LLMCache] 已缓存: {prompt_hash} ({len(content)} 字符)")
        except Exception as e:
            logger.warning(f"[LLMCache] 保存缓存失败: {cache_path}, error: {e}")
    
    async def get_or_call(
        self,
        prompt: str,
        model: str,
        llm_fn: Callable[[str], Awaitable[str]],
        ttl: Optional[int] = None,
    ) -> str:
        """从缓存获取或调用 LLM
        
        这是推荐的使用方式，自动处理缓存逻辑。
        
        Args:
            prompt: 提示词
            model: 模型名称
            llm_fn: LLM 调用函数
            ttl: 缓存过期时间
            
        Returns:
            LLM 结果
        """
        # 尝试从缓存获取
        cached = self.get(prompt, model)
        if cached is not None:
            logger.info(f"[LLMCache] ✅ 缓存命中 (hash={self._hash_prompt(prompt, model)[:8]}...)")
            return cached
        
        # 调用 LLM
        logger.debug(f"[LLMCache] 缓存未命中，调用 LLM")
        result = await llm_fn(prompt)
        
        # 保存到缓存
        self.set(prompt, model, result, ttl)
        
        return result
    
    def invalidate(self, prompt: str, model: str) -> bool:
        """使特定缓存失效
        
        Args:
            prompt: 提示词
            model: 模型名称
            
        Returns:
            是否成功删除
        """
        prompt_hash = self._hash_prompt(prompt, model)
        
        # 从内存缓存删除
        with self._memory_lock:
            self._memory_cache.pop(prompt_hash, None)
        
        # 从文件缓存删除
        cache_path = self._get_cache_path(prompt_hash)
        if cache_path.exists():
            cache_path.unlink()
            logger.debug(f"[LLMCache] 已删除缓存: {prompt_hash}")
            return True
        
        return False
    
    def clear(self) -> int:
        """清空所有缓存
        
        Returns:
            删除的缓存条目数
        """
        count = 0
        
        # 清空内存缓存
        with self._memory_lock:
            count += len(self._memory_cache)
            self._memory_cache.clear()
        
        # 清空文件缓存
        if self.cache_dir.exists():
            for cache_file in self.cache_dir.rglob("*.json"):
                cache_file.unlink()
                count += 1
        
        logger.info(f"[LLMCache] 已清空 {count} 个缓存条目")
        return count
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        hit_rate = 0
        total = self._stats["hits"] + self._stats["misses"]
        if total > 0:
            hit_rate = self._stats["hits"] / total * 100
        
        return {
            **self._stats,
            "hit_rate": f"{hit_rate:.1f}%",
            "memory_entries": len(self._memory_cache),
            "enabled": self.enabled,
            "cache_dir": str(self.cache_dir),
        }
    
    def cleanup_expired(self) -> int:
        """清理过期的缓存条目
        
        Returns:
            删除的条目数
        """
        count = 0
        
        # 清理内存缓存
        with self._memory_lock:
            expired_keys = [
                k for k, v in self._memory_cache.items()
                if v.is_expired()
            ]
            for k in expired_keys:
                del self._memory_cache[k]
                count += 1
        
        # 清理文件缓存
        if self.cache_dir.exists():
            for cache_file in self.cache_dir.rglob("*.json"):
                try:
                    data = json.loads(cache_file.read_text(encoding='utf-8'))
                    entry = CacheEntry(**data)
                    if entry.is_expired():
                        cache_file.unlink()
                        count += 1
                except Exception:
                    # 损坏的文件也删除
                    cache_file.unlink()
                    count += 1
        
        if count > 0:
            logger.info(f"[LLMCache] 清理了 {count} 个过期缓存")
        
        return count


# 全局单例实例
llm_cache = LLMCache()


# 便捷函数
def get_llm_cache() -> LLMCache:
    """获取全局 LLM 缓存实例"""
    return llm_cache


def cache_llm_call(prompt: str, model: str, result: str) -> None:
    """便捷函数：缓存 LLM 调用结果"""
    llm_cache.set(prompt, model, result)


def get_cached_llm_result(prompt: str, model: str) -> Optional[str]:
    """便捷函数：获取缓存的 LLM 结果"""
    return llm_cache.get(prompt, model)

