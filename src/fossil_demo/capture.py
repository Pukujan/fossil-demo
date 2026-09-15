from __future__ import annotations

from typing import Protocol

from .domain import CaptureResult, CaptureStatus, IngestionStatus


class CaptureAdapter(Protocol):
    def capture(self, url: str) -> CaptureResult: ...


class FixtureCaptureAdapter:
    """Deterministic V0 adapter used to prove product behavior before live wiring."""

    def __init__(self, outcome: str = "complete") -> None:
        if outcome not in {"complete", "incomplete"}:
            raise ValueError("outcome must be complete or incomplete")
        self._outcome = outcome

    def capture(self, url: str) -> CaptureResult:
        del url
        if self._outcome == "complete":
            return CaptureResult(
                display_title="Productizing FOSSIL",
                capture_status=CaptureStatus.COMPLETE,
                fidelity="verbatim",
                completeness="complete",
                completeness_reason="source_terminal",
                message_count=516,
                sha256="9e77214c5be6f3958be8d9eceea2ecd568b877a86b4c7a33db578546b199eb4b",
                byte_count=1_517_420,
                artifact_id="art_9e77214c5be6f3958be8d9eceea2ecd5",
                ingestion_status=IngestionStatus.INGESTED,
                ingestion_reason=None,
                evidence_preserved=True,
                citation_id="cit_fixture_current",
                span_id="span_fixture_current",
                lineage_ref="ln_fixture_current",
                evidence_status="reconstructed",
                excerpt="Fixture reconstructed evidence for the V0 product contract.",
            )
        return CaptureResult(
            display_title="Productizing FOSSIL",
            capture_status=CaptureStatus.INCOMPLETE,
            fidelity="verbatim",
            completeness="incomplete",
            completeness_reason="unresolved_continuation",
            message_count=516,
            sha256="9f9c4789c123938d7163a74ffe11cec4723e5194081eea0f5acaa97cfb12a141",
            byte_count=1_513_860,
            artifact_id="art_9f9c4789c123938d7163a74ffe11cec4",
            ingestion_status=IngestionStatus.REFUSED,
            ingestion_reason="complete_conversation_promotion_refused",
            evidence_preserved=True,
            citation_id="cit_fixture_incomplete",
            span_id="span_fixture_incomplete",
            lineage_ref="ln_fixture_incomplete",
            evidence_status="reconstructed",
            excerpt="Fixture evidence was preserved even though complete promotion was refused.",
        )
