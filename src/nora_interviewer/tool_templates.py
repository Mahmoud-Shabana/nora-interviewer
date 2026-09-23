from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .coding import CodingChallengeManager, CodingChallengeRequest
from .models import InterviewSession, JobSpec, ToolInvocation, ToolKind


class ToolTemplateFactory(Protocol):
    template_id: str
    kind: ToolKind
    description: str

    def instantiate(
        self,
        *,
        session: InterviewSession,
        job: JobSpec,
        competency_tags: list[str],
        opened_from_turn_id: str | None,
    ) -> ToolInvocation: ...


@dataclass(frozen=True)
class StaticToolTemplate:
    template_id: str
    kind: ToolKind
    title: str
    description: str
    instructions: str
    payload: dict

    def instantiate(
        self,
        *,
        session: InterviewSession,
        job: JobSpec,
        competency_tags: list[str],
        opened_from_turn_id: str | None,
    ) -> ToolInvocation:
        payload = dict(self.payload)
        payload["template_id"] = self.template_id
        return ToolInvocation(
            kind=self.kind,
            title=self.title,
            instructions=self.instructions,
            competency_tags=competency_tags,
            opened_from_turn_id=opened_from_turn_id,
            payload=payload,
        )


@dataclass(frozen=True)
class CodingToolTemplate:
    template_id: str
    title: str
    description: str
    instructions: str
    starter_code: str
    public_tests: tuple[str, ...]
    hidden_tests: tuple[str, ...]
    timeout_seconds: float
    manager: CodingChallengeManager
    kind: ToolKind = ToolKind.CODING

    def instantiate(
        self,
        *,
        session: InterviewSession,
        job: JobSpec,
        competency_tags: list[str],
        opened_from_turn_id: str | None,
    ) -> ToolInvocation:
        invocation = self.manager.create(
            CodingChallengeRequest(
                title=self.title,
                instructions=self.instructions,
                competency_tags=competency_tags,
                starter_code=self.starter_code,
                public_tests=list(self.public_tests),
                hidden_tests=list(self.hidden_tests),
                opened_from_turn_id=opened_from_turn_id,
                timeout_seconds=self.timeout_seconds,
            )
        )
        invocation.payload["template_id"] = self.template_id
        return invocation


class ToolTemplateRegistry:
    def __init__(self) -> None:
        self._templates: dict[str, ToolTemplateFactory] = {}

    def register(self, template: ToolTemplateFactory) -> None:
        if template.template_id in self._templates:
            raise ValueError(f"duplicate tool template id: {template.template_id}")
        self._templates[template.template_id] = template

    def get(self, template_id: str) -> ToolTemplateFactory:
        try:
            return self._templates[template_id]
        except KeyError as exc:
            raise ValueError(f"unknown tool template: {template_id}") from exc

    def describe(self, template_id: str) -> dict[str, str]:
        template = self.get(template_id)
        return {
            "template_id": template.template_id,
            "kind": template.kind.value,
            "description": template.description,
        }

    def instantiate(
        self,
        template_id: str,
        *,
        session: InterviewSession,
        job: JobSpec,
        competency_tags: list[str],
        opened_from_turn_id: str | None,
    ) -> ToolInvocation:
        template = self.get(template_id)
        return template.instantiate(
            session=session,
            job=job,
            competency_tags=competency_tags,
            opened_from_turn_id=opened_from_turn_id,
        )


def default_tool_template_registry(
    coding_manager: CodingChallengeManager,
) -> ToolTemplateRegistry:
    registry = ToolTemplateRegistry()

    registry.register(
        CodingToolTemplate(
            template_id="python-dedupe-events-v1",
            title="Debug and complete an event de-duplication function",
            description=(
                "A short Python implementation task that checks edge-case reasoning "
                "and whether the candidate validates behavior beyond the happy path."
            ),
            instructions=(
                "Implement dedupe_events(events). Each event is a dictionary with id, "
                "timestamp, and payload. Keep exactly one event per id: the event with "
                "the greatest timestamp. Return the retained events ordered by timestamp "
                "ascending. Do not mutate the input list."
            ),
            starter_code=(
                "def dedupe_events(events):\n"
                "    # Return one latest event per id, ordered by timestamp.\n"
                "    raise NotImplementedError\n"
            ),
            public_tests=(
                "assert dedupe_events([{'id':'a','timestamp':1,'payload':'x'},"
                "{'id':'a','timestamp':3,'payload':'y'}]) == "
                "[{'id':'a','timestamp':3,'payload':'y'}]",
            ),
            hidden_tests=(
                "events=[{'id':'b','timestamp':5,'payload':1},{'id':'a','timestamp':2,'payload':2},"
                "{'id':'b','timestamp':1,'payload':3}]; before=[dict(x) for x in events]; "
                "assert dedupe_events(events) == [{'id':'a','timestamp':2,'payload':2},"
                "{'id':'b','timestamp':5,'payload':1}]; assert events == before",
                "assert dedupe_events([]) == []",
            ),
            timeout_seconds=5.0,
            manager=coding_manager,
        )
    )

    registry.register(
        StaticToolTemplate(
            template_id="system-design-burst-api-v1",
            kind=ToolKind.CASE_STUDY,
            title="Bursty API architecture case",
            description=(
                "A system-design case focused on overload protection, queueing, "
                "failure modes, observability, and explicit trade-offs."
            ),
            instructions=(
                "A public API normally receives 1k requests/minute but can burst to "
                "100k requests/minute for five minutes. A downstream dependency cannot "
                "safely exceed 2k requests/minute. Propose an architecture, explain "
                "backpressure and degradation behavior, and list the metrics you would "
                "use to validate the design."
            ),
            payload={
                "deliverables": [
                    "architecture_summary",
                    "failure_modes",
                    "tradeoffs",
                    "validation_metrics",
                ]
            },
        )
    )

    registry.register(
        StaticToolTemplate(
            template_id="whiteboard-service-map-v1",
            kind=ToolKind.WHITEBOARD,
            title="Service dependency whiteboard",
            description=(
                "A lightweight architecture whiteboard exercise for communicating "
                "components, boundaries, and data flow."
            ),
            instructions=(
                "Draw the major components of the proposed system, connect the critical "
                "request/data flows, and annotate at least two failure boundaries."
            ),
            payload={
                "artifact_schema": {
                    "nodes": "array",
                    "edges": "array",
                    "notes": "array",
                }
            },
        )
    )

    registry.register(
        StaticToolTemplate(
            template_id="document-incident-review-v1",
            kind=ToolKind.DOCUMENT,
            title="Incident review analysis",
            description=(
                "A document-analysis exercise that asks the candidate to separate "
                "evidence, assumptions, contributing factors, and remediation."
            ),
            instructions=(
                "Review the supplied incident summary. Identify verified facts, open "
                "questions, contributing factors, and the first three remediation steps "
                "you would prioritize. State where evidence is insufficient."
            ),
            payload={
                "document_type": "incident_summary",
                "deliverables": [
                    "verified_facts",
                    "open_questions",
                    "contributing_factors",
                    "remediation",
                ],
            },
        )
    )

    return registry
