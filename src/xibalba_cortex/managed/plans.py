"""The approved monthly USD catalog. Limits are enforced, not merely advertised."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    monthly_cents: int
    max_memories: int
    writes_per_month: int
    retrievals_per_month: int

    def public(self) -> dict:
        return {**asdict(self), "currency": "usd", "interval": "month"}


PLANS = {
    "free": Plan("free", "Free", 0, 1_000, 250, 1_000),
    "pro": Plan("pro", "Pro", 2_900, 25_000, 5_000, 25_000),
    "team": Plan("team", "Team", 14_900, 250_000, 50_000, 250_000),
}
# Canceled or unpaid subscriptions retain read/export access to existing data. They do not
# regain a fresh free allowance: that would let a canceled paid account continue making writes.
WRITE_STATUSES = frozenset({"free", "active", "trialing"})
