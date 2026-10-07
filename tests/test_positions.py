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
