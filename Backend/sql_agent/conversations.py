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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .agent import MAX_HISTORY_TURNS, Turn
from .appdb import SCHEMA, SCHEMA_VERSION, AppDatabase, NewerSchema  # noqa: F401  (re-exported)

DEFAULT_MAX_CONVERSATIONS = 1_000
TITLE_CHARS = 60
MAX_TITLE_CHARS = 100
MAX_SEARCH_CHARS = 200
SEARCH_LIMIT = 50

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
    pinned_at: str | None = None
    last_model: str | None = None
    last_effort: str | None = None


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
    """Thread-safe and bounded per owner: each owner's least recently used conversation goes first.

    Every method that finds a conversation takes its `owner`, a user id. Another owner's
    conversation is reported as unknown, exactly like one that does not exist, so its
    existence is not revealed. `owner=None` means conversations from before accounts, which
    have none.
    """

    def __init__(
        self,
        path: Path | None = None,
        *,
        database: AppDatabase | None = None,
        max_conversations: int = DEFAULT_MAX_CONVERSATIONS,
        max_turns: int = MAX_HISTORY_TURNS,
    ):
        self.database = database or AppDatabase(path)
        self.path = self.database.path
        self.max_conversations = max_conversations
        self.max_turns = max_turns
        self._lock = self.database.lock
        self._db = self.database.connection
        self._busy: set[str] = set()
        self._clock = datetime.min.replace(tzinfo=timezone.utc)

    def schema_version(self) -> int:
        return self.database.schema_version()

    def begin(self, conversation_id: str | None, *, owner: str | None = None) -> tuple[str, tuple[Turn, ...], int]:
        """Claim a conversation for one question. Returns its id, its turns and the turn number.

        With no id, a new conversation is started for `owner`. Every call must be matched by
        `finish`.
        """
        with self._lock:
            now = self._now()
            if conversation_id is None:
                conversation_id = secrets.token_hex(16)
                self._db.execute(
                    "INSERT INTO conversations (id, owner, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (conversation_id, owner, now, now),
                )
            row = self._row(conversation_id, owner)
            if conversation_id in self._busy:
                raise ConversationBusy(conversation_id)
            self._busy.add(conversation_id)
            self._db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
            self._evict(owner)
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
        model: str | None = None,
        effort: str | None = None,
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
                    " title = CASE WHEN title = '' THEN ? ELSE title END,"
                    " last_model = COALESCE(?, last_model), last_effort = COALESCE(?, last_effort) WHERE id = ?",
                    (number, now, input_tokens + output_tokens, title_from(turn.question), model, effort, conversation_id),
                )

    def tokens_spent(self, conversation_id: str) -> int:
        """Model tokens the conversation's stored turns used, or 0 if it is not known."""
        with self._lock:
            row = self._db.execute("SELECT tokens_spent FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
            return row["tokens_spent"] if row else 0

    def list(self, *, owner: str | None = None) -> list[ConversationSummary]:
        """The owner's conversations with at least one answer, most recently used first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM conversations WHERE owner IS ? AND turn_count > 0 ORDER BY updated_at DESC",
                (owner,),
            ).fetchall()
            return [_summary(row) for row in rows]

    def search(self, text: str, *, owner: str | None = None) -> list[ConversationSummary]:
        """Conversations whose title or any question contains the text, most recently used first.

        Matching ignores case for English letters. The text is matched literally: % and _ are
        not wildcards here.
        """
        words = " ".join(text.split())[:MAX_SEARCH_CHARS]
        if not words:
            return self.list(owner=owner)
        pattern = "%" + words.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM conversations c WHERE c.owner IS :owner AND c.turn_count > 0"
                " AND (c.title LIKE :p ESCAPE '\\'"
                " OR EXISTS (SELECT 1 FROM turns t WHERE t.conversation_id = c.id AND t.question LIKE :p ESCAPE '\\'))"
                " ORDER BY c.updated_at DESC LIMIT :limit",
                {"p": pattern, "limit": SEARCH_LIMIT, "owner": owner},
            ).fetchall()
            return [_summary(row) for row in rows]

    def get(self, conversation_id: str, *, owner: str | None = None) -> StoredConversation:
        with self._lock:
            row = self._row(conversation_id, owner)
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

    def rename(self, conversation_id: str, title: str, *, owner: str | None = None) -> ConversationSummary:
        title = " ".join(title.split())[:MAX_TITLE_CHARS]
        if not title:
            raise ValueError("A title cannot be empty.")
        with self._lock:
            self._row(conversation_id, owner)
            self._db.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id))
            return _summary(self._row(conversation_id, owner))

    def pin(self, conversation_id: str, pinned: bool, *, owner: str | None = None) -> ConversationSummary:
        """Pin or unpin. Pinning again keeps the original time; neither counts as use."""
        with self._lock:
            self._row(conversation_id, owner)
            if pinned:
                self._db.execute(
                    "UPDATE conversations SET pinned_at = COALESCE(pinned_at, ?) WHERE id = ?",
                    (self._now(), conversation_id),
                )
            else:
                self._db.execute("UPDATE conversations SET pinned_at = NULL WHERE id = ?", (conversation_id,))
            return _summary(self._row(conversation_id, owner))

    def delete(self, conversation_id: str, *, owner: str | None = None) -> None:
        """Remove the conversation and its turns. One that is answering cannot be removed."""
        with self._lock:
            self._row(conversation_id, owner)
            if conversation_id in self._busy:
                raise ConversationBusy(conversation_id)
            self._db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

    def claim_unowned(self, owner: str) -> int:
        """Give every conversation from before accounts to this user. Returns how many."""
        with self._lock:
            return self._db.execute("UPDATE conversations SET owner = ? WHERE owner IS NULL", (owner,)).rowcount

    def close(self) -> None:
        self.database.close()

    def __len__(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]

    def _row(self, conversation_id: str, owner: str | None) -> sqlite3.Row:
        # Someone else's conversation is reported exactly like one that does not exist.
        row = self._db.execute(
            "SELECT * FROM conversations WHERE id = ? AND owner IS ?", (conversation_id, owner)
        ).fetchone()
        if row is None:
            raise UnknownConversation(conversation_id)
        return row

    def _now(self) -> str:
        """The time in UTC, never the same twice, so the order of use is always clear."""
        self._clock = max(datetime.now(timezone.utc), self._clock + timedelta(microseconds=1))
        return self._clock.isoformat(timespec="microseconds")

    def _evict(self, owner: str | None) -> None:
        """Keep each owner within the cap, so nobody's conversations push out anyone else's."""
        count = self._db.execute("SELECT COUNT(*) FROM conversations WHERE owner IS ?", (owner,)).fetchone()[0]
        excess = count - self.max_conversations
        if excess <= 0:
            return
        # Unpinned conversations go first, least recently used first; pinned ones only after.
        for (conversation_id,) in self._db.execute(
            "SELECT id FROM conversations WHERE owner IS ? ORDER BY pinned_at IS NOT NULL, updated_at", (owner,)
        ).fetchall():
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
        pinned_at=row["pinned_at"],
        last_model=row["last_model"],
        last_effort=row["last_effort"],
    )
