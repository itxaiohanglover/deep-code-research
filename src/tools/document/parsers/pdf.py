from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, List, Optional

from src.tools.document.parsers.types import DocumentContent, ImageContent, TableContent

try:
    from docling.document_converter import DocumentConverter  # type: ignore
except Exception:
    DocumentConverter = None  # type: ignore

try:
    import PyPDF2  # type: ignore
except Exception:
    PyPDF2 = None  # type: ignore

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None  # type: ignore


class PdfParser:
    """PDF 文档解析器。
    
    支持提取：
    - 文本内容（优先使用 docling，回退到 PyMuPDF 或 PyPDF2）
    - 嵌入图片（使用 PyMuPDF）
    - 表格内容（通过 docling）
    """
    
    def __init__(self, output_dir: Optional[Path] = None) -> None:
        """初始化解析器。
        
        Args:
            output_dir: 图片输出目录，默认使用文档同级 images 目录
        """
        self._output_dir = output_dir
        self._converter: DocumentConverter | None = None
        if DocumentConverter is not None:
            try:
                self._converter = DocumentConverter()  # type: ignore[call-arg]
            except Exception:
                self._converter = None

    def parse(self, path: Path) -> DocumentContent:
        """解析 PDF 文档。
        
        解析策略：
        1. 优先使用 docling（最佳文本和表格提取）
        2. 回退到 PyMuPDF（支持图片提取）
        3. 最后回退到 PyPDF2（仅文本）
        
        Args:
            path: PDF 文件路径
            
        Returns:
            结构化的文档内容
        """
        warning: str | None = None
        images: List[ImageContent] = []
        
        # 尝试使用 PyMuPDF 提取图片（无论文本解析用什么方式）
        if fitz is not None:
            try:
                images = self._extract_pymupdf_images(path)
            except Exception as exc:
                warning = f"PyMuPDF image extraction failed: {exc}"
        
        # 策略 1: 使用 docling 解析文本
        if self._converter is not None:
            try:
                result = self._converter.convert(str(path))  # type: ignore[call-arg]
                text = self._extract_docling_text(result)
                docling_images = self._extract_docling_images(result, base_path=path)
                # 合并 docling 和 PyMuPDF 提取的图片（去重）
                all_images = self._merge_images(images, docling_images)
                metadata = {
                    "path": str(path), 
                    "format": "pdf", 
                    "parser": "docling",
                    "images": len(all_images),
                }
                if warning:
                    metadata["warning"] = warning
                return DocumentContent(text=text, images=all_images, metadata=metadata)
            except Exception as exc:
                warning = f"docling conversion failed: {exc}"
        else:
            warning = "docling not available; falling back to PyMuPDF/PyPDF2."

        # 策略 2: 使用 PyMuPDF 解析文本
        if fitz is not None:
            try:
                doc = fitz.open(str(path))
                text_chunks: List[str] = []
                for page in doc:
                    text_chunks.append(page.get_text())
                doc.close()
                metadata = {
                    "path": str(path), 
                    "format": "pdf", 
                    "parser": "PyMuPDF",
                    "images": len(images),
                }
                if warning:
                    metadata["warning"] = warning
                return DocumentContent(text="\n".join(text_chunks), images=images, metadata=metadata)
            except Exception as exc:
                warning = f"PyMuPDF text extraction failed: {exc}"

        # 策略 3: 使用 PyPDF2 解析文本（不支持图片）
        if PyPDF2 is not None:
            try:
                reader = PyPDF2.PdfReader(str(path))  # type: ignore[arg-type]
                text_chunks = []
                for page in reader.pages:
                    extracted = page.extract_text() or ""
                    text_chunks.append(extracted)
                metadata = {
                    "path": str(path), 
                    "format": "pdf", 
                    "parser": "PyPDF2",
                    "images": len(images),
                }
                if warning:
                    metadata["warning"] = warning
                return DocumentContent(text="\n".join(text_chunks), images=images, metadata=metadata)
            except Exception as exc:
                warning = f"PyPDF2 fallback failed: {exc}"

        return DocumentContent(
            text="", 
            images=images,
            metadata={
                "path": str(path), 
                "format": "pdf", 
                "warning": warning or "PDF parsing failed."
            }
        )

    @staticmethod
    def _extract_docling_text(result: Any) -> str:
        document = getattr(result, "document", None)
        if document is None:
            return ""
        exporters = [
            "export_to_markdown",
            "export_markdown",
            "export_markdown_string",
            "export_plaintext",
            "export_text",
        ]
        for name in exporters:
            exporter = getattr(document, name, None)
            if callable(exporter):
                try:
                    return str(exporter())
                except Exception:
                    continue
        return str(document)

    @staticmethod
    def _extract_docling_images(result: Any, base_path: Path) -> List[ImageContent]:
        images: List[ImageContent] = []
        resources = getattr(result, "resources", None)
        if not resources:
            return images
        doc_images = getattr(resources, "images", None) or []
        for idx, img in enumerate(doc_images, start=1):
            img_path = getattr(img, "path", None) or getattr(img, "file_path", "")
            caption = getattr(img, "caption", "") or getattr(img, "text", "")
            img_type = getattr(img, "type", "") or getattr(img, "category", "")
            if not img_path:
                img_path = str(base_path.with_suffix("")) + f"_image_{idx}.png"
            images.append(ImageContent(path=str(img_path), caption=str(caption), description="", image_type=str(img_type)))
        return images
    
    def _extract_pymupdf_images(self, path: Path) -> List[ImageContent]:
        """使用 PyMuPDF 提取 PDF 中的图片。
        
        Args:
            path: PDF 文件路径
            
        Returns:
            图片内容列表
        """
        if fitz is None:
            return []
        
        images: List[ImageContent] = []
        
        # 确定图片输出目录
        output_dir = self._output_dir
        if output_dir is None:
            output_dir = path.parent / "images" / path.stem
        output_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            doc = fitz.open(str(path))
            
            for page_idx, page in enumerate(doc, start=1):
                # 获取页面中的所有图片
                image_list = page.get_images(full=True)
                
                for img_idx, img_info in enumerate(image_list, start=1):
                    try:
                        xref = img_info[0]  # 图片引用 ID
                        
                        # 提取图片数据
                        base_image = doc.extract_image(xref)
                        if not base_image:
                            continue
                        
                        image_bytes = base_image["image"]
                        image_ext = base_image.get("ext", "png")
                        
                        # 生成唯一文件名
                        content_hash = hashlib.md5(image_bytes).hexdigest()[:8]
                        filename = f"{path.stem}_p{page_idx}_{img_idx}_{content_hash}.{image_ext}"
                        image_path = output_dir / filename
                        
                        # 保存图片
                        image_path.write_bytes(image_bytes)
                        
                        images.append(ImageContent(
                            path=str(image_path),
                            caption=f"Page {page_idx}, Image {img_idx}",
                            description="",
                            image_type="pdf_embedded",
                        ))
                    except Exception:
                        # 单个图片提取失败不影响其他图片
                        continue
            
            doc.close()
            
        except Exception:
            pass
        
        return images
    
    @staticmethod
    def _merge_images(images1: List[ImageContent], images2: List[ImageContent]) -> List[ImageContent]:
        """合并两个图片列表，去除重复项。
        
        Args:
            images1: 第一个图片列表
            images2: 第二个图片列表
            
        Returns:
            合并后的图片列表
        """
        if not images1:
            return images2
        if not images2:
            return images1
        
        # 使用路径作为去重依据
        seen_paths = {img.path for img in images1}
        merged = list(images1)
        
        for img in images2:
            if img.path not in seen_paths:
                merged.append(img)
                seen_paths.add(img.path)
        
        return merged
