from __future__ import annotations

from pathlib import Path

from src.tools.document.parsers.types import DocumentContent


class TxtParser:
    def parse(self, path: Path) -> DocumentContent:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return DocumentContent(text=text, metadata={"path": str(path), "format": "txt"})
