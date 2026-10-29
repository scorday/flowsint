"""Trusted operator/readiness connection, separate from request admission.

Only server-side bootstrap and explicit migration commands use this adapter.
Request/worker repositories continue to use Neo4jConnection and its project
admission checks. Migration ownership is resolved independently through SQL.
"""

from typing import Any, Callable, TypeVar

from neo4j import Driver

T = TypeVar("T")


class MaintenanceGraphConnection:
    def __init__(self, driver: Driver) -> None:
        self.driver = driver

    def query(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        with self.driver.session() as session:
            return session.run(query, parameters or {}).data()

    def run_transaction(self, operation: Callable[[Any], T]) -> T:
        with self.driver.session() as session:
            return session.execute_write(operation)

    def execute_write(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        return self.run_transaction(lambda tx: tx.run(query, parameters or {}).data())
