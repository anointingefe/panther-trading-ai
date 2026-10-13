from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from panther_trading.demo_auto import DemoAutoTrader, DemoAutoRunner
from panther_trading.live_auto import LiveAutoTrader, LiveAutoRunner


@pytest.mark.parametrize("kind", ["demo", "live"])
def test_overlapping_cycles_do_not_execute_twice(tmp_path, kind):
    if kind == "demo":
        trader = DemoAutoTrader("config/demo.yaml", tmp_path / "state.json")
    else:
        trader = LiveAutoTrader(
            "config/demo.yaml", tmp_path / "positions.jsonl",
            state_path=tmp_path / "state.json",
        )
    entered, release = Event(), Event()
    calls = []

    def cycle(**kwargs):
        calls.append(kwargs)
        entered.set()
        assert release.wait(3)
        return "completed"

    trader._run_cycle = cycle
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(trader.run_cycle)
        try:
            assert entered.wait(3)
            second = trader.run_cycle()
            assert second.status == "blocked"
            assert second.placed == 0
            assert "already in progress" in second.reasons[0]
            assert len(calls) == 1
        finally:
            release.set()
        assert first.result(timeout=3) == "completed"
    assert trader.run_cycle() == "completed"
    assert len(calls) == 2


@pytest.mark.parametrize("kind", ["demo", "live"])
def test_cycle_lock_is_released_after_exception(tmp_path, kind):
    if kind == "demo":
        trader = DemoAutoTrader("config/demo.yaml", tmp_path / "state.json")
    else:
        trader = LiveAutoTrader(
            "config/demo.yaml", tmp_path / "positions.jsonl",
            state_path=tmp_path / "state.json",
        )
    def failing(**kwargs):
        raise RuntimeError("test failure")
    trader._run_cycle = failing
    with pytest.raises(RuntimeError, match="test failure"):
        trader.run_cycle()
    trader._run_cycle = lambda **kwargs: "recovered"
    assert trader.run_cycle() == "recovered"


@pytest.mark.parametrize("runner_class", [DemoAutoRunner, LiveAutoRunner])
def test_stop_interrupts_interval_wait(runner_class):
    entered = Event()
    trader = SimpleNamespace(
        run_cycle=lambda **kwargs: entered.set(),
        latest_state=lambda: {},
        status=lambda: {},
    )
    runner = runner_class(trader, interval_seconds=3600)
    runner.start()
    try:
        assert entered.wait(3)
    finally:
        runner.stop()
        runner._thread.join(timeout=3)
    assert not runner._thread.is_alive()
