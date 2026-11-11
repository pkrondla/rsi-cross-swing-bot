from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from rsi_cross_swing_bot.app.watch import (
    GATEWAY_RETRY_SEC,
    ScanResult,
    in_scan_window,
    scan_once,
    watch,
)
from rsi_cross_swing_bot.config.settings import RuntimeConfig
from rsi_cross_swing_bot.core.clock import ET, FixedClock
from rsi_cross_swing_bot.core.errors import DataUnavailableError
from rsi_cross_swing_bot.core.models import Bar
from rsi_cross_swing_bot.engine.signal_engine import IndicatorSnapshot
from rsi_cross_swing_bot.runtime.watchlist import (
    SymbolState,
    WatchEntry,
    add_entry,
    already_alerted,
    confirm_position,
    cross_direction,
    effective_long,
    ib_symbol,
    last_alert_text,
    load_entries,
    load_state,
    normalize_symbol,
    record_alert,
    remove_entry,
    save_state,
    set_mark,
    state_for,
)

RUNTIME = RuntimeConfig()
# The cross series below end on Monday 2023-12-18 (a NYSE session).
BAR_DAY = date(2023, 12, 18)


def at(hh: int, mm: int, day: date = BAR_DAY) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=ET)


class _Notifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send(self, text: str) -> None:
        self.messages.append(text)


class _Bars:
    def __init__(
        self,
        bars: list[Bar],
        *,
        per_symbol: dict[str, list[Bar]] | None = None,
        fail: dict[str, Exception] | None = None,
    ) -> None:
        self._bars = bars
        self._per_symbol = per_symbol or {}
        self._fail = fail or {}
        self.requested: list[str] = []

    def daily_bars(self, symbol: str, end: date, days: int) -> list[Bar]:
        self.requested.append(symbol)
        if symbol in self._fail:
            raise self._fail[symbol]
        return list(self._per_symbol.get(symbol, self._bars))


def _bars(closes: list[float], start: date = date(2023, 1, 2)) -> list[Bar]:
    day = start
    out: list[Bar] = []
    for close in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        out.append(Bar(session_date=day, open=close, high=close, low=close, close=close))
        day += timedelta(days=1)
    return out


def _series(step: float, last: float) -> list[Bar]:
    closes = [100.0]
    for _ in range(1, 250):
        closes.append(round(closes[-1] * step, 4))
    closes.append(round(closes[-1] * last, 4))
    return _bars(closes)


BULLISH = _series(0.997, 1.15)
BEARISH = _series(1.003, 0.85)
QUIET = _series(1.001, 1.001)


def _scan(
    data: _Bars,
    watch_dir: Path,
    notifier: _Notifier,
    now: datetime,
    warned: set[str] | None = None,
) -> ScanResult:
    return scan_once(
        now=now,
        runtime=RUNTIME,
        data=data,
        watch_dir=watch_dir,
        notifier=notifier,
        rsi_period=14,
        rsi_ma_period=14,
        ema_period=200,
        warned=warned,
    )


def _snapshot(rsi: float, ma: float, prev_rsi: float, prev_ma: float) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        session_date=date(2024, 6, 3),
        close=100.0,
        rsi=rsi,
        rsi_ma=ma,
        ema200=90.0,
        prev_rsi=prev_rsi,
        prev_rsi_ma=prev_ma,
    )


def test_fixture_series_cross_on_bar_day() -> None:
    assert BULLISH[-1].session_date == BAR_DAY
    assert BEARISH[-1].session_date == BAR_DAY
    assert QUIET[-1].session_date == BAR_DAY


# --- storage ---------------------------------------------------------------


def test_normalize_and_ib_symbol() -> None:
    assert normalize_symbol("aapl") == "AAPL"
    assert normalize_symbol(" brk.b ") == "BRK.B"
    assert normalize_symbol("") is None
    assert normalize_symbol("!!!") is None
    assert normalize_symbol("1abc") is None
    assert ib_symbol("BRK.B") == "BRK B"
    assert ib_symbol("AAPL") == "AAPL"


