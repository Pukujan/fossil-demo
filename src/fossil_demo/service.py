from __future__ import annotations

import hashlib
import json
import secrets
import shutil
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID

from .capture import CaptureAdapter
from .config import Settings
from .db import Repository
from .domain import (
    CaptureStatus,
    ExportStatus,
    IngestionStatus,
    MemoryStatus,
    StageStatus,
    WorkspaceStatus,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def hash_session_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def valid_chatgpt_share_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "chatgpt.com":
            return False
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 2 or parts[0] != "share":
            return False
        UUID(parts[1])
        return True
    except (ValueError, AttributeError):
        return False


class DemoService:
    def __init__(self, settings: Settings, repo: Repository, capture_adapter: CaptureAdapter) -> None:
        self.settings = settings
        self.repo = repo
        self.capture_adapter = capture_adapter
        self.settings.workspace_root.mkdir(parents=True, exist_ok=True)

    def establish_session(self, current_secret: str | None) -> tuple[str, bool]:
        if current_secret:
            current_hash = hash_session_secret(current_secret)
            if self.repo.session_exists(current_hash):
                return current_secret, False
        secret = secrets.token_urlsafe(32)
        self.repo.put_session(hash_session_secret(secret), iso(utc_now()))
        return secret, True

    def require_session_hash(self, secret: str | None) -> str | None:
        if not secret:
            return None
        value = hash_session_secret(secret)
        return value if self.repo.session_exists(value) else None

    def create_workspace(self, owner_hash: str) -> dict[str, str]:
        now = utc_now()
        workspace_id = f"ws_{secrets.token_hex(16)}"
        values = {
            "workspace_id": workspace_id,
            "owner_session_hash": owner_hash,
            "status": WorkspaceStatus.READY.value,
            "created_at": iso(now),
            "expires_at": iso(now + timedelta(seconds=self.settings.workspace_ttl_seconds)),
            "memory_status": MemoryStatus.UNAVAILABLE.value,
            "export_status": ExportStatus.UNAVAILABLE.value,
        }
        self.repo.create_workspace(values)
        (self.settings.workspace_root / workspace_id).mkdir(mode=0o700)
        return values

    def get_owned_workspace(self, workspace_id: str, owner_hash: str) -> dict | None:
        return self.repo.get_owned_workspace(workspace_id, owner_hash)

    def submit_source(self, workspace_id: str, owner_hash: str, url: str) -> dict[str, str]:
        workspace = self.get_owned_workspace(workspace_id, owner_hash)
        if not workspace:
            raise LookupError("workspace_not_found")
        if self.repo.get_source_for_workspace(workspace_id):
            raise ValueError("source_already_exists")
        if not valid_chatgpt_share_url(url):
            raise ValueError("unsupported_source_url")
        source_id = f"src_{secrets.token_hex(16)}"
        self.repo.create_source(
            {
                "source_id": source_id,
                "workspace_id": workspace_id,
                "kind": "chatgpt_share",
                "url": url,
                "capture_status": CaptureStatus.PENDING.value,
            }
        )
        self.repo.update_workspace(
            workspace_id,
            status=WorkspaceStatus.PROCESSING.value,
            memory_status=MemoryStatus.BUILDING.value,
        )
        return {
            "source_id": source_id,
            "kind": "chatgpt_share",
            "capture_status": CaptureStatus.PENDING.value,
            "completeness": "unknown",
        }

    def process_pending(self, workspace_id: str) -> None:
        source = self.repo.get_source_for_workspace(workspace_id)
        if not source or source["result_json"] is not None:
            return
        result = self.capture_adapter.capture(source["url"])
        result_dict = asdict(result)
        result_dict["capture_status"] = result.capture_status.value
        result_dict["ingestion_status"] = result.ingestion_status.value
        self.repo.finish_source(source["source_id"], result.capture_status.value, result_dict)
        if result.ingestion_status == IngestionStatus.INGESTED:
            self.repo.update_workspace(
                workspace_id,
                status=WorkspaceStatus.READY.value,
                memory_status=MemoryStatus.READY.value,
            )
        elif result.ingestion_status == IngestionStatus.REFUSED:
            self.repo.update_workspace(
                workspace_id,
                status=WorkspaceStatus.READY.value,
                memory_status=MemoryStatus.UNAVAILABLE.value,
            )
        else:
            self.repo.update_workspace(
                workspace_id,
                status=WorkspaceStatus.FAILED.value,
                memory_status=MemoryStatus.UNAVAILABLE.value,
            )

    def source_result(self, workspace_id: str) -> dict | None:
        source = self.repo.get_source_for_workspace(workspace_id)
        if not source:
            return None
        result = json.loads(source["result_json"]) if source["result_json"] else None
        return {**source, "result": result}

    def workspace_view(self, workspace: dict) -> dict:
        source = self.source_result(workspace["workspace_id"])
        stages = self._stage_view(source)
        source_view = None
        if source:
            if source["result"]:
                result = source["result"]
                source_view = {
                    "source_id": source["source_id"],
                    "kind": source["kind"],
                    "display_title": result["display_title"],
                    "capture_status": result["capture_status"],
                    "fidelity": result["fidelity"],
                    "completeness": result["completeness"],
                    "completeness_reason": result["completeness_reason"],
                    "message_count": result["message_count"],
                    "ingestion": {
                        "status": result["ingestion_status"],
                        "reason": result["ingestion_reason"],
                    },
                    "evidence_preserved": result["evidence_preserved"],
                }
            else:
                source_view = {
                    "source_id": source["source_id"],
                    "kind": source["kind"],
                    "display_title": None,
                    "capture_status": source["capture_status"],
                    "fidelity": None,
                    "completeness": "unknown",
                    "completeness_reason": None,
                    "message_count": None,
                }
        return {
            "workspace": {
                "workspace_id": workspace["workspace_id"],
                "status": workspace["status"],
                "created_at": workspace["created_at"],
                "expires_at": workspace["expires_at"],
                "memory_status": workspace["memory_status"],
                "export_status": workspace["export_status"],
            },
            "source": source_view,
            "stages": stages,
        }

    def _stage_view(self, source: dict | None) -> list[dict[str, str]]:
        ids = ["capture", "integrity", "completeness", "evidence", "ingest", "query"]
        if source is None:
            return [{"id": value, "status": StageStatus.PENDING.value} for value in ids]
        if not source["result"]:
            return [
                {"id": "capture", "status": StageStatus.RUNNING.value},
                *[{"id": value, "status": StageStatus.PENDING.value} for value in ids[1:]],
            ]
        result = source["result"]
        if result["ingestion_status"] == IngestionStatus.INGESTED.value:
            return [{"id": value, "status": StageStatus.PASSED.value} for value in ids]
        if result["ingestion_status"] == IngestionStatus.REFUSED.value:
            return [
                {"id": "capture", "status": StageStatus.PASSED.value},
                {"id": "integrity", "status": StageStatus.PASSED.value},
                {"id": "completeness", "status": StageStatus.REFUSED.value},
                {"id": "evidence", "status": StageStatus.PASSED.value},
                {"id": "ingest", "status": StageStatus.REFUSED.value},
                {"id": "query", "status": StageStatus.SKIPPED.value},
            ]
        return [{"id": value, "status": StageStatus.FAILED.value} for value in ids]

    def delete_workspace(self, workspace_id: str, owner_hash: str) -> bool:
        if not self.repo.delete_workspace(workspace_id, owner_hash):
            return False
        root = self.settings.workspace_root / workspace_id
        if root.exists():
            shutil.rmtree(root)
        return True
