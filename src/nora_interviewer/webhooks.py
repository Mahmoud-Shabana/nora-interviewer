from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Iterable

import httpx

from .audit import append_event
from .models import EventType, InterviewEvent, InterviewSession
from .storage import Store

_WEBHOOK_SAFE_EVENT_TYPES = {
    EventType.SESSION_CREATED,
    EventType.INTERVIEW_STARTED,
    EventType.APPEAL_SUBMITTED,
    EventType.APPEAL_REVIEWED,
    EventType.REVIEW_ASSIGNED,
    EventType.REVIEW_STARTED,
    EventType.REVIEW_COMPLETED,
    EventType.REVIEW_ASSIGNMENT_CANCELLED,
    EventType.TOOL_OPENED,
    EventType.TOOL_SUBMITTED,
    EventType.TOOL_EVALUATED,
    EventType.TOOL_CANCELLED,
    EventType.ARTIFACT_CREATED,
    EventType.ARTIFACT_DELETED,
    EventType.SESSION_COMPLETED,
    EventType.SESSION_CANCELLED,
}


@dataclass(frozen=True)
class WebhookSubscription:
    id: str
    url: str
    secret: bytes
    organization_id: str | None = None
    event_types: frozenset[EventType] = frozenset(
        _WEBHOOK_SAFE_EVENT_TYPES
    )

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("webhook subscription id is required")
        if not self.url.startswith(("https://", "http://")):
            raise ValueError("webhook URL must use http:// or https://")
        if len(self.secret) < 32:
            raise ValueError(
                "webhook signing secret must be at least 32 bytes"
            )
        unsafe = set(self.event_types) - _WEBHOOK_SAFE_EVENT_TYPES
        if unsafe:
            raise ValueError(
                "webhook subscription requested unsafe event types: "
                + ", ".join(sorted(item.value for item in unsafe))
            )


@dataclass(frozen=True)
class WebhookDeliveryResult:
    subscription_id: str
    event_seq: int
    event_type: str
    delivered: bool
    attempts: int
    status_code: int | None = None
    error_type: str | None = None


class WebhookDispatcher:
    def __init__(
        self,
        subscriptions: Iterable[WebhookSubscription],
        *,
        timeout_seconds: float = 8.0,
        max_attempts: int = 3,
        retry_base_seconds: float = 0.25,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("webhook timeout must be positive")
        if not 1 <= max_attempts <= 5:
            raise ValueError("webhook max_attempts must be between 1 and 5")
        if retry_base_seconds < 0 or retry_base_seconds > 5:
            raise ValueError(
                "webhook retry base must be between 0 and 5 seconds"
            )
        self.subscriptions = tuple(subscriptions)
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.retry_base_seconds = retry_base_seconds

    @staticmethod
    def _payload(
        session: InterviewSession,
        event: InterviewEvent,
        subscription: WebhookSubscription,
    ) -> dict:
        return {
            "schema": "nora.webhook.v1",
            "subscription_id": subscription.id,
            "organization_id": session.organization_id,
            "session_id": session.id,
            "event": {
                "seq": event.seq,
                "type": event.type.value,
                "created_at": event.created_at.isoformat(),
                "event_hash": event.event_hash,
            },
        }

    @staticmethod
    def _encode(payload: dict) -> bytes:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _signature(
        secret: bytes,
        body: bytes,
    ) -> str:
        digest = hmac.new(
            secret,
            body,
            hashlib.sha256,
        ).hexdigest()
        return "sha256=" + digest

    async def _deliver_one(
        self,
        *,
        session: InterviewSession,
        event: InterviewEvent,
        subscription: WebhookSubscription,
    ) -> WebhookDeliveryResult:
        payload = self._payload(
            session,
            event,
            subscription,
        )
        body = self._encode(payload)
        idempotency_key = (
            f"nora:{subscription.id}:{session.id}:{event.seq}"
        )
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "nora-interviewer-webhooks/1",
            "X-Nora-Webhook-Signature": self._signature(
                subscription.secret,
                body,
            ),
            "X-Nora-Webhook-Event": event.type.value,
            "X-Nora-Webhook-Idempotency-Key": idempotency_key,
        }

        last_status: int | None = None
        last_error: str | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds,
                ) as client:
                    response = await client.post(
                        subscription.url,
                        content=body,
                        headers=headers,
                    )
                last_status = response.status_code
                if 200 <= response.status_code < 300:
                    return WebhookDeliveryResult(
                        subscription_id=subscription.id,
                        event_seq=event.seq,
                        event_type=event.type.value,
                        delivered=True,
                        attempts=attempt,
                        status_code=response.status_code,
                    )
                retryable = (
                    response.status_code in {408, 409, 425, 429}
                    or response.status_code >= 500
                )
                if not retryable:
                    return WebhookDeliveryResult(
                        subscription_id=subscription.id,
                        event_seq=event.seq,
                        event_type=event.type.value,
                        delivered=False,
                        attempts=attempt,
                        status_code=response.status_code,
                    )
            except (
                httpx.TimeoutException,
                httpx.RequestError,
            ) as exc:
                last_error = type(exc).__name__

            if attempt < self.max_attempts:
                await asyncio.sleep(
                    self.retry_base_seconds
                    * (2 ** (attempt - 1))
                )

        return WebhookDeliveryResult(
            subscription_id=subscription.id,
            event_seq=event.seq,
            event_type=event.type.value,
            delivered=False,
            attempts=self.max_attempts,
            status_code=last_status,
            error_type=last_error,
        )

    async def dispatch(
        self,
        *,
        session: InterviewSession,
        events: Iterable[InterviewEvent],
    ) -> list[WebhookDeliveryResult]:
        results: list[WebhookDeliveryResult] = []

        for event in events:
            if event.type not in _WEBHOOK_SAFE_EVENT_TYPES:
                continue

            for subscription in self.subscriptions:
                if (
                    subscription.organization_id is not None
                    and subscription.organization_id
                    != session.organization_id
                ):
                    continue
                if event.type not in subscription.event_types:
                    continue

                results.append(
                    await self._deliver_one(
                        session=session,
                        event=event,
                        subscription=subscription,
                    )
                )

        return results


