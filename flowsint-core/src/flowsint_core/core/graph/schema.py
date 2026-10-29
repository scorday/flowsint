"""Investigation graph schema. Installation is an explicit operator action."""

from .connection import GraphConnectionProtocol

CONSTRAINTS = {
    "graph_scope_key": "FOR (n:GraphScope) REQUIRE n.key IS UNIQUE",
    "graph_entity_uid": "FOR (n:GraphEntity) REQUIRE n.uid IS UNIQUE",
    "graph_view_key": "FOR (n:GraphView) REQUIRE (n.scope_key, n.sketch_id) IS UNIQUE",
}


def install_schema(connection: GraphConnectionProtocol) -> None:
    for name, definition in CONSTRAINTS.items():
        connection.execute_write(f"CREATE CONSTRAINT {name} IF NOT EXISTS {definition}")
    connection.execute_write(
        "CREATE INDEX graph_entity_scope IF NOT EXISTS FOR (n:GraphEntity) ON (n.scope_key)"
    )


def require_schema(connection: GraphConnectionProtocol) -> None:
    rows = connection.query(
        "SHOW CONSTRAINTS YIELD name, labelsOrTypes, properties, type RETURN name, labelsOrTypes, properties, type"
    )
    expected = {
        "graph_scope_key": (["GraphScope"], ["key"]),
        "graph_entity_uid": (["GraphEntity"], ["uid"]),
        "graph_view_key": (["GraphView"], ["scope_key", "sketch_id"]),
    }
    valid = {
        r["name"]
        for r in rows
        if r["name"] in expected
        and (r["labelsOrTypes"], r["properties"]) == expected[r["name"]]
        and r["type"] in {"UNIQUENESS", "NODE_PROPERTY_UNIQUENESS"}
    }
    if not CONSTRAINTS.keys() <= valid:
        raise RuntimeError(
            "Investigation graph schema is required; run the graph migration first"
        )
