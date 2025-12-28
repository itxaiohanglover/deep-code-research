"""文档解析器基础类"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Any


class BaseParser:
    """文档解析器基类"""

    name: str = "base"
    extensions: tuple[str, ...] = ()

    def supports(self, suffix: str) -> bool:
        return suffix.lower() in self.extensions

    def parse(self, file_path: Path) -> Dict[str, Any]:
        raise NotImplementedError

    def _build_result(self, text: str, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
        metadata = metadata or {}
        preview = self._build_preview(text)
        return {
            "text": text,
            "content_preview": preview,
            "metadata": metadata,
        }

    @staticmethod
    def _build_preview(text: str, limit: int = 500) -> str:
        cleaned = " ".join(text.split())
        if len(cleaned) > limit:
            return f"{cleaned[:limit].rstrip()}..."
        return cleaned

