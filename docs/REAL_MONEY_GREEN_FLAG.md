# Panther real-money green flag

Panther must not move from demo evidence to real-money trading because of hype, a few lucky wins, or a manual feeling that the market looks good. The final promotion check is the real-money green flag.

The green flag is stricter than the base edge-validation gate. Edge validation proves that the demo strategy has positive evidence. The green flag asks whether the evidence is clean enough to even consider a tiny live deployment.

## Required proof before live funding

Panther now requires all of the following before the green flag can pass:

- at least 100 closed demo trades
- at least 20 separate demo trading days
- base demo edge validation must already pass
- every closed demo trade must have a recorded stop loss
- almost every closed demo trade must have a recorded take-profit target
- the last 20 closed trades must hold at least 48% win rate
- the last 20 closed trades must hold at least 1.35 profit factor
- the last 20 closed trades must be at least +3R net
- recent drawdown must stay below 4R
- current loss streak must not exceed 4 losses
- MT5 must be connected for the final live check

The live guard consumes the green-flag result. If the green flag is still building evidence or blocked, live auto execution remains blocked even if the older edge-validation gate passes.

## API

Read the final promotion status from:

```http
GET /api/live/green-flag
```

Dashboard snapshots also include:

```json
{
  "greenFlag": {
    "status": "building_evidence",
    "passed": false,
    "score": 0,
    "reasons": [],
    "closed_trades": 0,
    "recent_trades": 0,
    "protected_trade_rate": 0,
    "take_profit_rate": 0,
    "recent_win_rate": 0,
    "recent_profit_factor": 0,
    "recent_net_r": 0,
    "recent_max_drawdown_r": 0,
    "consecutive_losses": 0
  }
}
```

## What this means operationally

A green flag is not a profit guarantee. It is a deployment safety gate. If it passes, the first live phase should still use the smallest practical lot size and a small starting balance. Panther should then compare live execution quality against demo execution before any scaling.

If the green flag fails, do not fund live trading yet. Keep collecting demo trades, sync MT5 history, study the blockers, and let Panther repair the weakest markets or sessions.
