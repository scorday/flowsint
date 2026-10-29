"""
Investigation service for managing investigations and user roles.
"""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from ..models import Investigation, InvestigationUserRole, Sketch
from ..project_scope import ActorID, current_scope
from ..repositories import (
    AnalysisRepository,
    InvestigationRepository,
    ProfileRepository,
    SketchRepository,
)
from ..types import Role
from .base import BaseService
from .exceptions import (
    ConflictError,
    DatabaseError,
    NotFoundError,
    PermissionDeniedError,
)


class InvestigationService(BaseService):
    """
    Service for investigation CRUD operations and role management.
    """

    def __init__(
        self,
        db: Session,
        investigation_repo: InvestigationRepository,
        sketch_repo: SketchRepository,
        analysis_repo: AnalysisRepository,
        profile_repo: ProfileRepository,
        **kwargs,
    ):
        super().__init__(db, **kwargs)
        self._investigation_repo = investigation_repo
        self._sketch_repo = sketch_repo
        self._analysis_repo = analysis_repo
        self._profile_repo = profile_repo

    def get_accessible_investigations(
        self, user_id: ActorID, allowed_roles: Optional[List[Role]] = None
    ) -> List[Investigation]:
        return self._investigation_repo.get_accessible_by_user(user_id, allowed_roles)

    def get_by_id(self, investigation_id: UUID, user_id: ActorID) -> Investigation:
        self._check_permission(user_id, investigation_id, actions=["read"])

        investigation = self._investigation_repo.get_with_relations(investigation_id)
        if not investigation:
            raise NotFoundError("Investigation not found")
        return investigation

    def get_sketches(self, investigation_id: UUID, user_id: ActorID) -> List[Sketch]:
        self._check_permission(user_id, investigation_id, actions=["read"])

        return self._sketch_repo.get_by_investigation(investigation_id)

    def create(
        self, name: str, description: Optional[str], owner_id: ActorID
    ) -> Investigation:
        new_investigation = Investigation(
            id=uuid4(),
            name=name,
            description=description or name,
            owner_id=owner_id,
            status="active",
        )
        self._investigation_repo.add(new_investigation)

        if current_scope():
            self._commit()
            self._refresh(new_investigation)
            return new_investigation

        new_roles = InvestigationUserRole(
            id=uuid4(),
            user_id=owner_id,
            investigation_id=new_investigation.id,
            roles=[Role.OWNER],
        )
        self._investigation_repo.add_user_role(new_roles)

        self._commit()
        self._refresh(new_investigation)

        return new_investigation

    def update(
        self,
        investigation_id: UUID,
        user_id: ActorID,
        name: str,
        description: str,
        status: str,
    ) -> Investigation:
        self._check_permission(user_id, investigation_id, actions=["update"])

        investigation = self._investigation_repo.get_by_id(investigation_id)
        if not investigation:
            raise NotFoundError("Investigation not found")

        investigation.name = name
        investigation.description = description
        investigation.status = status
        investigation.last_updated_at = datetime.now(timezone.utc)

        self._commit()
        self._refresh(investigation)
        return investigation

    def delete(self, investigation_id: UUID, user_id: ActorID) -> None:
        self._check_permission(user_id, investigation_id, actions=["delete"])

        investigation = self._investigation_repo.get_by_id_and_owner(
            investigation_id, user_id
        )
        if not investigation:
            raise NotFoundError("Investigation not found")

        sketches = self._sketch_repo.get_by_investigation(investigation_id)
        analyses = self._analysis_repo.get_by_investigation(investigation_id)

        # Hidden entities also belong to the investigation. Removing its views
        # alone would leave canonical data behind.
        from ..graph.identity import GraphScope
        from ..graph.repository import Neo4jGraphRepository

        try:
            repository = Neo4jGraphRepository(
                scope=GraphScope(
                    investigation.project_id,
                    str(investigation_id),
                    tuple(str(s.id) for s in sketches),
                )
            )
            repository.delete_investigation_graph(
                str(sketches[0].id) if sketches else ""
            )
        except Exception as exc:
            raise DatabaseError("Failed to clean up investigation graph") from exc

        for sketch in sketches:
            self._sketch_repo.delete(sketch)
        for analysis in analyses:
            self._analysis_repo.delete(analysis)

        self._investigation_repo.delete(investigation)
        self._commit()

    # ── Collaborator management ──────────────────────────────────────────

    def get_user_role_for_investigation(
        self, user_id: ActorID, investigation_id: UUID
    ) -> Optional[InvestigationUserRole]:
        return self._investigation_repo.get_user_role(user_id, investigation_id)

    def get_collaborators(
        self, investigation_id: UUID, user_id: ActorID
    ) -> List[InvestigationUserRole]:
        self._check_permission(user_id, investigation_id, actions=["read"])
        return self._investigation_repo.get_collaborators(investigation_id)

    def add_collaborator(
        self,
        investigation_id: UUID,
        user_id: ActorID,
        target_email: str,
        role: Role,
    ) -> InvestigationUserRole:
        self._check_permission(user_id, investigation_id, actions=["manage"])

        # Verify investigation exists
        investigation = self._investigation_repo.get_by_id(investigation_id)
        if not investigation:
            raise NotFoundError("Investigation not found")

        # Cannot assign OWNER role
        if role == Role.OWNER:
            raise PermissionDeniedError("Cannot assign owner role")

        # Look up target user by email
        target_user = self._profile_repo.get_by_email(target_email)
        if not target_user:
            raise NotFoundError("User not found")

        # Check if already a collaborator
        existing = self._investigation_repo.get_user_role(
            target_user.id, investigation_id
        )
        if existing:
            raise ConflictError("User is already a collaborator")

        role_entry = InvestigationUserRole(
            id=uuid4(),
            user_id=target_user.id,
            investigation_id=investigation_id,
            roles=[role],
        )
        self._investigation_repo.add_user_role(role_entry)
        self._commit()
        self._db.refresh(role_entry)
        return role_entry

    def update_collaborator_role(
        self,
        investigation_id: UUID,
        user_id: ActorID,
        target_user_id: UUID,
        role: Role,
    ) -> InvestigationUserRole:
        self._check_permission(user_id, investigation_id, actions=["manage"])

        if role == Role.OWNER:
            raise PermissionDeniedError("Cannot assign owner role")

        existing = self._investigation_repo.get_user_role(
            target_user_id, investigation_id
        )
        if not existing:
            raise NotFoundError("Collaborator not found")

        # Cannot change the owner's role
        if Role.OWNER in existing.roles:
            raise PermissionDeniedError("Cannot change owner role")

        entry = self._investigation_repo.update_user_role(
            target_user_id, investigation_id, [role]
        )
        self._commit()
        self._db.refresh(entry)
        return entry

    def remove_collaborator(
        self,
        investigation_id: UUID,
        user_id: ActorID,
        target_user_id: UUID,
    ) -> None:
        self._check_permission(user_id, investigation_id, actions=["manage"])

        existing = self._investigation_repo.get_user_role(
            target_user_id, investigation_id
        )
        if not existing:
            raise NotFoundError("Collaborator not found")

        if Role.OWNER in existing.roles:
            raise PermissionDeniedError("Cannot remove owner")

        self._investigation_repo.remove_user_role(target_user_id, investigation_id)
        self._commit()


def create_investigation_service(db: Session) -> InvestigationService:
    investigation_repo = InvestigationRepository(db)
    return InvestigationService(
        db=db,
        investigation_repo=investigation_repo,
        sketch_repo=SketchRepository(db),
        analysis_repo=AnalysisRepository(db),
        profile_repo=ProfileRepository(db),
    )
