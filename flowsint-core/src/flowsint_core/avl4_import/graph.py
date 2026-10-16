from typing import Protocol

from flowsint_core.core.graph.connection import Neo4jConnection

from .contracts import CardSnapshot
from .repository import Avl4Material


class MaterialProjection(Protocol):
    def project(self, material: Avl4Material) -> str: ...


class Neo4jMaterialProjection:
    def __init__(self, connection: Neo4jConnection | None = None) -> None:
        self.connection = connection

    def project(self, material: Avl4Material) -> str:
        connection = self.connection or Neo4jConnection.get_instance()
        # Installation owns DDL. Refuse writes unless uniqueness is enforced.
        constraints = connection.query("""
            SHOW CONSTRAINTS YIELD labelsOrTypes, properties, type
            WHERE labelsOrTypes = ['avl4_card'] AND properties = ['avl4_import_key']
              AND type IN ['UNIQUENESS', 'NODE_PROPERTY_UNIQUENESS']
            RETURN count(*) AS total
        """)
        if not constraints or not constraints[0]["total"]:
            raise RuntimeError("AVL4 material constraint is required")
        snapshot = CardSnapshot.model_validate(material.snapshot)
        props = {
            f"nodeProperties.{key}": value
            for key, value in snapshot.model_dump(mode="json").items()
        }
        props.update(
            {
                "nodeProperties.snapshot_hash": material.snapshot_hash,
                "nodeType": "avl4_card",
                "nodeLabel": snapshot.title,
                "sketch_id": str(material.sketch_id),
                "project_id": material.project_id,
                "avl4_import_key": material.material_key,
                "avl4_revision": material.revision,
                "nodeShape": "square",
                "nodeIcon": "FileText",
            }
        )
        rows = connection.execute_write(
            """
            MERGE (n:avl4_card {avl4_import_key: $key})
            ON CREATE SET n.`nodeMetadata.created_at` = $captured_at
            WITH n WHERE n.sketch_id IS NULL OR (n.sketch_id = $sketch AND n.project_id = $project)
            SET n += $props, n.deleted_at = null
            RETURN elementId(n) AS id
        """,
            {
                "key": material.material_key,
                "sketch": str(material.sketch_id),
                "project": material.project_id,
                "captured_at": snapshot.captured_at.isoformat(),
                "props": props,
            },
        )
        if not rows:
            raise RuntimeError("Material projection rejected")
        return str(rows[0]["id"])
