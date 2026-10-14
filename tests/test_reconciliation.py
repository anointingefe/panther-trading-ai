from datetime import datetime, timezone

from panther_trading.live_ledger import LivePositionLedger
from panther_trading.models import OrderResult, OrderStatus, SignalSide, TradeSignal
from panther_trading.reconciliation import BrokerReconciler


def _signal() -> TradeSignal:
    return TradeSignal(
        symbol="EURUSD",
        side=SignalSide.BUY,
        confidence=0.8,
        entry=1.1,
        stop_loss=1.09,
        take_profit=1.12,
        rationale=("test",),
        generated_at=datetime.now(timezone.utc),
    )


class FakeBroker:
    def __init__(self, positions: list[dict]) -> None:
        self.positions = positions

    def open_positions(self) -> list[dict]:
        return self.positions


def test_reconciliation_matches_live_order_and_ignores_demo_positions(tmp_path) -> None:
    ledger = LivePositionLedger(tmp_path / "live.json")
    ledger.record_accepted(
        _signal(),
        0.01,
        OrderResult(OrderStatus.ACCEPTED, "ok", "123"),
        "PANTHER live auto",
    )
    broker = FakeBroker(
        [
            {
                "id": "123",
                "ticket": "123",
                "symbol": "EURUSD",
                "side": "buy",
                "volume": 0.01,
                "metadata": {"comment": "PANTHER live auto"},
            },
            {
                "id": "demo-1",
                "symbol": "GBPUSD",
                "side": "sell",
                "volume": 0.01,
                "metadata": {"comment": "PANTHER demo incubation"},
            },
        ]
    )

    report = BrokerReconciler().reconcile(ledger, broker)

    assert report.clean
    assert report.mismatch_count == 0
    assert report.broker_open_count == 1
    assert len(report.matched_open) == 1
    assert ledger.active()[0]["status"] == "reconciled"


def test_reconciliation_blocks_orphan_live_broker_position(tmp_path) -> None:
    ledger = LivePositionLedger(tmp_path / "live.json")
    broker = FakeBroker(
        [
            {
                "id": "999",
                "symbol": "EURUSD",
                "side": "buy",
                "volume": 0.01,
                "metadata": {"comment": "PANTHER live trade"},
            }
        ]
    )

    report = BrokerReconciler().reconcile(ledger, broker)

    assert not report.clean
    assert report.mismatch_count == 1
    assert report.orphan_broker_positions[0]["id"] == "999"
