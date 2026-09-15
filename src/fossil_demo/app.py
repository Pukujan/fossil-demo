from __future__ import annotations

from pathlib import Path

from fastapi import BackgroundTasks, Cookie, FastAPI, HTTPException, Response
from pydantic import BaseModel

from .capture import CaptureAdapter, FixtureCaptureAdapter
from .config import Settings
from .db import Repository
from .domain import IngestionStatus, MemoryStatus
from .service import DemoService

COOKIE_NAME = "__Host-fossil_session"


class SourceRequest(BaseModel):
    kind: str
    url: str


class QueryRequest(BaseModel):
    query: str
    mode: str = "grounded"


def default_settings() -> Settings:
    return Settings(
        db_path=Path(".fossil-demo/fossil-demo.sqlite"),
        workspace_root=Path(".fossil-demo/workspaces"),
    )


def create_app(
    settings: Settings | None = None,
    capture_adapter: CaptureAdapter | None = None,
) -> FastAPI:
    settings = settings or default_settings()
    repo = Repository(settings.db_path)
    service = DemoService(settings, repo, capture_adapter or FixtureCaptureAdapter("complete"))

    app = FastAPI(title="FOSSIL Demo", version="0.0.1")
    app.state.service = service
    app.state.settings = settings

    def require_owner(secret: str | None) -> str:
        owner_hash = service.require_session_hash(secret)
        if owner_hash is None:
            raise HTTPException(status_code=401, detail={"code": "session_required"})
        return owner_hash

    def owned_workspace_or_404(workspace_id: str, owner_hash: str) -> dict:
        workspace = service.get_owned_workspace(workspace_id, owner_hash)
        if not workspace:
            raise HTTPException(status_code=404, detail={"code": "workspace_not_found"})
        return workspace

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v0/session")
    def establish_session(
        response: Response,
        fossil_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    ) -> dict:
        secret, created = service.establish_session(fossil_session)
        if created:
            response.set_cookie(
                key=COOKIE_NAME,
                value=secret,
                secure=settings.cookie_secure,
                httponly=True,
                samesite="strict",
                path="/",
            )
        return {
            "session": {"status": "active", "expires_with_browser_identity": True},
            "capabilities": {
                "chatgpt_share_import": True,
                "query": True,
                "verify": True,
                "export": False,
            },
            "limits": {"active_workspaces": 1},
        }

    @app.post("/api/v0/workspaces", status_code=201)
    def create_workspace(
        fossil_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    ) -> dict:
        owner_hash = require_owner(fossil_session)
        workspace = service.create_workspace(owner_hash)
        return {
            "workspace": {
                key: workspace[key]
                for key in (
                    "workspace_id",
                    "status",
                    "created_at",
                    "expires_at",
                    "memory_status",
                    "export_status",
                )
            }
        }

    @app.get("/api/v0/workspaces/{workspace_id}")
    def get_workspace(
        workspace_id: str,
        fossil_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    ) -> dict:
        owner_hash = require_owner(fossil_session)
        workspace = owned_workspace_or_404(workspace_id, owner_hash)
        return service.workspace_view(workspace)

    @app.delete("/api/v0/workspaces/{workspace_id}", status_code=204)
    def delete_workspace(
        workspace_id: str,
        fossil_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    ) -> Response:
        owner_hash = require_owner(fossil_session)
        if not service.delete_workspace(workspace_id, owner_hash):
            raise HTTPException(status_code=404, detail={"code": "workspace_not_found"})
        return Response(status_code=204)

    @app.post("/api/v0/workspaces/{workspace_id}/sources", status_code=202)
    def submit_source(
        workspace_id: str,
        request: SourceRequest,
        background_tasks: BackgroundTasks,
        fossil_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    ) -> dict:
        owner_hash = require_owner(fossil_session)
        if request.kind != "chatgpt_share":
            raise HTTPException(status_code=422, detail={"code": "unsupported_source_kind"})
        try:
            source = service.submit_source(workspace_id, owner_hash, request.url)
        except LookupError:
            raise HTTPException(status_code=404, detail={"code": "workspace_not_found"}) from None
        except ValueError as exc:
            code = str(exc)
            status = 409 if code == "source_already_exists" else 422
            raise HTTPException(status_code=status, detail={"code": code}) from None
        background_tasks.add_task(service.process_pending, workspace_id)
        return {
            "source": source,
            "workspace": {"status": "processing", "memory_status": "building"},
        }

    @app.get("/api/v0/workspaces/{workspace_id}/memory")
    def memory(
        workspace_id: str,
        fossil_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    ) -> dict:
        owner_hash = require_owner(fossil_session)
        workspace = owned_workspace_or_404(workspace_id, owner_hash)
        source = service.source_result(workspace_id)
        if workspace["memory_status"] != MemoryStatus.READY.value or not source or not source["result"]:
            raise HTTPException(status_code=409, detail={"code": "memory_not_ready"})
        result = source["result"]
        return {
            "memory": {
                "status": "ready",
                "title": result["display_title"],
                "source_count": 1,
                "message_count": result["message_count"],
                "capabilities": {
                    "grounded_query": True,
                    "structural_lineage": True,
                    "semantic_claims": False,
                    "decisions": False,
                    "changed_positions": False,
                    "unresolved_questions": False,
                },
            },
            "source": {
                "source_id": source["source_id"],
                "capture_status": result["capture_status"],
                "fidelity": result["fidelity"],
                "completeness": result["completeness"],
            },
            "workspace": {"expires_at": workspace["expires_at"]},
        }

    @app.post("/api/v0/workspaces/{workspace_id}/queries")
    def query(
        workspace_id: str,
        request: QueryRequest,
        fossil_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    ) -> dict:
        owner_hash = require_owner(fossil_session)
        workspace = owned_workspace_or_404(workspace_id, owner_hash)
        source = service.source_result(workspace_id)
        if request.mode != "grounded":
            raise HTTPException(status_code=422, detail={"code": "unsupported_query_mode"})
        if not request.query.strip():
            raise HTTPException(status_code=422, detail={"code": "empty_query"})
        if workspace["memory_status"] != MemoryStatus.READY.value or not source or not source["result"]:
            raise HTTPException(status_code=409, detail={"code": "memory_not_ready"})
        result = source["result"]
        if result["ingestion_status"] != IngestionStatus.INGESTED.value:
            raise HTTPException(status_code=409, detail={"code": "memory_not_ready"})
        return {
            "answer": {
                "status": "grounded",
                "text": "Fixture grounded result for V0 contract validation.",
                "generated": False,
            },
            "evidence": [
                {
                    "citation_id": result["citation_id"],
                    "source_id": source["source_id"],
                    "artifact_id": result["artifact_id"],
                    "span_id": result["span_id"],
                    "evidence_status": result["evidence_status"],
                    "excerpt": result["excerpt"],
                }
            ],
            "lineage": {
                "available": True,
                "kind": "structural_reconstruction",
                "current_ref": result["lineage_ref"],
            },
        }

    @app.get("/api/v0/workspaces/{workspace_id}/evidence/{citation_id}")
    def evidence(
        workspace_id: str,
        citation_id: str,
        fossil_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    ) -> dict:
        owner_hash = require_owner(fossil_session)
        owned_workspace_or_404(workspace_id, owner_hash)
        source = service.source_result(workspace_id)
        if not source or not source["result"] or source["result"]["citation_id"] != citation_id:
            raise HTTPException(status_code=404, detail={"code": "citation_not_found"})
        result = source["result"]
        return {
            "citation": {
                "citation_id": result["citation_id"],
                "artifact_id": result["artifact_id"],
                "span_id": result["span_id"],
                "evidence_status": result["evidence_status"],
                "excerpt": result["excerpt"],
            }
        }

    @app.get("/api/v0/workspaces/{workspace_id}/lineage/{lineage_ref}")
    def lineage(
        workspace_id: str,
        lineage_ref: str,
        fossil_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    ) -> dict:
        owner_hash = require_owner(fossil_session)
        owned_workspace_or_404(workspace_id, owner_hash)
        source = service.source_result(workspace_id)
        if not source or not source["result"] or source["result"]["lineage_ref"] != lineage_ref:
            raise HTTPException(status_code=404, detail={"code": "lineage_not_found"})
        result = source["result"]
        return {
            "lineage": {
                "kind": "structural_reconstruction",
                "current_ref": result["lineage_ref"],
                "nodes": [{"ref": result["lineage_ref"]}],
                "edges": [],
                "citation_ids": [result["citation_id"]],
            }
        }

    @app.get("/api/v0/workspaces/{workspace_id}/verify")
    def verify(
        workspace_id: str,
        fossil_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    ) -> dict:
        owner_hash = require_owner(fossil_session)
        owned_workspace_or_404(workspace_id, owner_hash)
        source = service.source_result(workspace_id)
        if not source or not source["result"]:
            raise HTTPException(status_code=409, detail={"code": "verification_not_ready"})
        result = source["result"]
        complete = result["completeness"] == "complete"
        ingested = result["ingestion_status"] == IngestionStatus.INGESTED.value
        return {
            "verification": {
                "status": "verified" if complete and ingested else "not_verified",
                "checks": {
                    "capture_complete": complete,
                    "messages_accounted": {
                        "accounted": result["message_count"],
                        "expected": result["message_count"] if complete else None,
                    },
                    "source_binding": True,
                    "artifact_integrity": True,
                    "citations_resolve": True if ingested else None,
                    "rebuildability": True if ingested else None,
                },
            },
            "advanced": {
                "sha256": result["sha256"],
                "byte_count": result["byte_count"],
                "artifact_id": result["artifact_id"],
                "capture_receipt_id": None,
            },
        }

    return app


app = create_app()
