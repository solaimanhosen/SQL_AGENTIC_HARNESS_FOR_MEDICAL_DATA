"""Conversations kept by the HTTP service, so a follow-up question can be understood.

The store lives in memory. A restart forgets every conversation, which is acceptable for a
demonstration and keeps answers and SQL off the disk apart from the run log. One question
at a time may be answered in a conversation, since a second one asked before the first
finishes could not see its answer.
"""

from __future__ import annotations

import secrets
import threading
from collections import OrderedDict
from dataclasses import dataclass, field

from .agent import MAX_HISTORY_TURNS, Turn

DEFAULT_MAX_CONVERSATIONS = 1_000


class UnknownConversation(KeyError):
    """The conversation expired, was never started, or was forgotten by a restart."""


class ConversationBusy(RuntimeError):
    """The conversation is still answering an earlier question."""


@dataclass
class _Conversation:
    turns: list[Turn] = field(default_factory=list)
    asked: int = 0
    """Questions answered so far, including turns too old to be kept."""
    busy: bool = False


class ConversationStore:
    """Thread-safe, in memory, and bounded: the least recently used conversation goes first."""

    def __init__(self, *, max_conversations: int = DEFAULT_MAX_CONVERSATIONS, max_turns: int = MAX_HISTORY_TURNS):
        self.max_conversations = max_conversations
        self.max_turns = max_turns
        self._conversations: OrderedDict[str, _Conversation] = OrderedDict()
        self._lock = threading.Lock()

    def begin(self, conversation_id: str | None) -> tuple[str, tuple[Turn, ...], int]:
        """Claim a conversation for one question. Returns its id, its turns and the turn number.

        With no id, a new conversation is started. Every call must be matched by `finish`.
        """
        with self._lock:
            if conversation_id is None:
                conversation_id = secrets.token_hex(16)
                self._conversations[conversation_id] = _Conversation()
            conversation = self._conversations.get(conversation_id)
            if conversation is None:
                raise UnknownConversation(conversation_id)
            if conversation.busy:
                raise ConversationBusy(conversation_id)
            conversation.busy = True
            self._conversations.move_to_end(conversation_id)
            self._evict()
            return conversation_id, tuple(conversation.turns), conversation.asked + 1

    def finish(self, conversation_id: str, turn: Turn | None) -> None:
        """Release the conversation, recording the answered turn if there is one."""
        with self._lock:
            conversation = self._conversations.get(conversation_id)
            if conversation is None:
                return
            conversation.busy = False
            if turn is not None:
                conversation.turns = [*conversation.turns, turn][-self.max_turns :]
                conversation.asked += 1

    def __len__(self) -> int:
        with self._lock:
            return len(self._conversations)

    def _evict(self) -> None:
        idle = [key for key, conversation in self._conversations.items() if not conversation.busy]
        while len(self._conversations) > self.max_conversations and idle:
            del self._conversations[idle.pop(0)]
