"""Loopback-only browser verification fixture using synthetic data.

Start with uvicorn browser_fixture:app, adding this directory to PYTHONPATH.
No production routes/authentication are replaced. Requires an explicitly
created temporary SQLite file and the disposable test Neo4j on port 17687.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

if (
    os.getenv("FLOWSINT_AUTH_MODE") != "standalone"
    or not os.getenv("DATABASE_URL", "").startswith(
        "sqlite:////private/tmp/flowsint-graph-browser-"
    )
    or os.getenv("NEO4J_URI_BOLT") != "bolt://127.0.0.1:17687"
):
    raise RuntimeError("Browser fixture requires isolated temporary storage")

from app.main import app  # noqa: E402,F401
from flowsint_core.core.auth import get_password_hash  # noqa: E402
from flowsint_core.core.graph import create_graph_service  # noqa: E402
from flowsint_core.core.graph.connection import Neo4jConnection  # noqa: E402
from flowsint_core.core.graph.schema import install_schema  # noqa: E402
from flowsint_core.core.models import (  # noqa: E402
    Base,
    Investigation,
    InvestigationUserRole,
    Profile,
    Sketch,
)
from flowsint_core.core.postgre_db import SessionLocal, engine  # noqa: E402
from flowsint_core.core.types import Role  # noqa: E402

Base.metadata.create_all(engine)
install_schema(Neo4jConnection.get_instance())
with SessionLocal() as db:
    user = db.query(Profile).filter(Profile.email == "graph-ui@example.com").first()
    if user is None:
        user = Profile(
            id=uuid4(),
            email="graph-ui@example.com",
            hashed_password=get_password_hash(os.environ["GRAPH_BROWSER_PASSWORD"]),
        )
        db.add(user)
        db.flush()
        case = Investigation(
            id=uuid4(),
            name="Graph verification",
            description="Synthetic browser verification",
            owner_id=user.id,
        )
        db.add(case)
        db.flush()
        db.add(
            InvestigationUserRole(
                user_id=user.id, investigation_id=case.id, roles=[Role.OWNER]
            )
        )
        friends = Sketch(
            id=uuid4(),
            title="Friends",
            description="Friends subgraph",
            investigation_id=case.id,
            owner_id=user.id,
        )
        work = Sketch(
            id=uuid4(),
            title="Work",
            description="Work subgraph",
            investigation_id=case.id,
            owner_id=user.id,
        )
        db.add_all([friends, work])
        db.commit()
        source = create_graph_service(str(friends.id), enable_batching=False).repository
        stamp = datetime.now(timezone.utc).isoformat()
        alice = source.create_node(
            {
                "nodeType": "socialaccount",
                "nodeLabel": "Alice VK",
                "nodeProperties.username.value": "id123",
                "nodeProperties.platform": "vk.ru",
                "nodeProperties.profile_url": "https://vk.ru/id123",
                "nodeProperties.display_name": "Alice",
                "nodeMetadata.created_at": stamp,
                "nodeProperties.bio": "Initial observation",
                "x": 120,
                "y": 140,
            },
            str(friends.id),
        )
        bob = source.create_node(
            {
                "nodeType": "socialaccount",
                "nodeLabel": "Bob VK",
                "nodeProperties.username.value": "id456",
                "nodeProperties.platform": "vk.ru",
                "nodeProperties.display_name": "Bob",
                "nodeMetadata.created_at": stamp,
                "x": 320,
                "y": 140,
            },
            str(friends.id),
        )
        company = source.create_node(
            {
                "nodeType": "organization",
                "nodeLabel": "Acme",
                "nodeProperties.name": "Acme",
                "nodeProperties.siren": "123456789",
                "nodeMetadata.created_at": stamp,
            },
            str(friends.id),
        )
        friendship = source.create_relationship_by_element_id(
            alice, bob, "FRIEND_OF", str(friends.id)
        )
        employment = source.create_relationship_by_element_id(
            alice, company, "WORKS_AT", str(friends.id)
        )
        source.delete_nodes([company], str(friends.id))
        target = create_graph_service(str(work.id), enable_batching=False).repository
        target.attach_subgraph([company], [employment["id"]], str(work.id))
        metadata = {
            "investigation": str(case.id),
            "friends": str(friends.id),
            "work": str(work.id),
            "alice": alice,
            "bob": bob,
            "company": company,
            "friendship": friendship["id"],
            "employment": employment["id"],
        }
        destination = Path(os.environ["GRAPH_BROWSER_METADATA"])
        destination.write_text(json.dumps(metadata))
        destination.chmod(0o600)
