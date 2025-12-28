"""共享 RAG 服务 - 解决每个 Agent 重复初始化 RAG 的问题

设计原则：
1. 单例模式：整个 workflow 共享一个 RAG 实例
2. 懒加载：仅在首次使用时初始化
3. 索引持久化：避免重复构建索引
4. 支持 Reranker 重排序提升检索质量（Phase 2）
"""

from __future__ import annotations

import os
from typing import Optional, List, Dict, Any
from pathlib import Path

from src.utils import logger
from src.tools.rag.reranker import RAGReranker, rag_reranker


class SharedRAGService:
    """共享 RAG 服务（单例）
    
    解决的问题：
    1. 每个 Agent 单独初始化 RAG 导致的性能问题
    2. 长期知识库每次都重新加载的问题
    3. 用户上传文档在不同 Agent 间不共享的问题
    """
    
    _instance: Optional['SharedRAGService'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._initialized = True
        self.rag = None
        self._config = None
        self._knowledge_loaded = False
        self._user_docs_loaded = False
        
    async def initialize(self, config) -> None:
        """初始化 RAG（仅首次调用生效）"""
        if self.rag is not None:
            return
            
        self._config = config
        rag_config = getattr(config, 'rag', None)
        
        if rag_config is None:
            logger.debug("[SharedRAG] 配置中未启用 RAG")
            return
            
        try:
            from ms_agent.rag.utils import rag_mapping
            
            rag_name = rag_config.name
            if rag_name not in rag_mapping:
                logger.error(f"[SharedRAG] 不支持的 RAG 类型: {rag_name}")
                return
                
            self.rag = rag_mapping[rag_name](config)
            logger.info(f"[SharedRAG] ✅ RAG 服务初始化成功 ({rag_name})")
            
        except Exception as e:
            logger.error(f"[SharedRAG] RAG 初始化失败: {e}")
            self.rag = None
    
    async def load_knowledge_base(self, config) -> int:
        """加载长期知识库（仅首次调用生效）
        
        支持配置格式：
        knowledge_sources:
          persistent:
            enabled: true
            base_path: ${oc.env:OUTPUT_DIR}/knowledge_base  # 知识库根目录（可选）
            paths:
              - tech_patterns      # 相对于 base_path 的子目录
              - best_practices
        
        Returns:
            加载的文档数量
        """
        if self._knowledge_loaded:
            logger.debug("[SharedRAG] 知识库已加载，跳过")
            return 0
            
        await self.initialize(config)
        
        if not self.rag:
            return 0
            
        rag_config = getattr(config, 'rag', None)
        knowledge_sources = getattr(rag_config, 'knowledge_sources', None) if rag_config else None
        
        if not knowledge_sources:
            return 0
            
        persistent_config = getattr(knowledge_sources, 'persistent', None)
        if not persistent_config or not getattr(persistent_config, 'enabled', False):
            return 0
        
        # 获取知识库根目录（base_path），可选配置
        base_path = getattr(persistent_config, 'base_path', None)
        if base_path and not os.path.isabs(base_path):
            base_path = os.path.join(os.getcwd(), base_path)
            
        paths = getattr(persistent_config, 'paths', []) or []
        docs_to_add = []
        
        for kb_path in paths:
            # 如果配置了 base_path，则将 paths 视为相对路径
            if base_path:
                full_path = os.path.join(base_path, kb_path)
            else:
                # 向后兼容：如果没有 base_path，paths 视为完整路径
                full_path = kb_path
                
            if not os.path.isabs(full_path):
                full_path = os.path.join(os.getcwd(), full_path)
                
            if not os.path.exists(full_path):
                logger.debug(f"[SharedRAG] 知识库路径不存在: {full_path}")
                continue
                
            try:
                if os.path.isdir(full_path):
                    for root, _, files in os.walk(full_path):
                        for file in files:
                            if file.endswith(('.md', '.txt', '.rst', '.json', '.yaml', '.yml')):
                                file_path = os.path.join(root, file)
                                with open(file_path, 'r', encoding='utf-8') as f:
                                    content = f.read()
                                if content.strip():
                                    docs_to_add.append(f"[知识库] {file_path}\n{content}")
                elif os.path.isfile(full_path):
                    with open(full_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    if content.strip():
                        docs_to_add.append(f"[知识库] {full_path}\n{content}")
            except Exception as e:
                # 单个文件读取失败是可恢复错误，继续处理其他文件
                logger.warning(f"[SharedRAG] 读取 {full_path} 失败（可恢复，继续处理其他文件）: {e}")
        
        if docs_to_add:
            try:
                await self.rag.add_documents(docs_to_add)
                self._knowledge_loaded = True
                logger.info(f"[SharedRAG] 📚 长期知识库加载完成: {len(docs_to_add)} 个文档 (base_path: {base_path})")
            except Exception as e:
                # 添加文档失败是可恢复错误，RAG 可以继续工作但没有知识库增强
                logger.error(f"[SharedRAG] 添加知识库文档失败（可恢复）: {e}")
        else:
            logger.info(f"[SharedRAG] ⚠️ 知识库目录为空或不存在: {base_path}")
                
        return len(docs_to_add)
    
    async def add_user_documents(self, documents: List) -> int:
        """添加用户上传的文档
        
        Args:
            documents: ParsedDocument 对象列表或字典列表
            
        Returns:
            添加的文档数量
        """
        if not self.rag or not documents:
            return 0
            
        docs_to_add = []
        for doc in documents:
            # 支持 ParsedDocument 对象和字典两种格式
            if hasattr(doc, 'filename'):
                # ParsedDocument 对象
                filename = doc.filename
                content = doc.content
            else:
                # 字典格式
                filename = doc.get('filename', 'unknown')
                content = doc.get('content', '')
            if content.strip():
                docs_to_add.append(f"[用户文档] {filename}\n{content}")
        
        if docs_to_add:
            try:
                await self.rag.add_documents(docs_to_add)
                self._user_docs_loaded = True
                logger.info(f"[SharedRAG] 📄 用户文档已添加: {len(docs_to_add)} 个")
            except Exception as e:
                logger.error(f"[SharedRAG] 添加用户文档失败: {e}")
                return 0
                
        return len(docs_to_add)
    
    async def retrieve(
        self,
        query: str,
        limit: int = 5,
        score_threshold: float = 0.0,
        use_rerank: bool = False,
    ) -> List[Dict[str, Any]]:
        """检索相关文档
        
        Args:
            query: 检索查询
            limit: 返回结果数量
            score_threshold: 相似度阈值
            use_rerank: 是否使用重排序（默认 False，保持向后兼容）
            
        Returns:
            检索结果列表
        """
        if not self.rag:
            return []
            
        try:
            # 如果启用重排序，召回更多候选
            retrieve_limit = limit * 3 if use_rerank else limit
            
            results = await self.rag.retrieve(
                query=query,
                limit=retrieve_limit,
                score_threshold=score_threshold
            )
            
            if not results:
                return []
            
            # 重排序
            if use_rerank and len(results) > limit:
                results = rag_reranker.rerank(query, results, top_k=limit)
                logger.debug(f"[SharedRAG] 重排序完成: {retrieve_limit} -> {len(results)} 结果")
            
            return results or []
        except Exception as e:
            logger.warning(f"[SharedRAG] 检索失败: {e}")
            return []
    
    async def retrieve_with_expansion(
        self,
        query: str,
        limit: int = 5,
        expansion_limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """带查询扩展的检索（推荐用于复杂查询）
        
        步骤：
        1. 扩展查询为多个变体
        2. 对每个变体进行检索
        3. 合并去重
        4. 重排序返回
        
        Args:
            query: 原始查询
            limit: 最终返回数量
            expansion_limit: 每个扩展查询的检索数量
            
        Returns:
            检索结果列表
        """
        if not self.rag:
            return []
        
        try:
            # 使用 RAGReranker 的扩展检索
            results = await rag_reranker.rerank_with_expansion(
                query=query,
                retriever=self,  # 传入自身作为检索器
                top_k=limit,
                expansion_limit=expansion_limit,
            )
            
            logger.info(f"[SharedRAG] 扩展检索完成: {len(results)} 结果")
            return results
            
        except Exception as e:
            logger.warning(f"[SharedRAG] 扩展检索失败: {e}")
            # 降级到普通检索
            return await self.retrieve(query, limit=limit, use_rerank=True)
    
    def get_status(self) -> Dict[str, Any]:
        """获取 RAG 服务状态"""
        status = {
            "initialized": self.rag is not None,
            "knowledge_loaded": self._knowledge_loaded,
            "user_docs_loaded": self._user_docs_loaded,
        }
        
        if self.rag and hasattr(self.rag, 'get_index_info'):
            status["index_info"] = self.rag.get_index_info()
            
        return status
    
    def reset(self):
        """重置服务状态（用于新的 workflow）"""
        self.rag = None
        self._config = None
        self._knowledge_loaded = False
        self._user_docs_loaded = False
        logger.debug("[SharedRAG] 服务已重置")


# 全局单例
shared_rag_service = SharedRAGService()
