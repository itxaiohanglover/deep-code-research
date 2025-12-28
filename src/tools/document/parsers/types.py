from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ImageContent:
    path: str
    caption: str = ""
    description: str = ""
    image_type: str = ""


@dataclass
class TableContent:
    raw: Any
    description: str = ""


@dataclass
class DiagramContent:
    raw: Any
    description: str = ""


@dataclass
class DocumentContent:
    text: str
    images: List[ImageContent] = field(default_factory=list)
    tables: List[TableContent] = field(default_factory=list)
    diagrams: List[DiagramContent] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

