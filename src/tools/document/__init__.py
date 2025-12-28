"""文档处理工具模块

支持多种文档格式的解析和处理（PDF、DOCX、PPTX、TXT）。
支持批量解析上传目录中的文档。
"""

from .processor import DocumentProcessor
from .parsers import (
    TxtParser,
    PdfParser,
    DocxParser,
    PptxParser,
    DocumentContent,
    ImageContent,
    TableContent,
)
from .uploads import UploadsService, ParsedDocument

__all__ = [
    "DocumentProcessor",
    "UploadsService",
    "ParsedDocument",
    "TxtParser",
    "PdfParser",
    "DocxParser",
    "PptxParser",
    "DocumentContent",
    "ImageContent",
    "TableContent",
]
