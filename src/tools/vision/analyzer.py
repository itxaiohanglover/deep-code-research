"""图片分析器 - 基于规则的图片内容分析

支持：
- 基于关键词的图片类型分类
- OCR 文字提取（使用 EasyOCR 或 PaddleOCR）
- 基础图片信息获取
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Dict, List

from src.tools.document.parsers.types import ImageContent

# 尝试导入 OCR 库
try:
    import easyocr
    _EASYOCR_AVAILABLE = True
except ImportError:
    easyocr = None  # type: ignore
    _EASYOCR_AVAILABLE = False

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    Image = None  # type: ignore
    _PIL_AVAILABLE = False

# 全局 OCR Reader 缓存（避免重复初始化）
_shared_ocr_readers: Dict[tuple, Any] = {}

try:
    from ms_agent.utils import get_logger
    logger = get_logger()
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class ImageAnalyzer:
    """图片分析器。

    功能：
    - 基于关键词的图片类型分类
    - OCR 文字提取（支持中英文）
    - 图片基础信息获取
    
    OCR 支持：
    - 优先使用 EasyOCR（支持多语言，效果好）
    - 可配置是否启用 OCR
    """

    # 图片类型关键词映射
    TYPE_KEYWORDS: Dict[str, List[str]] = {
        "architecture": ["架构", "architecture", "arch", "系统", "system"],
        "flowchart": ["流程", "flow", "diagram", "工作流", "workflow"],
        "table": ["表", "table", "数据", "统计"],
        "screenshot": ["截图", "screenshot", "界面", "ui", "screen"],
        "chart": ["图表", "chart", "graph", "柱状", "饼图", "折线"],
        "uml": ["uml", "类图", "时序", "sequence", "class diagram"],
    }

    # 图片类型描述模板
    TYPE_DESCRIPTIONS: Dict[str, str] = {
        "architecture": "架构图，描述系统组件与关系",
        "flowchart": "流程图，展示步骤与控制流",
        "table": "数据表或图表",
        "screenshot": "界面或执行截图",
        "chart": "数据可视化图表",
        "uml": "UML 建模图",
    }
    
    def __init__(self, enable_ocr: bool = True, ocr_languages: List[str] = None):
        """初始化图片分析器。
        
        Args:
            enable_ocr: 是否启用 OCR 功能
            ocr_languages: OCR 支持的语言列表，默认 ['ch_sim', 'en']
        """
        self.enable_ocr = enable_ocr and _EASYOCR_AVAILABLE
        self.ocr_languages = ocr_languages or ['ch_sim', 'en']
        self._ocr_reader = None
    
    def _get_ocr_reader(self):
        """懒加载 OCR Reader（使用全局缓存避免重复初始化）。"""
        if self._ocr_reader is not None:
            return self._ocr_reader
            
        if not self.enable_ocr or not _EASYOCR_AVAILABLE:
            return None
        
        # 使用语言列表作为 key 来缓存 reader
        lang_key = tuple(sorted(self.ocr_languages))
        
        # 检查全局缓存
        if lang_key not in _shared_ocr_readers:
            try:
                _shared_ocr_readers[lang_key] = easyocr.Reader(self.ocr_languages, gpu=False)
            except Exception as e:
                logger.debug(f"[image_analyzer] OCR Reader 初始化失败: {e}")
                return None
        
        self._ocr_reader = _shared_ocr_readers[lang_key]
        return self._ocr_reader

    def analyze(self, img: ImageContent, include_ocr: bool = True) -> str:
        """分析图片内容并返回描述。

        Args:
            img: 图片内容对象
            include_ocr: 是否包含 OCR 提取的文字

        Returns:
            图片描述字符串
        """
        parts = []
        
        # 合并所有可用的文本信息进行分析
        text_sources = [
            img.caption or "",
            img.image_type or "",
            self._extract_filename_info(img.path),
        ]
        combined_text = " ".join(text_sources).lower()

        # 基于关键词匹配确定图片类型
        img_type_desc = None
        for img_type, keywords in self.TYPE_KEYWORDS.items():
            if any(kw in combined_text for kw in keywords):
                img_type_desc = self.TYPE_DESCRIPTIONS[img_type]
                break
        
        if img_type_desc:
            parts.append(img_type_desc)
        else:
            parts.append(self._get_default_description(img))
        
        # 尝试 OCR 提取文字
        if include_ocr and self.enable_ocr:
            ocr_text = self.extract_text(img.path)
            if ocr_text:
                parts.append(f"图中文字: {ocr_text}")
        
        return "\n".join(parts)
    
    def extract_text(self, image_path: str, max_length: int = 500) -> str:
        """使用 OCR 提取图片中的文字。
        
        Args:
            image_path: 图片文件路径
            max_length: 最大返回文字长度
            
        Returns:
            提取的文字内容，失败返回空字符串
        """
        if not self.enable_ocr:
            return ""
        
        path = Path(image_path)
        if not path.exists():
            return ""
        
        reader = self._get_ocr_reader()
        if reader is None:
            return ""
        
        try:
            # 使用 EasyOCR 识别
            results = reader.readtext(str(path))
            
            # 提取文字并按位置排序（从上到下，从左到右）
            texts = []
            for (bbox, text, confidence) in results:
                if confidence > 0.3:  # 只保留置信度较高的结果
                    texts.append(text.strip())
            
            if not texts:
                return ""
            
            # 合并文字
            combined = " ".join(texts)
            
            # 截断过长内容
            if len(combined) > max_length:
                combined = combined[:max_length] + "..."
            
            return combined
            
        except Exception:
            return ""
    
    def analyze_with_ocr(self, img: ImageContent) -> Dict[str, str]:
        """分析图片并返回详细结果（包含 OCR）。
        
        Args:
            img: 图片内容对象
            
        Returns:
            包含分类、描述、OCR 文字等信息的字典
        """
        result = {
            "type": self.classify(img),
            "description": self._get_default_description(img),
            "ocr_text": "",
        }
        
        # 获取类型描述
        if result["type"] in self.TYPE_DESCRIPTIONS:
            result["description"] = self.TYPE_DESCRIPTIONS[result["type"]]
        
        # OCR 提取文字
        if self.enable_ocr:
            result["ocr_text"] = self.extract_text(img.path)
        
        return result

    def classify(self, img: ImageContent) -> str:
        """分类图片类型。

        Args:
            img: 图片内容对象

        Returns:
            图片类型字符串
        """
        text_sources = [
            img.caption or "",
            img.image_type or "",
            self._extract_filename_info(img.path),
        ]
        combined_text = " ".join(text_sources).lower()

        for img_type, keywords in self.TYPE_KEYWORDS.items():
            if any(kw in combined_text for kw in keywords):
                return img_type

        return "unknown"

    @staticmethod
    def _extract_filename_info(path: str) -> str:
        """从文件路径中提取有用的信息。"""
        if not path:
            return ""
        try:
            p = Path(path)
            # 文件名可能包含类型提示
            return p.stem.replace("_", " ").replace("-", " ")
        except Exception:
            return ""

    def _get_default_description(self, img: ImageContent) -> str:
        """获取默认描述。"""
        # 如果有 caption，使用它
        if img.caption:
            return f"图片: {img.caption}"

        # 如果有 image_type，使用它
        if img.image_type:
            return f"{img.image_type} 类型图片"

        # 基于文件名生成描述
        filename_info = self._extract_filename_info(img.path)
        if filename_info:
            return f"图片: {filename_info}"

        return "图片内容待理解"

    def get_image_info(self, path: str) -> Dict[str, str]:
        """获取图片基本信息。

        Args:
            path: 图片文件路径

        Returns:
            包含图片信息的字典
        """
        info: Dict[str, str] = {"path": path, "exists": "false"}

        try:
            p = Path(path)
            if p.exists():
                info["exists"] = "true"
                info["filename"] = p.name
                info["extension"] = p.suffix.lower()
                info["size_bytes"] = str(p.stat().st_size)
        except Exception:
            pass

        return info
