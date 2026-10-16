"""Explicit operator initialization/readiness for a fresh AVL4 installation."""

from __future__ import annotations

import os
import subprocess
import sys

from neo4j import GraphDatabase
from redis import Redis
from sqlalchemy import create_engine, text

SQL_REVISION = "a6b7c8d9e0f1"

CONSTRAINT = """CREATE CONSTRAINT avl4_material_identity IF NOT EXISTS
FOR (n:avl4material) REQUIRE n.avl4_import_key IS UNIQUE"""


def check_storage() -> None:
    """Check the SQL revision, graph constraint and broker/Auth connections."""
    engine = create_engine(
        os.environ["DATABASE_URL"], connect_args={"connect_timeout": 3}
    )
    try:
        with engine.connect() as connection:
            if (
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar()
                != SQL_REVISION
            ):
                raise RuntimeError("Flowsint schema is not initialized")
    finally:
        engine.dispose()
    with (
        GraphDatabase.driver(
            os.environ["NEO4J_URI_BOLT"],
            auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
            connection_timeout=3,
        ) as driver,
        driver.session() as session,
    ):
        result = session.run(
            "SHOW CONSTRAINTS YIELD name WHERE name = 'avl4_material_identity' RETURN count(*) AS total"
        ).single()
        if not result or result["total"] != 1:
            raise RuntimeError("Flowsint graph schema is not initialized")
    with Redis.from_url(
        os.environ["REDIS_URL"], socket_timeout=3, socket_connect_timeout=3
    ) as broker:
        broker.ping()
    from avl4_auth import get_redis_client

    get_redis_client().ping()


def initialize() -> None:
    """Run migrations, then the graph DDL; safe to repeat, never deletes data."""
    subprocess.run(["alembic", "upgrade", "head"], check=True, capture_output=True)
    with (
        GraphDatabase.driver(
            os.environ["NEO4J_URI_BOLT"],
            auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
            connection_timeout=5,
        ) as driver,
        driver.session() as session,
    ):
        session.run(CONSTRAINT).consume()
    check_storage()


def main() -> int:
    try:
        if sys.argv[1:] == ["--check"]:
            check_storage()
        elif not sys.argv[1:]:
            initialize()
            print("Flowsint SQL and graph schemas are ready.")
        else:
            return 2
    except Exception:
        # Connection strings, SQL diagnostics and credentials stay out of operator output.
        print("Flowsint storage initialization/readiness failed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
