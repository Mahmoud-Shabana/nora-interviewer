from __future__ import annotations

import re
from contextvars import ContextVar, Token
from uuid import uuid4


_CORRELATION_ID = ContextVar[
    str | None
](
    "nora_correlation_id",
    default=None,
)

_ALLOWED = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,63}$"
)


def new_correlation_id(
    *,
    prefix: str = "req",
) -> str:
    return f"{prefix}_{uuid4().hex}"


def resolve_correlation_id(
    value: str | None,
    *,
    prefix: str = "req",
) -> str:
    """Accept a bounded safe upstream ID or generate a Nora-owned one."""

    candidate = (value or "").strip()
    if _ALLOWED.fullmatch(candidate):
        return candidate
    return new_correlation_id(
        prefix=prefix,
    )


def set_correlation_id(
    correlation_id: str,
) -> Token:
    return _CORRELATION_ID.set(
        correlation_id
    )


def reset_correlation_id(
    token: Token,
) -> None:
    _CORRELATION_ID.reset(token)


def current_correlation_id() -> str | None:
    return _CORRELATION_ID.get()
