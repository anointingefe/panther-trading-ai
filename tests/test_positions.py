from datetime import datetime, timezone

from panther_trading.models import ClosedTrade, SignalSide
from panther_trading.positions import PaperPositionBook


def _approved_entry() -> dict:
    return {
        "id": "sig-test",
        "symbol": "EURUSD",
        "side": "buy",
        "confidence": 0.82,
        "entry": 1.08,
        "stop_loss": 1.075,
        "take_profit": 1.09,
        "order_status": "simulated",
        "order_message": "Simulated buy order for EURUSD",
        "approval_status": "approved",
    }


def test_position_book_opens_approved_demo_position(tmp_path) -> None:
    book = PaperPositionBook(tmp_path / "positions.jsonl")

    position = book.open_from_journal(_approved_entry(), volume=0.01)

    assert position["status"] == "open"
    assert position["journal_entry_id"] == "sig-test"
    assert book.open_positions()[0]["id"] == position["id"]


def test_position_book_rejects_unapproved_entry(tmp_path) -> None:
    book = PaperPositionBook(tmp_path / "positions.jsonl")
    entry = {**_approved_entry(), "approval_status": "pending_approval"}

    try:
        book.open_from_journal(entry, volume=0.01)
    except ValueError as exc:
        assert "approved" in str(exc)
    else:
        raise AssertionError("Unapproved entries should not open positions")


def test_position_book_closes_open_position(tmp_path) -> None:
    book = PaperPositionBook(tmp_path / "positions.jsonl")
    position = book.open_from_journal(_approved_entry(), volume=1)

    closed = book.close(position["id"], close_price=1.085)

    assert closed["status"] == "closed"
    assert closed["close_reason"] == "manual_stop"
    assert closed["pnl"] == 0.005
    assert book.open_positions() == []


def test_position_book_does_not_duplicate_same_journal_entry(tmp_path) -> None:
    book = PaperPositionBook(tmp_path / "positions.jsonl")

    first = book.open_from_journal(_approved_entry(), volume=0.01)
    second = book.open_from_journal(_approved_entry(), volume=0.01)

    assert second["id"] == first["id"]
    assert len(book.latest()) == 1


def test_position_book_enforces_total_and_symbol_caps(tmp_path) -> None:
    book = PaperPositionBook(tmp_path / "positions.jsonl")
    first = book.open_from_journal(
        _approved_entry(), volume=0.01, max_open_positions=2, max_positions_per_symbol=1
    )
    second_entry = {**_approved_entry(), "id": "sig-test-2", "symbol": "GBPUSD"}
    book.open_from_journal(
        second_entry, volume=0.01, max_open_positions=2, max_positions_per_symbol=1
    )

    same_symbol = {**_approved_entry(), "id": "sig-test-3"}
    try:
        book.open_from_journal(
            same_symbol, volume=0.01, max_open_positions=3, max_positions_per_symbol=1
        )
    except ValueError as exc:
        assert "EURUSD" in str(exc)
    else:
        raise AssertionError("Per-symbol cap should reject a second EURUSD position")

    third_entry = {**_approved_entry(), "id": "sig-test-4", "symbol": "USDJPY"}
    try:
        book.open_from_journal(
            third_entry, volume=0.01, max_open_positions=2, max_positions_per_symbol=1
        )
    except ValueError as exc:
        assert "Maximum open demo positions" in str(exc)
    else:
        raise AssertionError("Total open-position cap should reject a third position")


def test_position_book_imports_verified_closed_trade_once(tmp_path) -> None:
    book = PaperPositionBook(tmp_path / "positions.jsonl")
    trade = ClosedTrade(
        external_id="mt5-pos-1",
        source="mt5",
        symbol="EURUSD",
        side=SignalSide.BUY,
        volume=0.1,
        entry=1.1,
        stop_loss=1.09,
        take_profit=1.12,
        close_price=1.115,
        pnl=0.0015,
        opened_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        closed_at=datetime(2026, 10, 1, 1, tzinfo=timezone.utc),
        broker_order_id="9002",
        comment="PANTHER demo trade",
    )

    first = book.import_closed_trade(trade)
    second = book.import_closed_trade(trade)

    assert first["id"] == second["id"]
    assert first["status"] == "closed"
    assert first["metadata"]["verified"] is True
    assert len(book.latest()) == 1
