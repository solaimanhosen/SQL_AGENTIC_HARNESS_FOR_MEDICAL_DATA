"""Conversations kept by the HTTP service, so they can be listed, reopened and continued.

They live in their own SQLite database, never in the patient database, which is read-only
and is replaced whenever the loader runs. With no path the store is in memory, which is
what the tests use and what `SQL_AGENT_CONVERSATIONS_PATH=off` selects.

Each answered question is stored as a turn, twice over: the answer as the interface was
sent it, so a reopened conversation shows what the user saw, and the short form a follow-up
question is shown. Only the most recent turns are handed back as history, however long the
conversation grows.

One question at a time may be answered in a conversation, since a second one asked before
the first finishes could not see its answer. Which conversations are busy is kept in
memory, because a run does not survive a restart either.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .agent import MAX_HISTORY_TURNS, Turn

DEFAULT_MAX_CONVERSATIONS = 1_000
TITLE_CHARS = 60
MAX_TITLE_CHARS = 100

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


class UnknownConversation(KeyError):
    """The conversation was deleted, was never started, or was removed to make room."""


class ConversationBusy(RuntimeError):
    """The conversation is still answering an earlier question."""


@dataclass(frozen=True)
class ConversationSummary:
    id: str
    title: str
    created_at: str
    updated_at: str
    turn_count: int


@dataclass(frozen=True)
class StoredTurn:
    turn: int
    question: str
    created_at: str
    answer: dict | None
    """The answer as the service returned it."""
    steps: list


@dataclass(frozen=True)
class StoredConversation:
    summary: ConversationSummary
    busy: bool
    turns: tuple[StoredTurn, ...]


def title_from(question: str) -> str:
    """A conversation's title: its first question on one line, cut short if it is long."""
    title = " ".join(question.split())
    return title if len(title) <= TITLE_CHARS else title[: TITLE_CHARS - 1].rstrip() + "…"


