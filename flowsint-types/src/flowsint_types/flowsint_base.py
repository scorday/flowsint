from typing import Any, Optional, Self, cast

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator


class FlowsintType(BaseModel):
    """Base class for all Flowsint entity types with nodeLabel support.
    nodeLabel is optional but computed at definition time.

    All classes that inherit from FlowsintType must be decorated with @flowsint_type
    to be registered in the global TYPE_REGISTRY and accessed by their class name.

    Usage:
        from flowsint_types.registry import flowsint_type

        @flowsint_type
        class Domain(FlowsintType):
            domain: str
    """

    # Runtime graph identity is separate from a domain ID (e.g. username@vk).
    # It survives model_copy during enrichment but is never a public property.
    _graph_uid: Optional[str] = PrivateAttr(default=None)

    @model_validator(mode="wrap")
    @classmethod
    def restore_task_graph_identity(cls, value: Any, handler: Any) -> Self:
        """Carry canonical identity through trusted task JSON, separately from id.

        The repository always resolves this hint inside its checked scope;
        neither this hint nor an input property can change graph ownership.
        """
        uid = None
        if isinstance(value, dict) and "_graph_uid" in value:
            value = dict(value)
            uid = value.pop("_graph_uid")
            if uid is not None and (
                not isinstance(uid, str) or not 0 < len(uid) <= 512
            ):
                raise ValueError("Invalid graph identity")
        result = handler(value)
        if uid is not None:
            result._graph_uid = uid
        return cast(Self, result)

    def task_dump(self) -> dict[str, Any]:
        data = self.model_dump(mode="json", serialize_as_any=True)
        if self._graph_uid:
            data["_graph_uid"] = self._graph_uid
        return data

    nodeLabel: Optional[str] = Field(
        None,
        description="UI-readable label for this entity, the one used on the graph.",
        title="Label",
    )

    # Allow extra keys to support additional properties from the user
    model_config = ConfigDict(extra="allow")
