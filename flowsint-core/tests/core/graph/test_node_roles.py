"""Roles describe a sketch membership, independently of shared entity data."""

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from flowsint_core.core.graph import (
    GraphNode,
    GraphSerializer,
    GraphService,
    NodeMetadata,
)
from flowsint_core.core.graph.identity import split_properties
from flowsint_types import Domain


def test_role_is_view_presentation_not_shared_entity_data():
    entity, presentation = split_properties(
        {
            "nodeType": "domain",
            "nodeRole": "secondary",
            "nodeProperties.domain": "a.org",
        }
    )
    assert "nodeRole" not in entity
    assert presentation == {"nodeRole": "secondary"}


@pytest.mark.parametrize("role", ["primary", "secondary", None])
def test_loading_roles_and_legacy_memberships(role):
    data = {
        "nodeType": "domain",
        "nodeLabel": "a.org",
        "nodeProperties.domain": "a.org",
    }
    if role is not None:
        data["nodeRole"] = role
    node = GraphSerializer.neo4j_dict_to_graph_node(
        {"id": "canonical-id", "data": data}
    )
    assert node.nodeRole == (role or "primary")
    assert node.id == "canonical-id"


def test_manual_creation_is_primary_and_enricher_creation_is_secondary():
    repository = MagicMock()
    service = GraphService("view", repository)
    domain = Domain(domain="a.org")
    service.create_node(
        GraphNode(
            id=None,
            nodeType="domain",
            nodeLabel="a.org",
            nodeProperties=domain,
            nodeMetadata=NodeMetadata(),
            nodeRole="secondary",
        )
    )
    assert repository.create_node.call_args.kwargs["node_obj"]["nodeRole"] == "primary"
    service.create_node_from_flowsint_type(domain)
    assert (
        repository.create_node.call_args.kwargs["node_obj"]["nodeRole"] == "secondary"
    )


def test_invalid_node_role_is_rejected():
    with pytest.raises(ValueError, match="nodeRole"):
        split_properties({"nodeRole": "unknown"})
    with pytest.raises(ValidationError):
        GraphNode(
            id=None,
            nodeType="domain",
            nodeLabel="a.org",
            nodeProperties={},
            nodeMetadata=NodeMetadata(),
            nodeRole="unknown",
        )
