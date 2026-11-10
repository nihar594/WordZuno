"""Configurable scoring rules."""
from __future__ import annotations

from dataclasses import dataclass

from config import Settings


@dataclass(frozen=True)
class Reward:
    base: int = 0
    streak_bonus: int = 0
    multiplayer_bonus: int = 0
    daily_bonus: int = 0
    daily_streak_bonus: int = 0

    @property
    def total(self) -> int:
        return (
            self.base + self.streak_bonus + self.multiplayer_bonus
            + self.daily_bonus + self.daily_streak_bonus
        )

    @property
    def bonus_total(self) -> int:
        return self.total - self.base


class Scoring:
    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def for_win(self, *, streak_after: int, participants: int, daily: bool, daily_streak: int = 0,
                attempts: int = 0, max_guesses: int = 30) -> Reward:
        s = self.s
        # fixed: POINTS_WIN every win. remaining: faster wins score more (max_guesses - guesses used, min 1)
        base = s.points_win if s.scoring_mode == "fixed" else max(1, max_guesses - attempts)
        return Reward(
            base=base,
            streak_bonus=s.streak_bonus if streak_after >= s.streak_min else 0,
            multiplayer_bonus=s.multiplayer_bonus if participants >= 2 else 0,
            daily_bonus=s.daily_bonus if daily else 0,
            daily_streak_bonus=(min(daily_streak, s.daily_streak_cap) * s.daily_streak_bonus) if daily else 0,
        )
