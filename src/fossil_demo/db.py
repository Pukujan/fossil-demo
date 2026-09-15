from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class Repository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_hash TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workspaces (
                    workspace_id TEXT PRIMARY KEY,
                    owner_session_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    memory_status TEXT NOT NULL,
                    export_status TEXT NOT NULL,
                    FOREIGN KEY(owner_session_hash) REFERENCES sessions(session_hash) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS sources (
                    source_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    url TEXT NOT NULL,
                    capture_status TEXT NOT NULL,
                    result_json TEXT,
                    FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE
                );
                """
            )

    def put_session(self, session_hash: str, created_at: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions(session_hash, created_at) VALUES (?, ?)",
                (session_hash, created_at),
            )

    def session_exists(self, session_hash: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM sessions WHERE session_hash = ?", (session_hash,)
            ).fetchone()
        return row is not None

    def create_workspace(self, values: dict[str, str]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO workspaces(
                    workspace_id, owner_session_hash, status, created_at, expires_at,
                    memory_status, export_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["workspace_id"],
                    values["owner_session_hash"],
                    values["status"],
                    values["created_at"],
                    values["expires_at"],
                    values["memory_status"],
                    values["export_status"],
                ),
            )

    def get_owned_workspace(self, workspace_id: str, owner_hash: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM workspaces WHERE workspace_id = ? AND owner_session_hash = ?",
                (workspace_id, owner_hash),
            ).fetchone()
        return dict(row) if row else None

    def update_workspace(self, workspace_id: str, **values: str) -> None:
        if not values:
            return
        allowed = {"status", "memory_status", "export_status"}
        if set(values) - allowed:
            raise ValueError("unsupported workspace field")
        clause = ", ".join(f"{key} = ?" for key in values)
        params = [*values.values(), workspace_id]
        with self.connect() as conn:
            conn.execute(f"UPDATE workspaces SET {clause} WHERE workspace_id = ?", params)

    def create_source(self, values: dict[str, str]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sources(source_id, workspace_id, kind, url, capture_status, result_json)
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (
                    values["source_id"],
                    values["workspace_id"],
                    values["kind"],
                    values["url"],
                    values["capture_status"],
                ),
            )

    def get_source_for_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM sources WHERE workspace_id = ?", (workspace_id,)
            ).fetchone()
        return dict(row) if row else None

    def finish_source(self, source_id: str, capture_status: str, result: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE sources SET capture_status = ?, result_json = ? WHERE source_id = ?",
                (capture_status, json.dumps(result, sort_keys=True), source_id),
            )

    def delete_workspace(self, workspace_id: str, owner_hash: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM workspaces WHERE workspace_id = ? AND owner_session_hash = ?",
                (workspace_id, owner_hash),
            )
        return cur.rowcount == 1