class WebhookDispatchingStore:
    """Store decorator that emits privacy-minimized webhooks after session saves."""

    def __init__(
        self,
        inner: Store,
        dispatcher: WebhookDispatcher,
    ) -> None:
        self.inner = inner
        self.dispatcher = dispatcher

    async def put_job(self, job):
        return await self.inner.put_job(job)

    async def get_job(self, job_id):
        return await self.inner.get_job(job_id)

    async def put_rubric_draft(self, draft):
        return await self.inner.put_rubric_draft(draft)

    async def get_rubric_draft(self, draft_id):
        return await self.inner.get_rubric_draft(draft_id)

    async def approve_rubric_draft(
        self,
        draft_id,
        approved_draft,
        job,
    ):
        return await self.inner.approve_rubric_draft(
            draft_id,
            approved_draft,
            job,
        )

    async def put_session(
        self,
        session: InterviewSession,
    ) -> None:
        previous = await self.inner.get_session(
            session.id
        )
        previous_seq = (
            previous.events[-1].seq
            if previous
            and previous.events
            else 0
        )

        await self.inner.put_session(
            session
        )

        new_events = [
            event
            for event in session.events
            if event.seq > previous_seq
            and event.type is not EventType.WEBHOOK_DELIVERY
        ]
        if not new_events:
            return

        results = await self.dispatcher.dispatch(
            session=session,
            events=new_events,
        )
        if not results:
            return

        for result in results:
            append_event(
                session,
                EventType.WEBHOOK_DELIVERY,
                payload={
                    "subscription_id": result.subscription_id,
                    "source_event_seq": result.event_seq,
                    "source_event_type": result.event_type,
                    "delivered": result.delivered,
                    "attempts": result.attempts,
                    "status_code": result.status_code,
                    "error_type": result.error_type,
                },
            )

        try:
            await self.inner.put_session(
                session
            )
        except Exception:
            # Delivery has already happened. Do not turn an observability
            # persistence race into a failure of the caller's primary save.
            return

    async def get_session(self, session_id):
        return await self.inner.get_session(session_id)

    async def list_sessions(self):
        return await self.inner.list_sessions()

    async def delete_session(self, session_id):
        return await self.inner.delete_session(session_id)

    async def ping(self):
        return await self.inner.ping()

    async def close(self):
        return await self.inner.close()
