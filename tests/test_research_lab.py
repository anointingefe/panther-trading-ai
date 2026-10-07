from panther_trading.brokers.simulated import SimulatedBroker
from panther_trading.research import StrategyResearchLab


def test_research_lab_returns_ranked_strategy_scorecards() -> None:
    lab = StrategyResearchLab(SimulatedBroker())

    result = lab.run("EURUSD")

    assert result["symbol"] == "EURUSD"
    assert result["marketCondition"] in {"uptrend", "downtrend", "range", "volatile", "insufficient_data"}
    assert len(result["scorecards"]) == 3
    assert result["summary"]["bestStrategy"]
    assert result["precisionProfile"]["spreadCostR"] > 0


def test_research_scorecards_include_risk_metrics() -> None:
    result = StrategyResearchLab(SimulatedBroker()).run("XAUUSD")
    first = result["scorecards"][0]

    assert first["status"] in {"approved", "watch", "rejected", "incubating"}
    assert "profit_factor" in first
    assert "max_drawdown_r" in first
    assert "out_of_sample_net_r" in first
    assert "precision_grade" in first
    assert "notes" in first
