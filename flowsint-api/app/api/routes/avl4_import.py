"""Dedicated service-auth boundary. No browser session or generic auth bypass."""

import hmac
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from flowsint_core.avl4_import.contracts import (
    IMPORT_PATH,
    MAX_BODY_BYTES,
    CardImportCommand,
    CardImportResult,
)
from flowsint_core.avl4_import.graph import Neo4jMaterialProjection
from flowsint_core.avl4_import.service import CardImportService, ImportRejected
from flowsint_core.avl4_import.signing import signature
from flowsint_core.core.platform_auth import (
    AccessDenied,
    SessionRejected,
    verify_actor_sync,
)
from flowsint_core.core.postgre_db import get_db
from flowsint_core.core.project_scope import ProjectScope, avl4_enabled, project_scope

router = APIRouter()


async def verified_command(request: Request) -> CardImportCommand:
    if not avl4_enabled():
        raise HTTPException(404, "Not found")
    key = os.getenv("FLOWSINT_CARDS_IMPORT_KEY", "")
    if len(key) < 32:
        raise HTTPException(503, "IMPORT_NOT_CONFIGURED")
    timestamp = request.headers.get("h-avl-cards-timestamp", "")
    proof = request.headers.get("h-avl-cards-signature", "")
    if (
        not timestamp.isascii()
        or not timestamp.isdigit()
        or len(timestamp) > 12
        or abs(time.time() - int(timestamp)) > 300
        or len(proof) != 64
        or any(char not in "0123456789abcdef" for char in proof)
    ):
        raise HTTPException(401, "SERVICE_SIGNATURE_REQUIRED")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(413, "CARD_SNAPSHOT_TOO_LARGE")
    if not hmac.compare_digest(signature(key, bytes(body), timestamp), proof):
        raise HTTPException(401, "SERVICE_SIGNATURE_REQUIRED")
    try:
        return CardImportCommand.model_validate_json(body)
    except ValidationError:
        raise HTTPException(422, "INVALID_CARD_IMPORT") from None


def get_import_graph(db: Session = Depends(get_db)) -> Neo4jMaterialProjection:
    return Neo4jMaterialProjection(db=db)


def apply_command(
    command: CardImportCommand, db: Session, graph: Neo4jMaterialProjection
) -> CardImportResult:
    # Fresh public Auth snapshots are also checked on retries of completed operations.
    verify_actor_sync(command.actor_id, command.project_id, command.private_project_id)
    scope = ProjectScope(
        command.actor_id,
        command.project_id,
        private_project_id=command.private_project_id,
        worker=True,
    )
    with project_scope(scope):
        return CardImportService(db, graph, os.getenv("FLOWSINT_UI_BASE_URL", "")).run(
            command
        )


@router.post(IMPORT_PATH, response_model=CardImportResult)
async def import_card(
    command: CardImportCommand = Depends(verified_command),
    db: Session = Depends(get_db),
    graph: Neo4jMaterialProjection = Depends(get_import_graph),
) -> CardImportResult:
    try:
        return await run_in_threadpool(apply_command, command, db, graph)
    except (AccessDenied, SessionRejected, PermissionError):
        raise HTTPException(403, "IMPORT_FORBIDDEN") from None
    except (RedisError, ImportError, OSError):
        raise HTTPException(503, "AUTH_UNAVAILABLE") from None
    except ImportRejected as exc:
        raise HTTPException(exc.status, exc.code) from None
