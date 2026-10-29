from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EntityPreview:
    """Preview of a single entity to be imported."""

    obj: Dict[str, Any]
    detected_type: str
    node_id: Optional[str] = None
    presentation: Dict[str, Any] = field(default_factory=dict)
    graph_uid: Optional[str] = None


@dataclass
class Entity:
    """Entity class"""

    type: str
    results: List[EntityPreview]


@dataclass
class Edge:
    """Edge class"""

    from_obj: Dict[str, Any]
    to_obj: Dict[str, Any]
    from_id: str | None
    to_id: str | None
    label: str
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FileParseResult:
    """Result of parsing an import file."""

    entities: Dict[str, Entity]
    total_entities: int
    edges: Optional[List[Edge]] = field(default_factory=list)
