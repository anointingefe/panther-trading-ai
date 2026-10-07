# Video Review - Candle Box Strategy

Source video: `8c8c84378ac24d68ac57195dd7513497.mp4`

## Observed Concept

The video explains a multi-timeframe candle setup:

- Treat the previous higher-timeframe candle as a trading box.
- Watch lower-timeframe candles form inside that box.
- Use EMA and VWAP context as directional filters.
- Wait for a lower-timeframe candle confirmation before entry.
- Define a stop-loss and target around the lower-timeframe confirmation leg.

The practical idea is not to trade a candle alone. The higher-timeframe candle
sets context, while the lower-timeframe sequence provides timing.

## Implemented In PANTHER

PANTHER now has `CandleIntelligenceEngine`, which produces:

- previous daily candle high/low/midpoint box
- latest lower-timeframe position inside or outside the box
- EMA bias
- VWAP bias
- candle patterns such as doji, momentum, engulfing, rejection wick, and inside bar
- confirmation decision: bullish, bearish, or wait
- confirmation score

The dashboard now shows this as `Daily Box / 5m Confirmation`.

## Next Precision Step

When connected to real MT5 data, this module should use true broker candles:

- D1 for the box
- H1 for structure
- M5 or M15 for entry confirmation

Until then, it runs against the simulator and acts as a product and rules engine
checkpoint.
