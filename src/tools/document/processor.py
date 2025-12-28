"""文档处理模块（完整版，支持可选的 vision 依赖）

职责：
- 识别文档格式（支持 TXT/PDF/DOCX/PPTX）
- 读取并返回结构化的 `DocumentContent`
- 图片智能分析（支持 VLM、OCR、规则分析）
- 图片保存到会话关联目录
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Dict, Any, Optional

from omegaconf import DictConfig

from src.tools.document.parsers import (
    TxtParser,
    PdfParser,
    DocxParser,
    PptxParser,
    DocumentContent,
    ImageContent,
)
from src.tools.document.table import TableExtractor


class DocumentProcessor:
    """文档处理模块。

    职责：
    - 识别文档格式（支持 TXT/PDF/DOCX/PPTX）
    - 读取并返回结构化的 `DocumentContent`
    - 图片智能分析（VLM > OCR > 规则）
    
    图片分析策略：
    1. 如果 enable_vision=True 且配置了 VLM，使用 VLM 理解图片
    2. 如果 enable_ocr=True，使用 OCR 提取图中文字
    3. 回退到基于规则的图片分类
    
    使用方式：
    ```python
    processor = DocumentProcessor(config, enable_vision=True, enable_ocr=True)
    content = processor.process_one("path/to/doc.pdf")
    ```
    """

    # 支持的文档格式映射
    SUPPORTED_FORMATS = {
        ".txt": "txt",
        ".md": "txt",        # Markdown 使用 TxtParser（纯文本）
        ".markdown": "txt",  # Markdown 使用 TxtParser（纯文本）
        ".pdf": "pdf",
        ".doc": "docx",
        ".docx": "docx",
        ".ppt": "pptx",
        ".pptx": "pptx",
    }

    def __init__(
        self, 
        config: DictConfig = None, 
        upload_root: Path = None,
        enable_vision: bool = True,
        enable_ocr: bool = True,
        images_dir: Path = None,
    ) -> None:
        """初始化文档处理器。

        Args:
            config: 配置对象（可选）
            upload_root: 上传文件根目录（可选）
            enable_vision: 是否启用 VLM 视觉分析（默认 True）
            enable_ocr: 是否启用 OCR 文字提取（默认 True）
            images_dir: 图片保存目录（可选，默认为文档同级 images 目录）
        """
        self.config = config
        self.upload_root = Path(upload_root) if upload_root else None
        self.enable_vision = enable_vision
        self.enable_ocr = enable_ocr
        self.images_dir = Path(images_dir) if images_dir else None
        
        # 初始化解析器，传入图片输出目录
        self._parsers = {
            "txt": TxtParser(),
            "pdf": PdfParser(output_dir=self.images_dir),
            "docx": DocxParser(output_dir=self.images_dir),
            "pptx": PptxParser(output_dir=self.images_dir),
        }
        self._table_extractor = TableExtractor()
        
        # 懒加载的视觉处理器
        self._image_analyzer = None
        self._vlm_service = None

    def _get_image_analyzer(self):
        """懒加载图片分析器（支持 OCR）"""
        if self._image_analyzer is None:
            try:
                from src.tools.vision.analyzer import ImageAnalyzer
                self._image_analyzer = ImageAnalyzer(enable_ocr=self.enable_ocr)
            except ImportError:
                pass
        return self._image_analyzer
    
    def _get_vlm_service(self):
        """懒加载 VLM 服务
        
        只有在 enable_vision=True 且配置了 API Key 时才初始化。
        """
        if self._vlm_service is None and self.enable_vision:
            try:
                from src.tools.vision.service import VLMService
                service = VLMService(self.config)
                # 只有配置了 API Key 才使用 VLM
                if service.api_key:
                    self._vlm_service = service
            except ImportError:
                pass
        return self._vlm_service

    def process_one(self, file_path: str) -> DocumentContent:
        """解析单个文档并返回结构化内容。

        Args:
            file_path: 文件路径

        Returns:
            结构化的文档内容
        """
        path = Path(file_path)
        doc_type = self._detect_format(path)

        parser = self._parsers.get(doc_type)
        if parser is None:
            return DocumentContent(
                text="",
                metadata={
                    "path": str(path),
                    "format": doc_type,
                    "warning": f"Unsupported document format `{doc_type}`.",
                },
            )

        content = parser.parse(path)

        # 提取表格（如果解析器本身没有提取）
        if not content.tables and doc_type == "docx":
            content.tables = self._table_extractor.extract_docx(path)
        elif not content.tables and doc_type == "pptx":
            content.tables = self._table_extractor.extract_pptx(path)
        
        # 分析图片（VLM > OCR > 规则）
        if content.images and (self.enable_vision or self.enable_ocr):
            self._analyze_images(content.images)
            # 将图片描述整合到文本内容中
            content.text = self._integrate_images_to_text(content)

        return content
    
    def _analyze_images(self, images: List[ImageContent]) -> None:
        """对图片列表进行智能分析，填充描述信息。
        
        分析策略（按优先级）：
        1. VLM 视觉理解（如果启用且可用）
        2. OCR 文字提取 + 规则分类（如果启用）
        3. 基于规则的分类
        """
        vlm = self._get_vlm_service() if self.enable_vision else None
        analyzer = self._get_image_analyzer()
        
        total = len(images)
        for idx, img in enumerate(images, 1):
            if img.description:
                continue  # 已有描述，跳过
            
            img_path = Path(img.path)
            if not img_path.exists():
                img.description = "[图片文件不存在]"
                continue
            
            # 显示进度
            print(f"  🖼️  分析图片 [{idx}/{total}]: {img_path.name}", end="", flush=True)
            
            # 策略 1: VLM 视觉理解
            if vlm:
                try:
                    desc = vlm.describe(img.path)
                    if desc and not desc.startswith('['):
                        img.description = desc
                        print(" ✅ VLM")
                        continue
                except Exception as e:
                    print(f" ⚠️ VLM失败", end="")
            
            # 策略 2 & 3: OCR + 规则分析
            if analyzer:
                # analyze 方法会根据 enable_ocr 决定是否包含 OCR
                img.description = analyzer.analyze(img, include_ocr=self.enable_ocr)
                print(" ✅ OCR" if self.enable_ocr else " ✅ 规则")
            else:
                # 没有 analyzer，提供基础描述
                img.description = f"图片: {img_path.name}"
                print(" ✅ 基础")
    
    def _integrate_images_to_text(self, content: DocumentContent) -> str:
        """将图片描述整合到文档文本中。
        
        策略：
        1. 查找文本中的图片标记（如 <!-- image -->、图 1 等）
        2. 在标记位置插入对应的图片描述
        3. 如果没有标记，按顺序在文本末尾添加
        
        Args:
            content: 文档内容对象
            
        Returns:
            整合后的文本内容
        """
        if not content.text:
            text = ""
        else:
            text = content.text
        
        if not content.images:
            return text
        
        # 查找文本中的图片标记位置
        import re
        
        # 匹配常见的图片标记模式（按优先级排序）
        image_patterns = [
            r'（图\s*\d+[：:：]\s*[^）)]+）',  # （图 1：描述）中文括号
            r'\(图\s*\d+[：:：]\s*[^)]+\)',  # (图 1：描述) 英文括号
            r'<!--\s*image\s*-->',  # <!-- image -->
            r'<!--\s*图\s*\d+\s*-->',  # <!-- 图 1 -->
            r'图\s*\d+[：:：]\s*[^\n]+',  # 图 1：描述（单独一行）
        ]
        
        # 按顺序匹配图片位置
        image_positions = []
        for pattern in image_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                image_positions.append((match.start(), match.end(), match.group()))
        
        # 如果有图片标记，在标记位置插入描述
        if image_positions and len(image_positions) == len(content.images):
            # 从后往前插入，避免位置偏移
            result = text
            for idx in range(len(content.images) - 1, -1, -1):
                image = content.images[idx]
                start, end, marker = image_positions[idx]
                
                # 构建图片描述
                img_desc = self._format_image_description(image, idx + 1)
                
                # 在标记后插入描述
                result = result[:end] + "\n\n" + img_desc + "\n\n" + result[end:]
            
            return result.strip()
        
        # 如果没有标记或数量不匹配，在文本末尾添加所有图片描述
        parts = [text] if text else []
        parts.append("\n\n## 📷 文档中的图片\n")
        
        for idx, image in enumerate(content.images, 1):
            parts.append(self._format_image_description(image, idx))
        
        return "\n".join(parts).strip()
    
    def _format_image_description(self, image: ImageContent, idx: int) -> str:
        """格式化单个图片描述。
        
        Args:
            image: 图片内容对象
            idx: 图片序号
            
        Returns:
            格式化后的图片描述文本
        """
        caption = image.caption or f"图片 {idx}"
        img_name = Path(image.path).name
        
        parts = [f"### {caption}\n"]
        
        if image.description:
            # 如果描述不是错误信息，直接使用
            if not image.description.startswith('[') or '失败' not in image.description:
                parts.append(f"{image.description}")
            else:
                parts.append(f"*图片分析: {image.description}*")
        else:
            parts.append(f"*图片文件: {img_name}*")
        
        return "\n".join(parts)
    
    def process(self, file_paths: List[str], session_id: str = None) -> Dict[str, Any]:
        """处理多个文件并返回摘要。

        Args:
            file_paths: 文件路径列表
            session_id: 会话 ID（可选）

        Returns:
            包含所有文件处理结果的摘要字典
        """
        processed_files = []
        for file_path_str in file_paths:
            path = Path(file_path_str)
            doc_type = self._detect_format(path)

            parser = self._parsers.get(doc_type)
            if parser is None:
                processed_files.append({
                    "filename": path.name,
                    "type": doc_type,
                    "status": "skipped",
                    "reason": f"Unsupported format: {doc_type}",
                })
                continue

            try:
                content = self.process_one(file_path_str)

                # 格式化内容
                formatted_content = self._format_document_content(content)

                processed_files.append({
                    "filename": path.name,
                    "type": doc_type,
                    "status": "success",
                    "content": formatted_content,
                    "metadata": content.metadata,
                })
            except Exception as e:
                processed_files.append({
                    "filename": path.name,
                    "type": doc_type,
                    "status": "failed",
                    "reason": str(e),
                })
        
        return {"files": processed_files, "session_id": session_id}
    
    def _format_document_content(self, content: DocumentContent) -> str:
        """将结构化文档内容格式化为供 LLM 使用的文本。
        
        注意：图片描述已经整合到 content.text 中，这里只需要处理表格。
        """
        parts = []
        if content.text:
            parts.append(content.text)
        
        # 添加表格（如果文本中还没有）
        if content.tables:
            parts.append("\n\n## 📊 文档中的表格\n")
            for idx, table in enumerate(content.tables, 1):
                parts.append(f"\n### 表格 {idx + 1}: {table.description}\n")
                parts.append(self._table_extractor.to_markdown(table))
        
        return "\n".join(parts).strip()

    def format_summary(self, summary: Dict[str, Any]) -> str:
        """格式化文件摘要为文本。

        Args:
            summary: 文件摘要字典

        Returns:
            格式化的文本摘要
        """
        if not summary or not summary.get("files"):
            return ""

        formatted_output = []
        for file_info in summary["files"]:
            filename = file_info.get("filename", "未知文件")
            status = file_info.get("status", "未知状态")
            file_type = file_info.get("type", "未知类型")

            formatted_output.append(f"#### 文件: {filename} (类型: {file_type}, 状态: {status})")
            if status == "success":
                content = file_info.get("content", "")
                formatted_output.append(content)
            elif status == "failed":
                reason = file_info.get("reason", "未知错误")
                formatted_output.append(f"解析失败原因: {reason}")
            formatted_output.append("\n---\n")  # 文件间分隔

        return "\n".join(formatted_output)

    def _detect_format(self, path: Path) -> str:
        """根据文件扩展名识别文档格式。"""
        suffix = path.suffix.lower()
        return self.SUPPORTED_FORMATS.get(suffix, suffix.lstrip(".") or "unknown")