def test_add_remove_mark_roundtrip(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watch"
    assert load_entries(watch_dir) == []

    ok, _ = add_entry(watch_dir, "aapl", now="2024-06-03T14:00:00+00:00")
    assert ok
    ok, _ = add_entry(watch_dir, "AAPL")
    assert not ok
    (entry,) = load_entries(watch_dir)
    assert entry == WatchEntry(symbol="AAPL", added="2024-06-03T14:00:00+00:00")

    ok, _ = set_mark(watch_dir, "aapl", "long", now="2024-06-03T15:00:00+00:00")
    assert ok
    (entry,) = load_entries(watch_dir)
    assert entry.mark == "long"
    assert entry.mark_ts == "2024-06-03T15:00:00+00:00"
    ok, _ = set_mark(watch_dir, "msft", "flat")
    assert not ok

    ok, _ = remove_entry(watch_dir, "AAPL")
    assert ok
    ok, _ = remove_entry(watch_dir, "AAPL")
    assert not ok
    assert load_entries(watch_dir) == []


def test_writes_are_atomic_no_temp_files_left(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watch"
    add_entry(watch_dir, "AAPL")
    save_state(watch_dir, {"AAPL": SymbolState(long=True)})
    assert sorted(p.name for p in watch_dir.iterdir()) == ["state.json", "watchlist.json"]


def test_load_tolerates_corrupt_files(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir(parents=True)
    (watch_dir / "watchlist.json").write_text("not json", encoding="utf-8")
    (watch_dir / "state.json").write_text("[1,2]", encoding="utf-8")
    assert load_entries(watch_dir) == []
    assert load_state(watch_dir) == {}


# --- pure rules ------------------------------------------------------------


def test_effective_long_newest_of_mark_and_confirmed_position_wins() -> None:
    early, late = "2024-06-03T14:00:00+00:00", "2024-06-03T20:00:00+00:00"
    marked_long = WatchEntry(symbol="AAPL", mark="long", mark_ts=early)
    # Confirmed SELL after the mark: position wins (mark no longer sticky).
    assert effective_long(marked_long, SymbolState(long=False, position_ts=late)) is False
    # Mark after the last confirmed cross: mark wins.
    marked_flat = WatchEntry(symbol="AAPL", mark="flat", mark_ts=late)
    assert effective_long(marked_flat, SymbolState(long=True, position_ts=early)) is False
    # Mark with no confirmed cross yet.
    assert effective_long(marked_long, SymbolState()) is True
    # No mark: virtual position.
    assert effective_long(WatchEntry(symbol="AAPL"), SymbolState(long=True)) is True


def test_state_for_resets_when_symbol_re_added() -> None:
    stored = {"AAPL": SymbolState(added="t1", long=True, last_bullish_day="2024-06-03")}
    assert state_for(WatchEntry(symbol="AAPL", added="t1"), stored).long is True
    fresh = state_for(WatchEntry(symbol="AAPL", added="t2"), stored)
    assert fresh == SymbolState(added="t2")
    assert state_for(WatchEntry(symbol="MSFT", added="t3"), stored) == SymbolState(added="t3")


def test_cross_direction() -> None:
    assert cross_direction(_snapshot(55, 50, 49, 50)) == "bullish"
    assert cross_direction(_snapshot(45, 50, 51, 50)) == "bearish"
    assert cross_direction(_snapshot(55, 50, 52, 50)) is None
    assert cross_direction(_snapshot(50, 50, 50, 50)) is None


def test_dedupe_is_per_direction_so_flip_flop_alerts_once_each() -> None:
    day = date(2024, 6, 3)
    state = SymbolState()
    fired = []
    for direction in ("bullish", "bearish", "bullish", "bearish"):
        if not already_alerted(state, day, direction):
            fired.append(direction)
            state = record_alert(state, day, direction)
    assert fired == ["bullish", "bearish"]
    assert not already_alerted(state, date(2024, 6, 4), "bullish")
    assert last_alert_text(state) == "buy=2024-06-03 sell=2024-06-03"
    assert last_alert_text(SymbolState()) == ""


def test_confirm_position_once_per_bar_day() -> None:
    day = date(2024, 6, 3)
    state = confirm_position(SymbolState(), day, "bullish", now="2024-06-03T20:00:00+00:00")
    assert state.long is True
    again = confirm_position(state, day, "bearish", now="2024-06-04T14:00:00+00:00")
    assert again is state


# --- scan_once -------------------------------------------------------------


def test_forming_cross_alerts_but_does_not_move_position(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watch"
    add_entry(watch_dir, "AAPL")
    notifier = _Notifier()

    assert _scan(_Bars(BULLISH), watch_dir, notifier, at(10, 0)).alerts == 1
    msg = notifier.messages[0]
    assert "AAPL BUY signal" in msg
    assert "crossed above" in msg
    assert "forming bar 2023-12-18 @ 10:00 ET" in msg
    assert "position before signal: flat" in msg
    state = load_state(watch_dir)["AAPL"]
    assert state.long is False
    assert state.last_bullish_day == "2023-12-18"

    assert _scan(_Bars(BULLISH), watch_dir, notifier, at(11, 0)).alerts == 0
    assert len(notifier.messages) == 1


def test_cross_held_to_decision_confirms_without_second_alert(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watch"
    add_entry(watch_dir, "AAPL")
    notifier = _Notifier()
    _scan(_Bars(BULLISH), watch_dir, notifier, at(10, 0))

    assert _scan(_Bars(BULLISH), watch_dir, notifier, at(15, 58)).alerts == 0
    assert len(notifier.messages) == 1
    state = load_state(watch_dir)["AAPL"]
    assert state.long is True
    assert state.last_confirmed_day == "2023-12-18"


def test_cross_that_fades_by_close_leaves_position_unchanged(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watch"
    add_entry(watch_dir, "AAPL")
    notifier = _Notifier()
    _scan(_Bars(BULLISH), watch_dir, notifier, at(10, 0))

    _scan(_Bars(QUIET), watch_dir, notifier, at(15, 58))
    assert load_state(watch_dir)["AAPL"].long is False


def test_first_cross_at_decision_alerts_as_closing(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watch"
    add_entry(watch_dir, "TSLA")
    notifier = _Notifier()

    assert _scan(_Bars(BEARISH), watch_dir, notifier, at(15, 58)).alerts == 1
    assert "TSLA SELL signal" in notifier.messages[0]
    assert "closing bar 2023-12-18" in notifier.messages[0]
    assert load_state(watch_dir)["TSLA"].last_confirmed_day == "2023-12-18"


def test_prior_session_bar_is_closed_and_labelled_with_its_date(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watch"
    add_entry(watch_dir, "AAPL")
    notifier = _Notifier()
    next_morning = at(9, 30, date(2023, 12, 19))

    assert _scan(_Bars(BULLISH), watch_dir, notifier, next_morning).alerts == 1
    assert "closing bar 2023-12-18 @ 09:30 ET" in notifier.messages[0]
    assert load_state(watch_dir)["AAPL"].long is True


def test_manual_long_mark_is_overridden_by_confirmed_sell(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watch"
    add_entry(watch_dir, "AAPL")
    set_mark(watch_dir, "AAPL", "long", now="2023-12-18T14:00:00+00:00")
    notifier = _Notifier()

    _scan(_Bars(BEARISH), watch_dir, notifier, at(15, 58))
    assert "position before signal: long" in notifier.messages[0]
    (entry,) = load_entries(watch_dir)
    assert effective_long(entry, load_state(watch_dir)["AAPL"]) is False


def test_mark_after_confirm_wins_and_is_not_reconfirmed_next_morning(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watch"
    add_entry(watch_dir, "AAPL")
    notifier = _Notifier()
    _scan(_Bars(BULLISH), watch_dir, notifier, at(15, 58))
    set_mark(watch_dir, "AAPL", "flat")

    _scan(_Bars(BULLISH), watch_dir, notifier, at(9, 30, date(2023, 12, 19)))
    (entry,) = load_entries(watch_dir)
    assert effective_long(entry, load_state(watch_dir)["AAPL"]) is False


def test_remove_then_re_add_starts_fresh(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watch"
    add_entry(watch_dir, "AAPL", now="2023-12-18T14:00:00+00:00")
    notifier = _Notifier()
    _scan(_Bars(BULLISH), watch_dir, notifier, at(15, 58))
    remove_entry(watch_dir, "AAPL")
    add_entry(watch_dir, "AAPL", now="2023-12-18T21:30:00+00:00")

    (entry,) = load_entries(watch_dir)
    assert state_for(entry, load_state(watch_dir)) == SymbolState(added=entry.added)
    # Same day, same cross: re-added symbol alerts again.
    assert _scan(_Bars(BULLISH), watch_dir, notifier, at(15, 59)).alerts == 1


def test_removed_symbols_are_pruned_from_state(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watch"
    add_entry(watch_dir, "AAPL")
    add_entry(watch_dir, "MSFT")
    notifier = _Notifier()
    _scan(_Bars(BULLISH), watch_dir, notifier, at(10, 0))
    remove_entry(watch_dir, "MSFT")

    _scan(_Bars(BULLISH), watch_dir, notifier, at(11, 0))
    assert set(load_state(watch_dir)) == {"AAPL"}


def test_quiet_symbol_no_alert(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watch"
    add_entry(watch_dir, "MSFT")
    notifier = _Notifier()
    assert _scan(_Bars(QUIET), watch_dir, notifier, at(10, 0)).alerts == 0
    assert notifier.messages == []


def test_empty_watchlist_is_noop(tmp_path: Path) -> None:
    notifier = _Notifier()
    result = _scan(_Bars(BULLISH), tmp_path / "watch", notifier, at(10, 0))
    assert result == ScanResult(alerts=0)
    assert notifier.messages == []


def test_ib_spelling_used_for_share_classes(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watch"
    add_entry(watch_dir, "BRK.B")
    data = _Bars(QUIET)
    _scan(data, watch_dir, _Notifier(), at(10, 0))
    assert data.requested == ["BRK B"]


@pytest.mark.parametrize(
    "exc", [DataUnavailableError("connect failed"), ConnectionError("Not connected")]
)
def test_gateway_error_aborts_scan(tmp_path: Path, exc: Exception) -> None:
    watch_dir = tmp_path / "watch"
    add_entry(watch_dir, "AAPL")
    add_entry(watch_dir, "MSFT")
    notifier = _Notifier()
    data = _Bars(BULLISH, fail={"AAPL": exc})

    result = _scan(data, watch_dir, notifier, at(10, 0))
    assert result.gateway_error is not None
    assert result.alerts == 0
    assert data.requested == ["AAPL"]
    assert notifier.messages == []


def test_bad_symbol_warns_once_and_others_still_scan(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watch"
    add_entry(watch_dir, "AAPL")
    add_entry(watch_dir, "APPL")
    add_entry(watch_dir, "OOPS")
    notifier = _Notifier()
    warned: set[str] = set()
    data = _Bars(BULLISH, per_symbol={"APPL": []}, fail={"OOPS": ValueError("bad contract")})

    assert _scan(data, watch_dir, notifier, at(10, 0), warned).alerts == 1
    assert sum("no daily bars for APPL" in m for m in notifier.messages) == 1
    assert sum("no daily bars for OOPS" in m for m in notifier.messages) == 1

    _scan(data, watch_dir, notifier, at(11, 0), warned)
    assert sum("no daily bars" in m for m in notifier.messages) == 2


def test_indicators_not_ready_is_silent(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watch"
    add_entry(watch_dir, "AAPL")
    notifier = _Notifier()
    assert _scan(_Bars(_bars([100.0, 101.0, 102.0])), watch_dir, notifier, at(10, 0)).alerts == 0
    assert notifier.messages == []


# --- schedule and loop -----------------------------------------------------


def test_in_scan_window() -> None:
    assert not in_scan_window(at(9, 0), RUNTIME)
    assert in_scan_window(at(9, 30), RUNTIME)
    assert in_scan_window(at(13, 0), RUNTIME)
    assert in_scan_window(at(16, 2), RUNTIME)
    assert not in_scan_window(at(16, 10), RUNTIME)
    assert not in_scan_window(at(20, 0), RUNTIME)
    assert not in_scan_window(at(10, 0, date(2023, 12, 16)), RUNTIME)  # Saturday


def test_watch_once_scans_and_writes_heartbeat(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watchlist"
    add_entry(watch_dir, "AAPL")
    notifier = _Notifier()

    rc = watch(
        once=True,
        clock=FixedClock(at(10, 0)),
        notifier=notifier,
        data=_Bars(BULLISH),
        watch_dir=watch_dir,
    )

    assert rc == 0
    assert (watch_dir / "heartbeat.json").exists()
    assert any("watch started" in m for m in notifier.messages)
    assert any("BUY signal" in m for m in notifier.messages)


def test_watch_outside_window_only_heartbeats(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watchlist"
    add_entry(watch_dir, "AAPL")
    notifier = _Notifier()
    data = _Bars(BULLISH)

    rc = watch(
        once=True,
        clock=FixedClock(at(20, 0)),
        notifier=notifier,
        data=data,
        watch_dir=watch_dir,
    )

    assert rc == 0
    assert data.requested == []
    assert (watch_dir / "heartbeat.json").exists()


def test_watch_gateway_down_then_restored(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watchlist"
    add_entry(watch_dir, "AAPL")
    notifier = _Notifier()

    class _Flaky(_Bars):
        def __init__(self) -> None:
            super().__init__(BULLISH)
            self.calls = 0

        def daily_bars(self, symbol: str, end: date, days: int) -> list[Bar]:
            self.calls += 1
            if self.calls <= 2:
                raise ConnectionError("Not connected")
            return super().daily_bars(symbol, end, days)

    sleeps: list[float] = []

    def sleep_fn(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        watch(
            sleep_fn=sleep_fn,
            clock=FixedClock(at(10, 0)),
            notifier=notifier,
            data=_Flaky(),
            watch_dir=watch_dir,
        )

    assert sleeps == [GATEWAY_RETRY_SEC, GATEWAY_RETRY_SEC, 3600]
    assert sum("IB data unavailable" in m for m in notifier.messages) == 1
    assert sum("IB data restored" in m for m in notifier.messages) == 1
    assert any("BUY signal" in m for m in notifier.messages)


def test_watch_once_reports_unhealthy_without_heartbeat(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watchlist"
    add_entry(watch_dir, "AAPL")
    notifier = _Notifier()

    rc = watch(
        once=True,
        clock=FixedClock(at(10, 0)),
        notifier=notifier,
        data=_Bars(BULLISH, fail={"AAPL": DataUnavailableError("down")}),
        watch_dir=watch_dir,
    )

    assert rc == 1
    assert not (watch_dir / "heartbeat.json").exists()
    assert any("IB data unavailable" in m for m in notifier.messages)
