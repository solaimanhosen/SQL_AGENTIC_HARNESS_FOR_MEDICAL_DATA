"""Limits on what the HTTP service may spend, so cost cannot become a denial of service.

Three limits apply before a question reaches the model:

- a number of questions answered at once, beyond which new ones are refused, not queued;
- a token budget per UTC day for the whole service, the real ceiling on cost;
- a token budget per conversation, so one long conversation cannot use up the day.

A question's cost is only known when it finishes, and a run keeps going even if the browser
leaves. So each run reserves an allowance when it starts, which counts against both budgets
until the run settles with what it actually used. A run that fails keeps its reservation,
since what it spent before failing is not known.

The ledger lives in memory, so a restart resets it. That is recorded as a residual risk in
docs/security.md.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone

# Held for a run until it settles. Logged questions so far used 13,000 to 45,000 tokens,
# with a median near 21,000, so this covers the costliest one seen with room to spare.
RUN_RESERVE_TOKENS = 60_000

# Conversations whose spending is remembered. Older ones are forgotten first, and a
# forgotten conversation is also gone from the conversation store, so nothing is lost.
MAX_TRACKED_CONVERSATIONS = 10_000


class LimitExceeded(RuntimeError):
    """A limit refused the question. `kind` says which, and the message says why."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


@dataclass(frozen=True)
class Reservation:
    conversation_id: str
    tokens: int
    day: date


class SpendingLimits:
    """Thread-safe accounting of runs in progress and tokens spent."""

    def __init__(
        self,
        *,
        max_concurrent_runs: int,
        daily_token_budget: int,
        conversation_token_budget: int,
        reserve_tokens: int = RUN_RESERVE_TOKENS,
        today: Callable[[], date] = lambda: datetime.now(timezone.utc).date(),
    ) -> None:
        self.max_concurrent_runs = max_concurrent_runs
        self.daily_token_budget = daily_token_budget
        self.conversation_token_budget = conversation_token_budget
        self.reserve_tokens = reserve_tokens
        self._today = today
        self._lock = threading.Lock()
        self._day = today()
        self._spent_today = 0
        self._reserved_today = 0
        self._running = 0
        self._conversations: OrderedDict[str, int] = OrderedDict()
        """Tokens spent or reserved by each conversation."""

    @classmethod
    def from_settings(cls, settings) -> "SpendingLimits":
        return cls(
            max_concurrent_runs=settings.max_concurrent_runs,
            daily_token_budget=settings.daily_token_budget,
            conversation_token_budget=settings.conversation_token_budget,
        )

    def reserve(self, conversation_id: str) -> Reservation:
        """Claim room for one run, or raise LimitExceeded. Every reservation must be settled."""
        with self._lock:
            self._roll_over()
            if self._running >= self.max_concurrent_runs:
                raise LimitExceeded(
                    "too_many_runs", "The service is answering as many questions as it allows. Try again shortly."
                )
            if self._spent_today + self._reserved_today + self.reserve_tokens > self.daily_token_budget:
                raise LimitExceeded(
                    "daily_budget", "The service has used its model budget for today. It resets at midnight UTC."
                )
            spent = self._conversations.get(conversation_id, 0)
            if spent + self.reserve_tokens > self.conversation_token_budget:
                raise LimitExceeded(
                    "conversation_budget", "This conversation has used its model budget. Start a new conversation."
                )
            self._running += 1
            self._reserved_today += self.reserve_tokens
            self._conversations[conversation_id] = spent + self.reserve_tokens
            self._conversations.move_to_end(conversation_id)
            while len(self._conversations) > MAX_TRACKED_CONVERSATIONS:
                self._conversations.popitem(last=False)
            return Reservation(conversation_id=conversation_id, tokens=self.reserve_tokens, day=self._day)

    def settle(self, reservation: Reservation, used_tokens: int | None) -> None:
        """Replace a reservation with what the run used, or keep it when that is unknown."""
        charged = reservation.tokens if used_tokens is None else used_tokens
        with self._lock:
            self._running -= 1
            if reservation.day == self._day:
                self._reserved_today -= reservation.tokens
                self._spent_today += charged
            if reservation.conversation_id in self._conversations:
                self._conversations[reservation.conversation_id] += charged - reservation.tokens
            self._roll_over()

    def usage(self) -> dict:
        with self._lock:
            self._roll_over()
            return {
                "day": self._day.isoformat(),
                "running": self._running,
                "max_concurrent_runs": self.max_concurrent_runs,
                "spent_today": self._spent_today,
                "reserved_today": self._reserved_today,
                "daily_token_budget": self.daily_token_budget,
            }

    def _roll_over(self) -> None:
        today = self._today()
        if today != self._day:
            # Runs still going from yesterday settle against yesterday, which is gone.
            self._day, self._spent_today, self._reserved_today = today, 0, 0
