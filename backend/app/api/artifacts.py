"""Artifact reads. Artifacts are persisted by the chat turn that created them."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import DbSession
from app.api.serializers import artifact_to_response
from app.db.models import Artifact
from app.errors import NotFoundError
from app.schemas import ArtifactResponse

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(artifact_id: uuid.UUID, db: DbSession) -> ArtifactResponse:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise NotFoundError(
            f"Artifact {artifact_id} does not exist.", details={"artifact_id": str(artifact_id)}
        )
    return artifact_to_response(artifact)
