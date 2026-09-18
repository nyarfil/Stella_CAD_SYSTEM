"""Transactional, revision-checked state. SQLite serializes competing agents."""
from __future__ import annotations
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from .models import Project
from .errors import BrainError
from .util import canonical, safe_id


class Store:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().absolute()
        if self.root.is_symlink():
            raise BrainError("UNSAFE_PATH", "Workspace cannot be a symlink.")
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "brain.sqlite3"
        if self.path.is_symlink():
            raise BrainError("UNSAFE_PATH", "Database cannot be a symlink.")
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS backend_calls (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, project TEXT NOT NULL, status TEXT NOT NULL, response TEXT);
                CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT NOT NULL, revision INTEGER NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        try:
            yield db
        finally:
            db.close()

    def create(self, project: Project):
        safe_id(project.id)
        with self.connect() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                db.execute("INSERT INTO projects VALUES (?,?,?)", (project.id, 0, project.model_dump_json()))
                db.execute("INSERT INTO events (project,revision,kind,payload) VALUES (?,?,?,?)", (project.id, 0, "created", canonical({"source_hashes": [s.sha256 for s in project.sources]})))
                db.commit()
            except sqlite3.IntegrityError as exc:
                db.rollback()
                raise BrainError("PROJECT_EXISTS", "Project already exists; use brain_get or brain_add_source.") from exc
        return project

    def get(self, project_id: str) -> Project:
        safe_id(project_id)
        with self.connect() as db:
            row = db.execute("SELECT document FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise BrainError("NOT_FOUND", "Unknown project.")
        return Project.model_validate_json(row[0])

    @contextmanager
    def edit(self, project_id: str, expected_revision: int, kind: str):
        safe_id(project_id)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute("SELECT revision,document FROM projects WHERE id=?", (project_id,)).fetchone()
                if not row:
                    raise BrainError("NOT_FOUND", "Unknown project.")
                if row["revision"] != expected_revision:
                    raise BrainError("REVISION_CONFLICT", "Reload before changing a newer design.", {"expected": expected_revision, "actual": row["revision"]})
                p = Project.model_validate_json(row["document"])
                yield p
                p.revision += 1
                db.execute("UPDATE projects SET revision=?,document=? WHERE id=?", (p.revision, p.model_dump_json(), project_id))
                db.execute("INSERT INTO events (project,revision,kind,payload) VALUES (?,?,?,?)", (project_id, p.revision, kind, canonical({"selection": p.selection, "has_plan": p.plan is not None})))
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def history(self, project_id: str):
        self.get(project_id)
        with self.connect() as db:
            return [dict(r) | {"payload": json.loads(r["payload"])} for r in db.execute("SELECT * FROM events WHERE project=? ORDER BY seq", (project_id,))]
