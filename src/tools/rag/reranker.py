"""RAG Reranker - 提升检索质量

解决问题：
- 简单向量检索的相关性不够
- 检索结果可能包含低质量内容
- 需要更精确的排序

设计原则：
1. 多路召回 + 重排序
2. 支持多种重排序策略
3. 可配置的相似度阈值
4. 支持 Query Expansion
"""

from __future__ import annotations

import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from ms_agent.utils import get_logger

logger = get_logger()


@dataclass
class RerankResult:
    """重排序结果"""
    text: str
    score: float
    original_score: float
    metadata: Dict[str, Any]


class QueryExpander:
    """查询扩展器
    
    将原始查询扩展为多个变体，提升召回率。
    
    扩展策略：
    1. 原始查询
    2. 技术实现角度
    3. 最佳实践角度
    4. 问题解决角度
    """
    
    # 扩展模板
    EXPANSION_TEMPLATES = [
        "{query}",  # 原始查询
        "关于 {query} 的技术实现方案",
        "{query} 的最佳实践和设计模式",
        "如何解决 {query} 相关的问题",
    ]
    
    def __init__(self, max_expansions: int = 3):
        """初始化查询扩展器
        
        Args:
            max_expansions: 最大扩展数量（不包括原始查询）
        """
        self.max_expansions = max_expansions
    
    def expand(self, query: str) -> List[str]:
        """扩展查询
        
        Args:
            query: 原始查询
            
        Returns:
            扩展后的查询列表（包括原始查询）
        """
        if not query or not query.strip():
            return [query] if query else []
        
        # 清理查询
        clean_query = self._clean_query(query)
        
        # 生成扩展查询
        expansions = []
        for template in self.EXPANSION_TEMPLATES[:self.max_expansions + 1]:
            expanded = template.format(query=clean_query)
            if expanded not in expansions:
                expansions.append(expanded)
        
        logger.debug(f"[QueryExpander] 扩展查询: {len(expansions)} 个变体")
        return expansions
    
    def _clean_query(self, query: str) -> str:
        """清理查询文本
        
        Args:
            query: 原始查询
            
        Returns:
            清理后的查询
        """
        # 移除多余空白
        clean = re.sub(r'\s+', ' ', query.strip())
        
        # 截断过长的查询
        max_len = 200
        if len(clean) > max_len:
            clean = clean[:max_len] + "..."
        
        return clean


class SimpleReranker:
    """简单重排序器
    
    基于关键词匹配和位置权重的轻量级重排序。
    不需要额外的模型调用。
    
    评分策略：
    1. 关键词命中数量
    2. 关键词位置权重（标题 > 开头 > 正文）
    3. 原始相似度分数
    """
    
    # 位置权重
    POSITION_WEIGHTS = {
        "title": 3.0,      # 标题中出现
        "first_100": 2.0,  # 前 100 字符
        "first_500": 1.5,  # 前 500 字符
        "body": 1.0,       # 正文
    }
    
    def __init__(
        self,
        keyword_weight: float = 0.4,
        position_weight: float = 0.3,
        original_weight: float = 0.3,
    ):
        """初始化重排序器
        
        Args:
            keyword_weight: 关键词匹配权重
            position_weight: 位置权重
            original_weight: 原始分数权重
        """
        self.keyword_weight = keyword_weight
        self.position_weight = position_weight
        self.original_weight = original_weight
    
    def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int = 5,
    ) -> List[RerankResult]:
        """重排序文档
        
        Args:
            query: 查询文本
            documents: 文档列表，每个文档包含 text, score, metadata
            top_k: 返回的文档数量
            
        Returns:
            重排序后的结果列表
        """
        if not documents:
            return []
        
        # 提取关键词
        keywords = self._extract_keywords(query)
        
        # 计算每个文档的重排序分数
        scored_docs = []
        for doc in documents:
            text = doc.get('text', '')
            original_score = doc.get('score', 0.0)
            metadata = doc.get('metadata', {})
            
            # 计算各项分数
            keyword_score = self._calculate_keyword_score(text, keywords)
            position_score = self._calculate_position_score(text, keywords)
            
            # 综合分数
            final_score = (
                self.keyword_weight * keyword_score +
                self.position_weight * position_score +
                self.original_weight * original_score
            )
            
            scored_docs.append(RerankResult(
                text=text,
                score=final_score,
                original_score=original_score,
                metadata=metadata,
            ))
        
        # 按分数排序
        scored_docs.sort(key=lambda x: x.score, reverse=True)
        
        # 返回 top_k
        result = scored_docs[:top_k]
        
        logger.debug(
            f"[SimpleReranker] 重排序完成: {len(documents)} -> {len(result)}, "
            f"top_score={result[0].score:.3f}" if result else ""
        )
        
        return result
    
    def _extract_keywords(self, query: str) -> List[str]:
        """从查询中提取关键词
        
        Args:
            query: 查询文本
            
        Returns:
            关键词列表
        """
        # 简单分词（空格和标点）
        words = re.split(r'[\s,，。！？、；：""''【】（）\[\]()]+', query)
        
        # 过滤停用词和短词
        stopwords = {'的', '是', '在', '了', '和', '与', '或', '等', '有', '为', '被', '将', '把', '从', '到', '对', '可以', '需要', '应该', '如何', '什么', '怎么', '哪些', '关于', 'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through', 'during', 'before', 'after', 'above', 'below', 'between', 'under', 'again', 'further', 'then', 'once', 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 'just', 'and', 'but', 'if', 'or', 'because', 'until', 'while', 'although', 'though', 'after', 'before', 'when', 'whenever', 'where', 'wherever', 'whether', 'which', 'who', 'whom', 'whose', 'what', 'whatever', 'whichever', 'whoever', 'whomever'}
        
        keywords = [
            w.lower() for w in words 
            if w and len(w) >= 2 and w.lower() not in stopwords
        ]
        
        return keywords
    
    def _calculate_keyword_score(self, text: str, keywords: List[str]) -> float:
        """计算关键词匹配分数
        
        Args:
            text: 文档文本
            keywords: 关键词列表
            
        Returns:
            匹配分数 (0-1)
        """
        if not keywords:
            return 0.0
        
        text_lower = text.lower()
        matched = sum(1 for kw in keywords if kw in text_lower)
        
        return matched / len(keywords)
    
    def _calculate_position_score(self, text: str, keywords: List[str]) -> float:
        """计算位置权重分数
        
        Args:
            text: 文档文本
            keywords: 关键词列表
            
        Returns:
            位置分数 (0-1)
        """
        if not keywords or not text:
            return 0.0
        
        text_lower = text.lower()
        total_weight = 0.0
        max_weight = len(keywords) * self.POSITION_WEIGHTS["title"]
        
        # 尝试提取标题（第一行或 # 开头的行）
        lines = text.split('\n')
        title = ""
        for line in lines[:3]:
            line = line.strip()
            if line.startswith('#'):
                title = line.lstrip('#').strip().lower()
                break
            elif line:
                title = line.lower()
                break
        
        for kw in keywords:
            kw_lower = kw.lower()
            
            # 检查各个位置
            if title and kw_lower in title:
                total_weight += self.POSITION_WEIGHTS["title"]
            elif kw_lower in text_lower[:100]:
                total_weight += self.POSITION_WEIGHTS["first_100"]
            elif kw_lower in text_lower[:500]:
                total_weight += self.POSITION_WEIGHTS["first_500"]
            elif kw_lower in text_lower:
                total_weight += self.POSITION_WEIGHTS["body"]
        
        return total_weight / max_weight if max_weight > 0 else 0.0


