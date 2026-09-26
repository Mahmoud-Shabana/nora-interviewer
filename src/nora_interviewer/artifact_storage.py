from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from typing import Protocol


class ArtifactStorageError(RuntimeError):
    pass


class ArtifactStorageUnavailableError(ArtifactStorageError):
    pass


class ArtifactNotFoundError(ArtifactStorageError):
    pass


class ArtifactObjectStore(Protocol):
    encrypted_at_rest: bool
    provider_id: str

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
    ) -> None: ...

    async def get(
        self,
        key: str,
    ) -> bytes: ...

    async def delete(
        self,
        key: str,
    ) -> None: ...


class DisabledArtifactObjectStore:
    provider_id = "disabled"
    encrypted_at_rest = False

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
    ) -> None:
        raise ArtifactStorageUnavailableError(
            "Artifact storage is disabled"
        )

    async def get(
        self,
        key: str,
    ) -> bytes:
        raise ArtifactStorageUnavailableError(
            "Artifact storage is disabled"
        )

    async def delete(
        self,
        key: str,
    ) -> None:
        raise ArtifactStorageUnavailableError(
            "Artifact storage is disabled"
        )


class EncryptedLocalArtifactObjectStore:
    """Filesystem-backed object store encrypted with AES-256-GCM.

    Storage keys are hashed before becoming filenames so callers cannot
    influence filesystem paths. The raw encryption key is supplied by the
    deployment and is never persisted beside ciphertext.
    """

    provider_id = "encrypted-local"
    encrypted_at_rest = True
    _magic = b"NORAOBJ1"
    _nonce_size = 12

    def __init__(
        self,
        root: str | Path,
        *,
        encryption_key: bytes,
        key_id: str = "primary",
    ) -> None:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import (
                AESGCM,
            )
        except ImportError as exc:
            raise RuntimeError(
                "Encrypted artifact storage requires the 'artifacts' extra: "
                "pip install -e '.[artifacts]'"
            ) from exc

        if len(encryption_key) != 32:
            raise ValueError(
                "artifact encryption key must be exactly 32 bytes"
            )
        key_id = key_id.strip()
        if not key_id:
            raise ValueError("artifact encryption key id is required")

        self.root = Path(root)
        self.root.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.key_id = key_id
        self._aesgcm = AESGCM(encryption_key)

    @staticmethod
    def _associated_data(
        key: str,
        content_type: str = "",
    ) -> bytes:
        return (
            "nora-artifact-v1\n"
            + key
            + "\n"
            + content_type
        ).encode("utf-8")

    def _path_for(
        self,
        key: str,
    ) -> Path:
        digest = hashlib.sha256(
            key.encode("utf-8")
        ).hexdigest()
        return self.root / digest[:2] / digest[2:]

    def _put_sync(
        self,
        key: str,
        data: bytes,
        content_type: str,
    ) -> None:
        path = self._path_for(key)
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        nonce = os.urandom(self._nonce_size)
        aad = self._associated_data(
            key,
            content_type,
        )
        ciphertext = self._aesgcm.encrypt(
            nonce,
            data,
            aad,
        )
        content_type_bytes = content_type.encode("utf-8")
        if len(content_type_bytes) > 65535:
            raise ValueError(
                "artifact content type is too long"
            )
        payload = (
            self._magic
            + len(content_type_bytes).to_bytes(2, "big")
            + content_type_bytes
            + nonce
            + ciphertext
        )
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(payload)
        os.replace(
            temporary,
            path,
        )

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
        path = self._path_for(key)
        if not path.exists():
            raise ArtifactNotFoundError(
                f"Artifact object {key!r} was not found"
            )
        payload = path.read_bytes()
        minimum = (
            len(self._magic)
            + 2
            + self._nonce_size
            + 16
        )
        if len(payload) < minimum or not payload.startswith(
            self._magic
        ):
            raise ArtifactStorageError(
                "Artifact ciphertext envelope is invalid"
            )

        cursor = len(self._magic)
        content_type_size = int.from_bytes(
            payload[cursor:cursor + 2],
            "big",
        )
        cursor += 2
        content_type_end = (
            cursor
            + content_type_size
        )
        nonce_end = (
            content_type_end
            + self._nonce_size
        )
        if nonce_end + 16 > len(payload):
            raise ArtifactStorageError(
                "Artifact ciphertext envelope is truncated"
            )

        content_type = payload[
            cursor:content_type_end
        ].decode("utf-8")
        nonce = payload[
            content_type_end:nonce_end
        ]
        ciphertext = payload[nonce_end:]
        aad = self._associated_data(
            key,
            content_type,
        )
        try:
            return self._aesgcm.decrypt(
                nonce,
                ciphertext,
                aad,
            )
        except Exception as exc:
            raise ArtifactStorageError(
                "Artifact ciphertext authentication failed"
            ) from exc

    async def get(
        self,
        key: str,
    ) -> bytes:
        return await asyncio.to_thread(
            self._get_sync,
            key,
        )

    async def delete(
        self,
        key: str,
    ) -> None:
        path = self._path_for(key)

        def remove() -> None:
            try:
                path.unlink()
            except FileNotFoundError:
                return

        await asyncio.to_thread(remove)
