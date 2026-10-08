from panther_trading.api.snapshot import build_dashboard_snapshot
from panther_trading.learning import EvolutionEngine


def test_evolution_engine_blocks_until_demo_sample_is_large_enough() -> None:
    report = EvolutionEngine(minimum_closed_trades=30).evaluate(
        research={
            "scorecards": [
                {
                    "name": "Trend SMA + Sentiment",
                    "status": "approved",
                    "profit_factor": 1.6,
                    "net_r": 8,
                    "out_of_sample_net_r": 2,
                }
            ]
        },
        positions=[],
        journal_entries=[],
    )

    assert report.status == "learning"
    assert report.promoted_strategy == "Trend SMA + Sentiment"
    assert "closed demo trades" in report.blockers[0]


def test_evolution_engine_can_mark_strategy_ready_after_demo_proof() -> None:
    positions = [
        {"status": "closed", "pnl": 3.0 if index % 2 == 0 else -1.0}
        for index in range(30)
    ]

    report = EvolutionEngine(minimum_closed_trades=30, minimum_profit_factor=1.2).evaluate(
        research={
            "scorecards": [
                {
                    "name": "Fast Momentum",
                    "status": "approved",
                    "profit_factor": 1.8,
                    "net_r": 12,
                    "out_of_sample_net_r": 4,
                }
            ]
        },
        positions=positions,
        journal_entries=[],
    )

    assert report.status == "ready_to_promote"
    assert report.blockers == ()


def test_snapshot_includes_learning_report() -> None:
    snapshot = build_dashboard_snapshot("config/demo.yaml", symbol="XAUUSD", record=False)

    assert snapshot["learning"]["status"] in {"learning", "ready_to_promote"}
    assert snapshot["learning"]["policy"]
