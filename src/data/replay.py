"""Deterministic replay primitives for offline strategy and backtest work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Sequence

from .loaders import NewsEvent, PriceBar


@dataclass(frozen=True, slots=True)
class ReplayStep:
    index: int
    bar: PriceBar
    news_events: tuple[NewsEvent, ...]


class DeterministicReplay(Iterator[ReplayStep]):
    """Stable iterator over bars with timestamp-scoped news events."""

    def __init__(self, bars: Sequence[PriceBar], news_events: Sequence[NewsEvent] | None = None) -> None:
        self._bars = tuple(sorted(bars, key=lambda bar: (bar.timestamp, bar.symbol, bar.timeframe)))
        self._events_by_ts = _group_news_by_timestamp(news_events or ())
        self._cursor = 0

    def __iter__(self) -> "DeterministicReplay":
        return self

    def __next__(self) -> ReplayStep:
        if self._cursor >= len(self._bars):
            raise StopIteration

        bar = self._bars[self._cursor]
        step = ReplayStep(
            index=self._cursor,
            bar=bar,
            news_events=self._events_by_ts.get(bar.timestamp, ()),
        )
        self._cursor += 1
        return step

    def __len__(self) -> int:
        return len(self._bars)

    def reset(self) -> None:
        self._cursor = 0

    def remaining(self) -> int:
        return len(self._bars) - self._cursor

    def snapshot(self) -> tuple[ReplayStep, ...]:
        """Return the full replay sequence without mutating iterator state."""

        return tuple(
            ReplayStep(
                index=index,
                bar=bar,
                news_events=self._events_by_ts.get(bar.timestamp, ()),
            )
            for index, bar in enumerate(self._bars)
        )


def build_replay(
    bars: Iterable[PriceBar], news_events: Iterable[NewsEvent] | None = None
) -> DeterministicReplay:
    return DeterministicReplay(tuple(bars), tuple(news_events or ()))


def _group_news_by_timestamp(events: Sequence[NewsEvent]) -> dict[object, tuple[NewsEvent, ...]]:
    grouped: dict[object, list[NewsEvent]] = {}
    for event in sorted(events, key=lambda item: (item.timestamp, item.symbol, item.source)):
        grouped.setdefault(event.timestamp, []).append(event)
    return {timestamp: tuple(items) for timestamp, items in grouped.items()}

