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


def test_evolution_engine_reviews_latest_demo_loss() -> None:
    report = EvolutionEngine(minimum_closed_trades=30).evaluate(
        research={"scorecards": []},
        positions=[
            {
                "status": "closed",
                "symbol": "XAUUSD",
                "entry": 2400.0,
                "stop_loss": 2395.0,
                "volume": 0.01,
                "pnl": -0.05,
                "closed_at": "2026-10-08T18:00:00+00:00",
            }
        ],
        journal_entries=[],
    )

    assert report.loss_review["losses"] == 1
    assert report.loss_review["latestSymbol"] == "XAUUSD"
    assert report.loss_review["latestR"] == -1.0
    assert "Do not chase" in report.loss_review["actions"][0]


def test_snapshot_includes_learning_report() -> None:
    snapshot = build_dashboard_snapshot("config/demo.yaml", symbol="XAUUSD", record=False)

    assert snapshot["learning"]["status"] in {"learning", "ready_to_promote"}
    assert snapshot["learning"]["policy"]
    assert "loss_review" in snapshot["learning"]
