from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import uuid4

from fastapi import HTTPException

from .artifact_storage import (
    ArtifactObjectStore,
    ArtifactStorageError,
    ArtifactStorageUnavailableError,
)
from .audit import append_event
from .models import (
    ArtifactAccessGrant,
    ArtifactRecord,
    EventType,
    InterviewSession,
)
from .storage import Store, StoreConflictError


class ArtifactService:
    """Session-scoped encrypted artifact lifecycle with signed access."""

    def __init__(
        self,
        *,
        store: Store,
        object_store: ArtifactObjectStore,
        signing_secret: bytes | None,
        max_artifact_bytes: int = 50 * 1024 * 1024,
        access_ttl_seconds: int = 300,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if max_artifact_bytes < 1:
            raise ValueError(
                "max_artifact_bytes must be positive"
            )
        if not 30 <= access_ttl_seconds <= 3600:
            raise ValueError(
                "access_ttl_seconds must be between 30 and 3600"
            )
        if (
            object_store.provider_id != "disabled"
            and (
                signing_secret is None
                or len(signing_secret) < 32
            )
        ):
            raise ValueError(
                "enabled artifact storage requires a signing secret "
                "of at least 32 bytes"
            )

        self.store = store
        self.object_store = object_store
        self.signing_secret = signing_secret
        self.max_artifact_bytes = max_artifact_bytes
        self.access_ttl_seconds = access_ttl_seconds
        self.now = now or (
            lambda: datetime.now(timezone.utc)
        )

    async def _session(
        self,
        session_id: str,
    ) -> InterviewSession:
        session = await self.store.get_session(
            session_id
        )
        if session is None:
            raise HTTPException(
                status_code=404,
                detail="Session not found",
            )
        return session

    @staticmethod
    def _artifact(
        session: InterviewSession,
        artifact_id: str,
    ) -> ArtifactRecord:
        artifact = next(
            (
                item
                for item in session.artifacts
                if item.id == artifact_id
            ),
            None,
        )
        if artifact is None:
            raise HTTPException(
                status_code=404,
                detail="Artifact not found",
            )
        return artifact

    async def _persist(
        self,
        session: InterviewSession,
    ) -> None:
        try:
            await self.store.put_session(session)
        except StoreConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Artifact state changed concurrently. "
                    "Reload and retry."
                ),
            ) from exc

    def _require_enabled(self) -> None:
        if self.object_store.provider_id == "disabled":
            raise HTTPException(
                status_code=503,
                detail="Artifact storage is disabled",
            )

    @staticmethod
    def _b64url(
        data: bytes,
    ) -> str:
        return (
            base64.urlsafe_b64encode(data)
            .rstrip(b"=")
            .decode("ascii")
        )

    @staticmethod
    def _b64url_decode(
        value: str,
    ) -> bytes:
        padding = "=" * (
            (-len(value)) % 4
        )
        return base64.urlsafe_b64decode(
            value + padding
        )

    def _sign(
        self,
        payload: dict,
    ) -> str:
        if self.signing_secret is None:
            raise ArtifactStorageUnavailableError(
                "Artifact signing is unavailable"
            )
        body = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        body_token = self._b64url(body)
        signature = hmac.new(
            self.signing_secret,
            body_token.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return (
            body_token
            + "."
            + self._b64url(signature)
        )

    def _verify(
        self,
        token: str,
    ) -> dict:
        if self.signing_secret is None:
            raise HTTPException(
                status_code=503,
                detail="Artifact signing is unavailable",
            )
        body_token, separator, signature_token = (
            token.partition(".")
        )
        if (
            not separator
            or not body_token
            or not signature_token
        ):
            raise HTTPException(
                status_code=401,
                detail="Artifact access token is invalid",
            )

        expected = hmac.new(
            self.signing_secret,
            body_token.encode("ascii"),
            hashlib.sha256,
        ).digest()
        try:
            supplied = self._b64url_decode(
                signature_token
            )
        except Exception as exc:
            raise HTTPException(
                status_code=401,
                detail="Artifact access token is invalid",
            ) from exc
        if not hmac.compare_digest(
            expected,
            supplied,
        ):
            raise HTTPException(
                status_code=401,
                detail="Artifact access token is invalid",
            )

        try:
            payload = json.loads(
                self._b64url_decode(
                    body_token
                )
            )
        except Exception as exc:
            raise HTTPException(
                status_code=401,
                detail="Artifact access token is invalid",
            ) from exc
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=401,
                detail="Artifact access token is invalid",
            )

        exp = payload.get("exp")
        if not isinstance(exp, int):
            raise HTTPException(
                status_code=401,
                detail="Artifact access token is invalid",
            )
        now_ts = int(
            self.now().timestamp()
        )
        if exp < now_ts:
            raise HTTPException(
                status_code=401,
                detail="Artifact access token has expired",
            )
        return payload

    async def create(
        self,
        session_id: str,
        *,
        data: bytes,
        kind: str,
        media_type: str,
        created_by: str,
    ) -> ArtifactRecord:
        self._require_enabled()
        kind = kind.strip()
        media_type = media_type.strip()
        if not kind or len(kind) > 120:
            raise HTTPException(
                status_code=422,
                detail="Artifact kind is invalid",
            )
        if not media_type or len(media_type) > 200:
            raise HTTPException(
                status_code=422,
                detail="Artifact media type is invalid",
            )
        if len(data) > self.max_artifact_bytes:
            raise HTTPException(
                status_code=413,
                detail="Artifact exceeds configured size limit",
            )

        session = await self._session(
            session_id
        )
        artifact_id = str(uuid4())
        scope = (
            session.organization_id
            or "unscoped"
        )
        storage_key = (
            f"{scope}/{session.id}/{artifact_id}"
        )
        digest = hashlib.sha256(
            data
        ).hexdigest()
        record = ArtifactRecord(
            id=artifact_id,
            storage_key=storage_key,
            kind=kind,
            media_type=media_type,
            size_bytes=len(data),
            sha256=digest,
            created_by=created_by,
        )

        try:
            await self.object_store.put(
                storage_key,
                data,
                content_type=media_type,
            )
        except ArtifactStorageError as exc:
            raise HTTPException(
                status_code=503,
                detail="Artifact storage write failed",
            ) from exc

        session.artifacts.append(record)
        append_event(
            session,
            EventType.ARTIFACT_CREATED,
            payload={
                "artifact_id": record.id,
                "kind": record.kind,
                "media_type": record.media_type,
                "size_bytes": record.size_bytes,
                "sha256": record.sha256,
                "created_by": created_by,
            },
        )
        try:
            await self._persist(session)
        except Exception:
            try:
                await self.object_store.delete(
                    storage_key
                )
            finally:
                raise
        return record

    async def list(
        self,
        session_id: str,
    ) -> list[ArtifactRecord]:
        session = await self._session(
            session_id
        )
        return [
            item
            for item in session.artifacts
            if item.deleted_at is None
        ]

    async def issue_access(
        self,
        session_id: str,
        artifact_id: str,
    ) -> ArtifactAccessGrant:
        self._require_enabled()
        session = await self._session(
            session_id
        )
        artifact = self._artifact(
            session,
            artifact_id,
        )
        if artifact.deleted_at is not None:
            raise HTTPException(
                status_code=404,
                detail="Artifact not found",
            )

        expires_at = self.now() + timedelta(
            seconds=self.access_ttl_seconds
        )
        token = self._sign({
            "v": 1,
            "session_id": session.id,
            "artifact_id": artifact.id,
            "exp": int(
                expires_at.timestamp()
            ),
        })
        return ArtifactAccessGrant(
            artifact_id=artifact.id,
            token=token,
            expires_at=expires_at,
        )

    async def read_token(
        self,
        token: str,
    ) -> tuple[ArtifactRecord, bytes]:
        self._require_enabled()
        payload = self._verify(token)
        session_id = payload.get(
            "session_id"
        )
        artifact_id = payload.get(
            "artifact_id"
        )
        if (
            not isinstance(session_id, str)
            or not isinstance(artifact_id, str)
        ):
            raise HTTPException(
                status_code=401,
                detail="Artifact access token is invalid",
            )

        session = await self._session(
            session_id
        )
        artifact = self._artifact(
            session,
            artifact_id,
        )
        if artifact.deleted_at is not None:
            raise HTTPException(
                status_code=404,
                detail="Artifact not found",
            )

        try:
            data = await self.object_store.get(
                artifact.storage_key
            )
        except ArtifactStorageError as exc:
            raise HTTPException(
                status_code=503,
                detail="Artifact storage read failed",
            ) from exc

        if (
            hashlib.sha256(data).hexdigest()
            != artifact.sha256
        ):
            raise HTTPException(
                status_code=500,
                detail="Artifact integrity verification failed",
            )

        append_event(
            session,
            EventType.ARTIFACT_ACCESSED,
            payload={
                "artifact_id": artifact.id,
                "access_method": "signed_token",
            },
        )
        await self._persist(session)
        return artifact, data

    async def delete(
        self,
        session_id: str,
        artifact_id: str,
        *,
        deleted_by: str,
        reason: str | None = None,
    ) -> ArtifactRecord:
        self._require_enabled()
        session = await self._session(
            session_id
        )
        artifact = self._artifact(
            session,
            artifact_id,
        )
        if artifact.deleted_at is not None:
            return artifact

        try:
            await self.object_store.delete(
                artifact.storage_key
            )
        except ArtifactStorageError as exc:
            raise HTTPException(
                status_code=503,
                detail="Artifact storage deletion failed",
            ) from exc

        artifact.deleted_at = self.now()
        artifact.deleted_by = deleted_by
        artifact.deletion_reason = reason
        append_event(
            session,
            EventType.ARTIFACT_DELETED,
            payload={
                "artifact_id": artifact.id,
                "deleted_by": deleted_by,
                "reason": reason,
            },
        )
        await self._persist(session)
        return artifact

    async def purge_session(
        self,
        session_id: str,
        *,
        deleted_by: str = "retention",
        reason: str = "session_retention",
    ) -> int:
        self._require_enabled()
        session = await self._session(
            session_id
        )
        active = [
            item
            for item in session.artifacts
            if item.deleted_at is None
        ]

        for artifact in active:
            try:
                await self.object_store.delete(
                    artifact.storage_key
                )
            except ArtifactStorageError as exc:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Artifact storage retention deletion failed"
                    ),
                ) from exc

        deleted_at = self.now()
        for artifact in active:
            artifact.deleted_at = deleted_at
            artifact.deleted_by = deleted_by
            artifact.deletion_reason = reason
            append_event(
                session,
                EventType.ARTIFACT_DELETED,
                payload={
                    "artifact_id": artifact.id,
                    "deleted_by": deleted_by,
                    "reason": reason,
                },
            )

        if active:
            await self._persist(session)
        return len(active)
