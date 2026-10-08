"""Bounded, short-lived, single-use confirmations for interactive actions."""

from dataclasses import dataclass
import secrets
import time


@dataclass(frozen=True)
class PendingConfirmation:
    action: str
    target_id: int
    actor: str
    expires_at: float


class ConfirmationStore:
    def __init__(self, ttl_seconds=300, max_pending=1000):
        self.ttl_seconds = ttl_seconds
        self.max_pending = max_pending
        self.pending = {}

    def issue(self, action, target_id, actor):
        now = time.monotonic()
        self.pending = {key: value for key, value in self.pending.items()
                        if value.expires_at > now}
        while len(self.pending) >= self.max_pending:
            self.pending.pop(next(iter(self.pending)))
        token = secrets.token_urlsafe(16)
        self.pending[token] = PendingConfirmation(
            action, target_id, actor, now + self.ttl_seconds,
        )
        return token

    def take(self, token, actor, *, action=None, target_id=None):
        pending = self.pending.get(token)
        if pending is None:
            return None
        if pending.expires_at <= time.monotonic():
            self.pending.pop(token)
            return None
        if (pending.actor != actor
                or (action is not None and pending.action != action)
                or (target_id is not None and pending.target_id != target_id)):
            return None
        return self.pending.pop(token)
