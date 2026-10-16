// Apply during installation before enabling card transfer. Neo4j 5+.
CREATE CONSTRAINT avl4_material_identity IF NOT EXISTS
FOR (n:avl4material) REQUIRE n.avl4_import_key IS UNIQUE;
