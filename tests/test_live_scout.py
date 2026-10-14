from __future__ import annotations

from datetime import datetime, timedelta, timezone

from panther_trading.brokers.base import Broker
from panther_trading.live_scout import LiveScoutStore, LiveScoutTrader
from panther_trading.models import BrokerStatus, Candle, OrderRequest, OrderResult, OrderStatus, SignalSide, TradeSignal


class ScoutBroker(Broker):
    def __init__(self) -> None:
        self.place_calls = 0

    def get_candles(self, symbol: str, timeframe: str, count: int) -> list[Candle]:
        now = datetime.now(timezone.utc)
        return [
            Candle(
                time=now - timedelta(minutes=(count - index) * 15),
                open=1.10,
                high=1.101,
                low=1.099,
                close=1.10,
                volume=100,
            )
            for index in range(count)
        ]

    def get_status(self) -> BrokerStatus:
        return BrokerStatus(
            name="Test Broker",
            connected=True,
            mode="demo",
            account_login="123",
            account_server="test",
            balance=10000,
            equity=10000,
            open_positions=0,
            symbols_total=1,
            message="connected",
        )

    def list_symbols(self) -> list[str]:
        return ["EURUSD"]

    def count_open_positions(self, symbol: str | None = None) -> int:
        return 0

    def place_order(self, request: OrderRequest) -> OrderResult:
        self.place_calls += 1
        return OrderResult(OrderStatus.ACCEPTED, "should not be called", "1")

    def calculate_position_volume(
        self,
        symbol: str,
        side: SignalSide,
        entry: float,
        stop_loss: float,
        risk_amount: float,
        max_volume: float,
    ) -> float:
        return min(0.01, max_volume)

    def execution_preflight(
        self,
        symbol: str,
        side: SignalSide,
        requested_volume: float,
        planned_entry: float,
        stop_loss: float,
        take_profit: float,
    ) -> dict:
        return {
            "broker_native": True,
            "executable": True,
            "symbol": symbol,
            "side": side.value,
            "planned_entry": planned_entry,
            "market_price": planned_entry,
            "requested_volume": requested_volume,
            "normalized_volume": requested_volume,
            "volume_valid": True,
            "bracket_valid": True,
            "blockers": [],
        }

    def get_closed_trades(self, days: int = 30) -> list:
        return []


def test_live_scout_emits_ticket_without_placing_order(tmp_path, monkeypatch) -> None:
    broker = ScoutBroker()

    def fixed_signal(self, symbol, candles, sentiment):
        return TradeSignal(
            symbol=symbol,
            side=SignalSide.BUY,
            confidence=0.92,
            entry=1.10,
            stop_loss=1.09,
            take_profit=1.12,
            rationale=("test setup",),
            generated_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr("panther_trading.live_scout.SmaSentimentStrategy.generate", fixed_signal)
    trader = LiveScoutTrader(
        "config/demo.yaml",
        state_path=tmp_path / "live_scout.json",
        positions_path=tmp_path / "positions.jsonl",
        goals_path=tmp_path / "goals.json",
        beast_mode_path=tmp_path / "beast.json",
        broker=broker,
    )

    cycle = trader.run_cycle()

    assert cycle.ready == 1
    assert cycle.decisions[0].ticket_id
    assert cycle.decisions[0].approval_required is True
    assert broker.place_calls == 0


def test_live_scout_store_returns_only_ready_ticket(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_text(
        '{"lastCycle":{"decisions":[{"ticket_id":"live-1","status":"ready"},{"ticket_id":"live-2","status":"blocked"}]}}',
        encoding="utf-8",
    )
    store = LiveScoutStore(path)

    assert store.ticket("live-1") is not None
    assert store.ticket("live-2") is None