class RAGReranker:
    """RAG 重排序器（组合器）
    
    组合 Query Expansion 和 Reranker，提供完整的重排序能力。
    
    使用示例：
        reranker = RAGReranker()
        
        # 直接重排序
        results = reranker.rerank(query, documents)
        
        # 带查询扩展的重排序
        results = reranker.rerank_with_expansion(query, documents, retriever)
    """
    
    def __init__(
        self,
        expander: Optional[QueryExpander] = None,
        reranker: Optional[SimpleReranker] = None,
    ):
        """初始化
        
        Args:
            expander: 查询扩展器（可选）
            reranker: 重排序器（可选）
        """
        self.expander = expander or QueryExpander()
        self.reranker = reranker or SimpleReranker()
    
    def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """重排序文档
        
        Args:
            query: 查询文本
            documents: 文档列表
            top_k: 返回数量
            
        Returns:
            重排序后的文档列表
        """
        results = self.reranker.rerank(query, documents, top_k)
        
        # 转换回字典格式
        return [
            {
                'text': r.text,
                'score': r.score,
                'original_score': r.original_score,
                'metadata': r.metadata,
            }
            for r in results
        ]
    
    async def rerank_with_expansion(
        self,
        query: str,
        retriever,  # RAG 检索器
        top_k: int = 5,
        expansion_limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """带查询扩展的重排序
        
        步骤：
        1. 扩展查询
        2. 对每个扩展查询进行检索
        3. 合并去重
        4. 重排序
        
        Args:
            query: 原始查询
            retriever: RAG 检索器（需要有 retrieve 方法）
            top_k: 最终返回数量
            expansion_limit: 每个扩展查询的检索数量
            
        Returns:
            重排序后的文档列表
        """
        # 1. 扩展查询
        expanded_queries = self.expander.expand(query)
        
        # 2. 多路召回
        all_docs = {}
        for eq in expanded_queries:
            try:
                results = await retriever.retrieve(
                    query=eq,
                    limit=expansion_limit,
                    score_threshold=0.0,
                )
                for doc in results:
                    # 使用文本 hash 作为去重 key
                    text = doc.get('text', '')
                    doc_key = hash(text)
                    
                    if doc_key not in all_docs:
                        all_docs[doc_key] = doc
                    else:
                        # 保留分数更高的
                        if doc.get('score', 0) > all_docs[doc_key].get('score', 0):
                            all_docs[doc_key] = doc
                            
            except Exception as e:
                logger.warning(f"[RAGReranker] 扩展查询检索失败: {eq[:50]}... - {e}")
        
        # 3. 重排序
        merged_docs = list(all_docs.values())
        
        if not merged_docs:
            logger.warning(f"[RAGReranker] 无检索结果")
            return []
        
        logger.info(
            f"[RAGReranker] 多路召回: {len(expanded_queries)} 查询 -> "
            f"{len(merged_docs)} 文档 (去重后)"
        )
        
        # 4. 重排序
        results = self.rerank(query, merged_docs, top_k)
        
        return results


# 全局实例
rag_reranker = RAGReranker()


# 便捷函数
def rerank_documents(
    query: str,
    documents: List[Dict[str, Any]],
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """便捷函数：重排序文档"""
    return rag_reranker.rerank(query, documents, top_k)


def expand_query(query: str) -> List[str]:
    """便捷函数：扩展查询"""
    return rag_reranker.expander.expand(query)

