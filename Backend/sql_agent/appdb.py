"""The service's own SQLite database: conversations, users and sign-in sessions.

It is never the patient database, which is read-only and replaced whenever the loader runs.
One file keeps the stores together, so a conversation's owner is a user in the same file.
With no path it is in memory, which is what the tests use and what
`SQL_AGENT_CONVERSATIONS_PATH=off` selects.

The file records its schema version. Opening a file from an earlier version upgrades it in
place, one transaction per step; a file from a newer version is refused untouched.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

# The schema as v3.0.0 created it. A file it wrote has user_version 0; this is version 1.
SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    owner TEXT,
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    turn_count INTEGER NOT NULL DEFAULT 0,
    tokens_spent INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS turns (
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    turn INTEGER NOT NULL,
    question TEXT NOT NULL,
    answer_json TEXT NOT NULL,
    steps_json TEXT NOT NULL,
    context_answer TEXT NOT NULL,
    context_sql_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (conversation_id, turn)
);
CREATE INDEX IF NOT EXISTS conversations_by_use ON conversations(updated_at);
"""

# Each entry takes the schema one version further: the first gives version 2. They only
# ever add, so a file written by any earlier version upgrades in place when it is opened.
# Never edit one that has shipped; add a new one.
MIGRATIONS: tuple[str, ...] = (
    # 2: pinning. NULL means not pinned; otherwise when it was pinned, newest pin first.
    "ALTER TABLE conversations ADD COLUMN pinned_at TEXT;",
    # 3: the model and effort of the latest answer, so reopening restores the picker.
    "ALTER TABLE conversations ADD COLUMN last_model TEXT;"
    " ALTER TABLE conversations ADD COLUMN last_effort TEXT;",
    # 4: accounts. A conversation's owner is a user id; conversations from before accounts
    # have none, and are seen by nobody until an admin claims them.
    """
    CREATE TABLE users (
        id TEXT PRIMARY KEY,
        email TEXT NOT NULL UNIQUE COLLATE NOCASE,
        name TEXT NOT NULL DEFAULT '',
        role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
        password_hash TEXT,
        google_sub TEXT UNIQUE,
        email_verified INTEGER NOT NULL DEFAULT 0,
        disabled INTEGER NOT NULL DEFAULT 0,
        default_model TEXT,
        default_effort TEXT,
        created_at TEXT NOT NULL,
        last_seen_at TEXT
    );
    CREATE TABLE sessions (
        id TEXT PRIMARY KEY,
        token_hash TEXT NOT NULL UNIQUE,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        last_used_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        user_agent TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX sessions_by_user ON sessions(user_id);
    CREATE TABLE oauth_states (
        state_hash TEXT PRIMARY KEY,
        nonce TEXT NOT NULL,
        code_verifier TEXT NOT NULL,
        next_path TEXT NOT NULL,
        link_user_id TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE INDEX conversations_by_owner ON conversations(owner, updated_at);
    """,
    # 5: the checks an admin ran from the console, with their output and verdict.
    """
    CREATE TABLE check_runs (
        id TEXT PRIMARY KEY,
        job TEXT NOT NULL,
        status TEXT NOT NULL,
        started_by TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        exit_code INTEGER,
        choices_json TEXT NOT NULL DEFAULT '{}',
        summary_json TEXT NOT NULL DEFAULT '{}',
        output TEXT NOT NULL DEFAULT '',
        truncated INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX check_runs_by_job ON check_runs(job, started_at);
    """,
    # 6: links sent by email, to reset a password or confirm an address. Only the hash is kept,
    # and a row is removed when its link is used or replaced.
    """
    CREATE TABLE email_tokens (
        token_hash TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        purpose TEXT NOT NULL CHECK (purpose IN ('reset', 'verify')),
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    );
    CREATE INDEX email_tokens_by_user ON email_tokens(user_id, purpose);
    """,
)
SCHEMA_VERSION = 1 + len(MIGRATIONS)


class NewerSchema(RuntimeError):
    """The file was written by a newer version of this program, which this one must not alter."""


class AppDatabase:
    """One connection, used only while `lock` is held, so any thread may call in."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.lock = threading.Lock()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path or ":memory:", check_same_thread=False, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        if path is not None:
            self.connection.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def _migrate(self) -> None:
        """Create the tables, or bring a file from an earlier version up to date."""
        db = self.connection
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise NewerSchema(
                f"{self.path} is at schema version {version}, newer than this program's"
                f" {SCHEMA_VERSION}. Use the newer program, or another conversations file."
            )
        db.executescript(SCHEMA)
        for number, script in enumerate(MIGRATIONS, start=2):
            if max(version, 1) < number:
                # One transaction per step, so a failed step leaves the file at the last good one.
                try:
                    db.executescript(f"BEGIN; {script} PRAGMA user_version = {number}; COMMIT;")
                except sqlite3.Error:
                    if db.in_transaction:
                        db.execute("ROLLBACK")
                    raise

    def schema_version(self) -> int:
        with self.lock:
            return self.connection.execute("PRAGMA user_version").fetchone()[0]

    def close(self) -> None:
        with self.lock:
            self.connection.close()
