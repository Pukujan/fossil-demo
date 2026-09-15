from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class WorkspaceStatus(StrEnum):
    CREATING = "creating"
    READY = "ready"
    PROCESSING = "processing"
    FAILED = "failed"
    EXPIRED = "expired"
    DELETING = "deleting"
    DELETED = "deleted"


class CaptureStatus(StrEnum):
    PENDING = "pending"
    CAPTURING = "capturing"
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"
    FAILED = "failed"


class IngestionStatus(StrEnum):
    NOT_STARTED = "not_started"
    INGESTING = "ingesting"
    INGESTED = "ingested"
    REFUSED = "refused"
    FAILED = "failed"


class MemoryStatus(StrEnum):
    UNAVAILABLE = "unavailable"
    BUILDING = "building"
    READY = "ready"
    DEGRADED = "degraded"


class ExportStatus(StrEnum):
    UNAVAILABLE = "unavailable"
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"
    EXPIRED = "expired"


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    REFUSED = "refused"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class CaptureResult:
    display_title: str
    capture_status: CaptureStatus
    fidelity: str
    completeness: str
    completeness_reason: str
    message_count: int
    sha256: str
    byte_count: int
    artifact_id: str
    ingestion_status: IngestionStatus
    ingestion_reason: str | None
    evidence_preserved: bool
    citation_id: str
    span_id: str
    lineage_ref: str
    evidence_status: str
    excerpt: str
