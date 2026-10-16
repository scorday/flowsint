// Apply during installation before enabling card transfer. Neo4j 5+.
CREATE CONSTRAINT avl4_card_identity IF NOT EXISTS
FOR (n:avl4_card) REQUIRE n.avl4_import_key IS UNIQUE;

// Upgrade existing imports in place, preserving element IDs and relationships.
MATCH (n:avl4material)
SET n:avl4_card, n.nodeType = 'avl4_card'
REMOVE n:avl4material;

DROP CONSTRAINT avl4_material_identity IF EXISTS;