class ConversationStore:
    """Thread-safe and bounded: the least recently used conversation is removed first."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        max_conversations: int = DEFAULT_MAX_CONVERSATIONS,
        max_turns: int = MAX_HISTORY_TURNS,
    ):
        self.path = path
        self.max_conversations = max_conversations
        self.max_turns = max_turns
        self._lock = threading.Lock()
        self._busy: set[str] = set()
        self._clock = datetime.min.replace(tzinfo=timezone.utc)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        # One connection, used only while the lock is held, so any thread may call in.
        self._db = sqlite3.connect(path or ":memory:", check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        if path is not None:
            self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(SCHEMA)

    def begin(self, conversation_id: str | None) -> tuple[str, tuple[Turn, ...], int]:
        """Claim a conversation for one question. Returns its id, its turns and the turn number.

        With no id, a new conversation is started. Every call must be matched by `finish`.
        """
        with self._lock:
            now = self._now()
            if conversation_id is None:
                conversation_id = secrets.token_hex(16)
                self._db.execute(
                    "INSERT INTO conversations (id, created_at, updated_at) VALUES (?, ?, ?)",
                    (conversation_id, now, now),
                )
            row = self._row(conversation_id)
            if conversation_id in self._busy:
                raise ConversationBusy(conversation_id)
            self._busy.add(conversation_id)
            self._db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
            self._evict()
            recent = self._db.execute(
                "SELECT question, context_answer, context_sql_json FROM turns"
                " WHERE conversation_id = ? ORDER BY turn DESC LIMIT ?",
                (conversation_id, self.max_turns),
            ).fetchall()
            history = tuple(
                Turn(question=item["question"], answer=item["context_answer"], sql=tuple(json.loads(item["context_sql_json"])))
                for item in reversed(recent)
            )
            return conversation_id, history, row["turn_count"] + 1

    def finish(
        self,
        conversation_id: str,
        turn: Turn | None,
        *,
        answer: dict | None = None,
        steps: list | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Release the conversation, storing the answered turn if there is one.

        `answer` is the body the interface was sent and `steps` what the agent did, both
        kept so the conversation can be shown again exactly as it was.
        """
        with self._lock:
            self._busy.discard(conversation_id)
            if turn is None:
                return
            row = self._db.execute("SELECT turn_count FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
            if row is None:
                return
            now = self._now()
            number = row["turn_count"] + 1
            with self._db:
                self._db.execute("BEGIN")
                self._db.execute(
                    "INSERT INTO turns VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        conversation_id,
                        number,
                        turn.question,
                        json.dumps(answer, ensure_ascii=False),
                        json.dumps(steps or [], ensure_ascii=False),
                        turn.answer,
                        json.dumps(list(turn.sql), ensure_ascii=False),
                        now,
                        input_tokens,
                        output_tokens,
                    ),
                )
                self._db.execute(
                    "UPDATE conversations SET turn_count = ?, updated_at = ?, tokens_spent = tokens_spent + ?,"
                    " title = CASE WHEN title = '' THEN ? ELSE title END WHERE id = ?",
                    (number, now, input_tokens + output_tokens, title_from(turn.question), conversation_id),
                )

    def tokens_spent(self, conversation_id: str) -> int:
        """Model tokens the conversation's stored turns used, or 0 if it is not known."""
        with self._lock:
            row = self._db.execute("SELECT tokens_spent FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
            return row["tokens_spent"] if row else 0

    def list(self) -> list[ConversationSummary]:
        """Conversations with at least one answer, most recently used first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM conversations WHERE turn_count > 0 ORDER BY updated_at DESC"
            ).fetchall()
            return [_summary(row) for row in rows]

    def get(self, conversation_id: str) -> StoredConversation:
        with self._lock:
            row = self._row(conversation_id)
            turns = self._db.execute(
                "SELECT turn, question, created_at, answer_json, steps_json FROM turns"
                " WHERE conversation_id = ? ORDER BY turn",
                (conversation_id,),
            ).fetchall()
            return StoredConversation(
                summary=_summary(row),
                busy=conversation_id in self._busy,
                turns=tuple(
                    StoredTurn(
                        turn=item["turn"],
                        question=item["question"],
                        created_at=item["created_at"],
                        answer=json.loads(item["answer_json"]),
                        steps=json.loads(item["steps_json"]),
                    )
                    for item in turns
                ),
            )

    def rename(self, conversation_id: str, title: str) -> ConversationSummary:
        title = " ".join(title.split())[:MAX_TITLE_CHARS]
        if not title:
            raise ValueError("A title cannot be empty.")
        with self._lock:
            self._row(conversation_id)
            self._db.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id))
            return _summary(self._row(conversation_id))

    def delete(self, conversation_id: str) -> None:
        """Remove the conversation and its turns. One that is answering cannot be removed."""
        with self._lock:
            self._row(conversation_id)
            if conversation_id in self._busy:
                raise ConversationBusy(conversation_id)
            self._db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __len__(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]

    def _row(self, conversation_id: str) -> sqlite3.Row:
        row = self._db.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        if row is None:
            raise UnknownConversation(conversation_id)
        return row

    def _now(self) -> str:
        """The time in UTC, never the same twice, so the order of use is always clear."""
        self._clock = max(datetime.now(timezone.utc), self._clock + timedelta(microseconds=1))
        return self._clock.isoformat(timespec="microseconds")

    def _evict(self) -> None:
        excess = self._db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] - self.max_conversations
        if excess <= 0:
            return
        for (conversation_id,) in self._db.execute("SELECT id FROM conversations ORDER BY updated_at").fetchall():
            if excess <= 0:
                break
            if conversation_id not in self._busy:
                self._db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
                excess -= 1


def _summary(row: sqlite3.Row) -> ConversationSummary:
    return ConversationSummary(
        id=row["id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        turn_count=row["turn_count"],
    )
