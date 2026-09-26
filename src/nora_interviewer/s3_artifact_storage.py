from __future__ import annotations

import asyncio
from typing import Any

from .artifact_storage import (
    ArtifactNotFoundError,
    ArtifactStorageError,
    ArtifactStorageUnavailableError,
)


class S3ArtifactObjectStore:
    """S3-compatible object store with required server-side encryption."""

    provider_id = "s3"
    encrypted_at_rest = True

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "",
        region: str | None = None,
        endpoint_url: str | None = None,
        sse_mode: str = "AES256",
        kms_key_id: str | None = None,
    ) -> None:
        try:
            import boto3
            from botocore.exceptions import (
                BotoCoreError,
                ClientError,
            )
        except ImportError as exc:
            raise RuntimeError(
                "S3 artifact storage requires the 's3' extra: "
                "pip install -e '.[s3]'"
            ) from exc

        bucket = bucket.strip()
        if not bucket:
            raise ValueError("S3 artifact bucket is required")

        normalized_sse = sse_mode.strip()
        if normalized_sse not in {"AES256", "aws:kms"}:
            raise ValueError(
                "S3 artifact SSE mode must be AES256 or aws:kms"
            )
        if normalized_sse == "aws:kms" and not (
            kms_key_id
            and kms_key_id.strip()
        ):
            raise ValueError(
                "S3 artifact KMS key id is required for aws:kms"
            )

        self.bucket = bucket
        self.prefix = prefix.strip().strip("/")
        self.region = region.strip() if region else None
        self.endpoint_url = (
            endpoint_url.strip().rstrip("/")
            if endpoint_url
            else None
        )
        self.sse_mode = normalized_sse
        self.kms_key_id = (
            kms_key_id.strip()
            if kms_key_id
            else None
        )
        self._client_error = ClientError
        self._boto_core_error = BotoCoreError
        self._client = boto3.client(
            "s3",
            region_name=self.region,
            endpoint_url=self.endpoint_url,
        )

    def _object_key(
        self,
        key: str,
    ) -> str:
        normalized = key.lstrip("/")
        if not normalized:
            raise ValueError(
                "artifact object key is required"
            )
        if self.prefix:
            return (
                self.prefix
                + "/"
                + normalized
            )
        return normalized

    def _put_sync(
        self,
        key: str,
        data: bytes,
        content_type: str,
    ) -> None:
        kwargs: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": self._object_key(key),
            "Body": data,
            "ContentType": content_type,
            "ServerSideEncryption": (
                self.sse_mode
            ),
        }
        if self.sse_mode == "aws:kms":
            kwargs[
                "SSEKMSKeyId"
            ] = self.kms_key_id

        try:
            self._client.put_object(
                **kwargs
            )
        except (
            self._client_error,
            self._boto_core_error,
        ) as exc:
            raise ArtifactStorageUnavailableError(
                "S3 artifact write failed"
            ) from exc

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
    ) -> None:
        await asyncio.to_thread(
            self._put_sync,
            key,
            data,
            content_type,
        )

    def _get_sync(
        self,
        key: str,
    ) -> bytes:
        try:
            response = self._client.get_object(
                Bucket=self.bucket,
                Key=self._object_key(key),
            )
        except self._client_error as exc:
            error = (
                exc.response
                .get("Error", {})
                .get("Code", "")
            )
            if error in {
                "NoSuchKey",
                "404",
                "NotFound",
            }:
                raise ArtifactNotFoundError(
                    f"Artifact object {key!r} was not found"
                ) from exc
            raise ArtifactStorageUnavailableError(
                "S3 artifact read failed"
            ) from exc
        except self._boto_core_error as exc:
            raise ArtifactStorageUnavailableError(
                "S3 artifact read failed"
            ) from exc

        body = response.get("Body")
        if body is None:
            raise ArtifactStorageError(
                "S3 artifact response did not contain a body"
            )
        try:
            return body.read()
        except Exception as exc:
            raise ArtifactStorageUnavailableError(
                "S3 artifact body read failed"
            ) from exc
        finally:
            close = getattr(
                body,
                "close",
                None,
            )
            if callable(close):
                close()

    async def get(
        self,
        key: str,
    ) -> bytes:
        return await asyncio.to_thread(
            self._get_sync,
            key,
        )

    def _delete_sync(
        self,
        key: str,
    ) -> None:
        try:
            self._client.delete_object(
                Bucket=self.bucket,
                Key=self._object_key(key),
            )
        except (
            self._client_error,
            self._boto_core_error,
        ) as exc:
            raise ArtifactStorageUnavailableError(
                "S3 artifact deletion failed"
            ) from exc

    async def delete(
        self,
        key: str,
    ) -> None:
        await asyncio.to_thread(
            self._delete_sync,
            key,
        )
