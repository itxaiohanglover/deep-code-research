"""上传文档解析服务 - 批量解析 uploads 目录中的文档

职责：
- 扫描 uploads 目录中的所有文档
- 批量解析各种格式的文件（PDF, DOCX, PPTX, TXT, 图片等）
- 返回结构化的解析结果
- 格式化为上下文文本供 LLM 使用
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from omegaconf import DictConfig

try:
    from ms_agent.utils import get_logger
    logger = get_logger()
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


@dataclass
class ParsedDocument:
    """解析后的文档"""
    filename: str
    file_type: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'filename': self.filename,
            'type': self.file_type,
            'content': self.content,
            'metadata': self.metadata
        }


class UploadsService:
    """上传文档解析服务
    
    支持的格式：
    - 文档：PDF, DOCX, DOC, PPTX, PPT, TXT, MD
    - 图片：PNG, JPG, JPEG, GIF, WEBP
    
    使用方式：
    ```python
    service = UploadsService(config)
    documents = await service.parse_all()
    context = service.format_as_context(documents)
    ```
    """
    
    # 支持的文件扩展名
    DOCUMENT_EXTENSIONS = {'.pdf', '.docx', '.doc', '.pptx', '.ppt', '.txt', '.md'}
    IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
    
    def __init__(self, config: DictConfig = None, uploads_dir: Optional[str] = None):
        """初始化服务
        
        Args:
            config: 配置对象
            uploads_dir: 可选的上传目录路径，如不提供则从配置读取
        """
        self.config = config
        
        # 确定上传目录
        if uploads_dir:
            self._uploads_dir = Path(uploads_dir)
        else:
            rc = getattr(config, 'research_config', {}) if config else {}
            dir_path = rc.get('uploads_dir') if hasattr(rc, 'get') else getattr(rc, 'uploads_dir', None)
            if not dir_path:
                import os
                output_root = getattr(config, 'output_dir', None) if config else None
                output_root = output_root or os.getenv('OUTPUT_DIR', 'output')
                dir_path = f"{output_root}/uploads"
            self._uploads_dir = Path(dir_path)
        
        # 配置项
        self.max_content_length = 5000  # 单个文档最大内容长度
        self.enable_vision = True       # 是否启用视觉模型解析图片
        
        # 懒加载的处理器
        self._document_processor = None
        self._vlm_service = None
    
    @property
    def uploads_dir(self) -> Path:
        return self._uploads_dir
    
    def _get_document_processor(self):
        """懒加载文档处理器"""
        if self._document_processor is None:
            try:
                from .processor import DocumentProcessor
                self._document_processor = DocumentProcessor(self.config)
            except ImportError as e:
                logger.warning(f"[uploads_service] 文档处理器导入失败: {e}")
        return self._document_processor
    
    def _get_vlm_service(self):
        """懒加载 VLM 服务（通过 API 调用）"""
        if self._vlm_service is None and self.enable_vision:
            try:
                from src.tools.vision.service import VLMService
                self._vlm_service = VLMService(self.config)
                logger.info("[uploads_service] VLM 服务初始化成功（API 模式）")
            except ImportError as e:
                logger.warning(f"[uploads_service] VLM 服务导入失败: {e}")
        return self._vlm_service
    
    async def parse_all(self) -> List[ParsedDocument]:
        """解析 uploads 目录中的所有文档
        
        Returns:
            解析结果列表
        """
        if not self._uploads_dir.exists():
            logger.info(f"[uploads_service] uploads 目录不存在: {self._uploads_dir}")
            return []
        
        documents: List[ParsedDocument] = []
        supported = self.DOCUMENT_EXTENSIONS | self.IMAGE_EXTENSIONS
        
        for file_path in sorted(self._uploads_dir.iterdir()):
            if not file_path.is_file():
                continue
            
            ext = file_path.suffix.lower()
            if ext not in supported:
                logger.debug(f"[uploads_service] 跳过不支持的文件: {file_path.name}")
                continue
            
            try:
                doc = await self._parse_file(file_path)
                if doc:
                    documents.append(doc)
                    logger.info(f"[uploads_service] 已解析: {file_path.name} ({doc.file_type})")
            except Exception as e:
                logger.warning(f"[uploads_service] 解析失败 {file_path.name}: {e}")
                documents.append(ParsedDocument(
                    filename=file_path.name,
                    file_type=ext.lstrip('.'),
                    content=f"[解析失败: {str(e)}]",
                    metadata={'error': str(e)}
                ))
        
        logger.info(f"[uploads_service] 共解析 {len(documents)} 个文档")
        return documents
    
    async def _parse_file(self, file_path: Path) -> Optional[ParsedDocument]:
        """解析单个文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            解析结果，失败返回 None
        """
        ext = file_path.suffix.lower()
        
        # 图片文件
        if ext in self.IMAGE_EXTENSIONS:
            return await self._parse_image(file_path)
        
        # 文档文件
        if ext in self.DOCUMENT_EXTENSIONS:
            return await self._parse_document(file_path)
        
        return None
    
    async def _parse_document(self, file_path: Path) -> ParsedDocument:
        """解析文档文件"""
        processor = self._get_document_processor()
        
        if processor is None:
            return ParsedDocument(
                filename=file_path.name,
                file_type=file_path.suffix.lstrip('.'),
                content="[文档处理器不可用]"
            )
        
        # 使用同步方法 process_one
        content_obj = processor.process_one(str(file_path))
        text = content_obj.text if hasattr(content_obj, 'text') else str(content_obj)
        
        # 截断过长内容
        if len(text) > self.max_content_length:
            text = text[:self.max_content_length] + "\n...[内容过长，已截断]..."
        
        metadata = {}
        if hasattr(content_obj, 'metadata'):
            metadata = content_obj.metadata
        
        return ParsedDocument(
            filename=file_path.name,
            file_type=file_path.suffix.lstrip('.'),
            content=text,
            metadata=metadata
        )
    
    async def _parse_image(self, file_path: Path) -> ParsedDocument:
        """解析图片文件（通过 VLM API）"""
        vlm = self._get_vlm_service()
        
        if vlm is None:
            return ParsedDocument(
                filename=file_path.name,
                file_type='image',
                content="[图片文件，VLM 服务不可用]"
            )
        
        try:
            # 使用异步方法调用 VLM API
            description = await vlm.describe_image(
                str(file_path),
                prompt="请详细描述这张图片的内容，包括关键的技术要点、图表信息、文字内容等。"
            )
            
            # 检查是否是错误响应
            if description.startswith('[') and '失败' in description:
                content = description
            else:
                content = f"[图片描述] {description}"
                
        except Exception as e:
            logger.warning(f"[uploads_service] 图片描述失败: {e}")
            content = f"[图片解析失败: {str(e)}]"
        
        return ParsedDocument(
            filename=file_path.name,
            file_type='image',
            content=content,
            metadata={'original_format': file_path.suffix.lstrip('.')}
        )
    
    def format_as_context(self, documents: List[ParsedDocument], max_total_length: int = 20000) -> str:
        """格式化解析结果为上下文文本
        
        Args:
            documents: 解析的文档列表
            max_total_length: 总内容最大长度
            
        Returns:
            格式化的 Markdown 文本
        """
        if not documents:
            return ""
        
        lines = [
            "## 用户上传的参考文档\n",
            f"共 {len(documents)} 个文档：\n"
        ]
        
        current_length = sum(len(line) for line in lines)
        
        for i, doc in enumerate(documents, 1):
            header = f"\n### 文档 {i}: {doc.filename} ({doc.file_type})\n"
            content = doc.content
            
            # 检查是否超出总长度限制
            if current_length + len(header) + len(content) > max_total_length:
                remaining = max_total_length - current_length - len(header) - 50
                if remaining > 100:
                    content = content[:remaining] + "\n...[已截断]..."
                else:
                    lines.append(f"\n...[还有 {len(documents) - i + 1} 个文档未显示]...")
                    break
            
            lines.append(header)
            lines.append(content)
            lines.append("")
            
            current_length += len(header) + len(content) + 1
        
        return "\n".join(lines)
    
    def to_json(self, documents: List[ParsedDocument]) -> str:
        """将解析结果序列化为 JSON
        
        Args:
            documents: 解析的文档列表
            
        Returns:
            JSON 字符串
        """
        return json.dumps(
            [doc.to_dict() for doc in documents],
            ensure_ascii=False,
            indent=2
        )
    
    def get_summary(self, documents: List[ParsedDocument]) -> str:
        """获取解析结果摘要
        
        Args:
            documents: 解析的文档列表
            
        Returns:
            摘要文本
        """
        if not documents:
            return "无上传文档"
        
        type_counts: Dict[str, int] = {}
        for doc in documents:
            t = doc.file_type
            type_counts[t] = type_counts.get(t, 0) + 1
        
        parts = [f"{count} 个 {t}" for t, count in type_counts.items()]
        return f"共 {len(documents)} 个文档: " + ", ".join(parts)
