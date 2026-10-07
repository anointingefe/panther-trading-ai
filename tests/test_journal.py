from panther_trading.journal import TradeJournal


def _snapshot(order_status: str = "rejected") -> dict:
    return {
        "mode": "Paper",
        "symbol": "EURUSD",
        "signal": {
            "side": "sell",
            "confidence": 0.25,
            "entry": 1.08,
            "stop_loss": 1.09,
            "take_profit": 1.06,
            "rationale": ["test"],
        },
        "order": {
            "status": order_status,
            "message": "Signal confidence is below minimum",
        },
        "executionMode": {"active": "demo", "liveEnabled": False},
        "broker": {"mode": "paper"},
    }


def test_journal_records_risk_blocked_signal(tmp_path) -> None:
    journal = TradeJournal(tmp_path / "journal.jsonl")

    entry = journal.record_signal(_snapshot())

    assert entry.approval_status == "blocked_by_risk"
    assert journal.latest()[0]["id"] == entry.id


def test_journal_blocks_approval_for_risk_blocked_signal(tmp_path) -> None:
    journal = TradeJournal(tmp_path / "journal.jsonl")
    entry = journal.record_signal(_snapshot())

    try:
        journal.decide(entry.id, "approved")
    except ValueError as exc:
        assert "Risk-blocked" in str(exc)
    else:
        raise AssertionError("Risk-blocked signal approval should fail")


def test_journal_allows_pending_signal_rejection(tmp_path) -> None:
    journal = TradeJournal(tmp_path / "journal.jsonl")
    entry = journal.record_signal(_snapshot(order_status="simulated"))

    updated = journal.decide(entry.id, "rejected", note="Not good enough")

    assert updated["approval_status"] == "rejected"
    assert updated["decision_note"] == "Not good enough"
