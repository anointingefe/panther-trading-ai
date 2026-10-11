from panther_trading.research import StrategyTrustGate


def test_strategy_gate_blocks_when_no_strategy_is_approved() -> None:
    decision = StrategyTrustGate().evaluate(
        {
            "scorecards": [
                {"name": "Fast Momentum", "status": "rejected", "profit_factor": 0.8, "net_r": -2.0}
            ]
        }
    )

    assert not decision.allowed
    assert decision.status == "blocked"
    assert decision.selected_strategy == "Fast Momentum"


def test_strategy_gate_allows_best_approved_strategy() -> None:
    decision = StrategyTrustGate().evaluate(
        {
            "scorecards": [
                {"name": "Cautious Swing", "status": "approved", "quality_score": 82, "profit_factor": 1.2, "net_r": 3.0},
                {"name": "Fast Momentum", "status": "approved", "quality_score": 70, "profit_factor": 1.8, "net_r": 2.0},
            ]
        }
    )

    assert decision.allowed
    assert decision.status == "approved"
    assert decision.selected_strategy == "Cautious Swing"
    assert "82/100" in decision.reason
