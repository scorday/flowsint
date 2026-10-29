from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from flowsint_core.core.services.sketch_service import SketchService


def test_failed_sql_commit_closes_only_new_view_and_keeps_canonical_graph(monkeypatch):
    db, sketches, investigations, graph = (MagicMock() for _ in range(4))
    service = SketchService(db, sketches, investigations)
    monkeypatch.setattr(service, "_check_permission", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        service, "_commit", MagicMock(side_effect=RuntimeError("commit failed"))
    )
    factory = MagicMock(return_value=graph)
    monkeypatch.setattr(
        "flowsint_core.core.services.sketch_service.create_graph_service", factory
    )
    with pytest.raises(RuntimeError, match="commit failed"):
        service.create(
            "new view", None, uuid4(), uuid4(), ["canonical-person"], ["canonical-edge"]
        )
    graph.attach_subgraph.assert_called_once_with(
        ["canonical-person"], ["canonical-edge"]
    )
    graph.delete_all_sketch_nodes.assert_called_once_with()
    graph.delete_investigation_graph.assert_not_called()
    db.rollback.assert_called_once_with()
    assert factory.call_args.kwargs["db"] is db


def test_blank_sketch_normalizes_optional_description():
    db, sketches, investigations = (MagicMock() for _ in range(3))
    service = SketchService(db, sketches, investigations)
    service._check_permission = MagicMock()
    result = service.create("blank", None, uuid4(), uuid4())
    assert result.description == ""
