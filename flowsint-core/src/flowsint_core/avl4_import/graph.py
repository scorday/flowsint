"""Project a checked SQL material into the investigation graph."""

import hashlib
import json
from typing import Protocol

from sqlalchemy.orm import Session

from flowsint_core.core.graph.connection import Neo4jConnection
from flowsint_core.core.graph.repository import Neo4jGraphRepository
from flowsint_core.core.graph.schema import require_schema
from flowsint_core.core.graph.service import resolve_graph_scope

from .contracts import CardSnapshot
from .repository import Avl4Material


class MaterialProjection(Protocol):
    def project(self, material: Avl4Material) -> str: ...


class Neo4jMaterialProjection:
    def __init__(
        self, connection: Neo4jConnection | None = None, *, db: Session | None = None
    ) -> None:
        self.connection = connection
        self.db = db

    def project(self, material: Avl4Material) -> str:
        connection = self.connection or Neo4jConnection.get_instance()
        require_schema(connection)
        snapshot = CardSnapshot.model_validate(material.snapshot)
        # Wire material_key intentionally stays sketch-specific: it identifies
        # an import operation/projection, while the graph entity is shared.
        identity = hashlib.sha256(
            json.dumps(
                [
                    material.project_id,
                    str(material.investigation_id),
                    snapshot.card_type,
                    snapshot.source_project_id,
                    snapshot.card_id,
                ],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        props = {
            f"nodeProperties.{key}": value
            for key, value in snapshot.model_dump(mode="json").items()
        }
        props.update(
            {
                "nodeProperties.snapshot_hash": material.snapshot_hash,
                "nodeType": "avl4_card",
                "nodeLabel": snapshot.title,
                "avl4_import_key": identity,
                "avl4_revision": material.revision,
                "nodeShape": "square",
                "nodeIcon": "FileText",
                "nodeMetadata.created_at": snapshot.captured_at.isoformat(),
            }
        )
        scope = resolve_graph_scope(str(material.sketch_id), db=self.db)
        if scope.project_id != material.project_id or scope.investigation_id != str(
            material.investigation_id
        ):
            raise PermissionError("Material does not belong to the verified graph")
        repository = Neo4jGraphRepository(connection, scope=scope)
        return repository.project_material(props, str(material.sketch_id))
