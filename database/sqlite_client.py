"""SQLite client — persistence for edit sessions, message history, and graph snapshots."""

import logging
import os

import aiosqlite

logger = logging.getLogger(__name__)

# Module-level singleton
_sqlite: "SQLiteClient | None" = None


class SQLiteClient:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    async def init_schema(self) -> None:
        """Create all tables if they do not already exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS edit_sessions (
                    session_id   TEXT PRIMARY KEY,
                    entity_type  TEXT NOT NULL,
                    entity_id    TEXT NOT NULL,
                    recruiter_id TEXT,
                    started_at   TEXT NOT NULL,
                    last_active  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS session_messages (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id    TEXT NOT NULL REFERENCES edit_sessions(session_id),
                    role          TEXT NOT NULL,
                    content       TEXT NOT NULL,
                    proposal_json TEXT,
                    created_at    TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS graph_snapshots (
                    version_id    TEXT PRIMARY KEY,
                    entity_type   TEXT NOT NULL,
                    entity_id     TEXT NOT NULL,
                    session_id    TEXT REFERENCES edit_sessions(session_id),
                    label         TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at    TEXT NOT NULL
                );
                """
            )
            await db.commit()
        logger.info(f"SQLite schema initialized: {self.db_path}")

    async def execute(self, query: str, params: tuple = ()) -> None:
        """Execute a write query and commit."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(query, params)
            await db.commit()

    async def fetchall(self, query: str, params: tuple = ()) -> list[dict]:
        """Execute a SELECT query and return all rows as a list of dicts."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def fetchone(self, query: str, params: tuple = ()) -> dict | None:
        """Execute a SELECT query and return the first row as a dict, or None."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row is not None else None


def get_sqlite() -> SQLiteClient:
    """Return the module-level singleton. Raises if init_sqlite() was never called."""
    if _sqlite is None:
        raise RuntimeError(
            "SQLite client not initialized. Call init_sqlite() at app startup."
        )
    return _sqlite


async def init_sqlite(db_path: str) -> SQLiteClient:
    """Create the singleton SQLite client and initialize the schema."""
    global _sqlite
    _sqlite = SQLiteClient(db_path)
    await _sqlite.init_schema()
    logger.info(f"SQLite client initialized: {db_path}")
    return _sqlite
