from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketSymbol:
    symbol: str
    name: str
    group: str


DEFAULT_MARKET_UNIVERSE: tuple[MarketSymbol, ...] = (
    MarketSymbol("EURUSD", "Euro / US Dollar", "Forex Majors"),
    MarketSymbol("GBPUSD", "British Pound / US Dollar", "Forex Majors"),
    MarketSymbol("USDJPY", "US Dollar / Japanese Yen", "Forex Majors"),
    MarketSymbol("USDCHF", "US Dollar / Swiss Franc", "Forex Majors"),
    MarketSymbol("USDCAD", "US Dollar / Canadian Dollar", "Forex Majors"),
    MarketSymbol("AUDUSD", "Australian Dollar / US Dollar", "Forex Majors"),
    MarketSymbol("NZDUSD", "New Zealand Dollar / US Dollar", "Forex Majors"),
    MarketSymbol("EURGBP", "Euro / British Pound", "Forex Minors"),
    MarketSymbol("EURJPY", "Euro / Japanese Yen", "Forex Minors"),
    MarketSymbol("GBPJPY", "British Pound / Japanese Yen", "Forex Minors"),
    MarketSymbol("AUDJPY", "Australian Dollar / Japanese Yen", "Forex Minors"),
    MarketSymbol("CADJPY", "Canadian Dollar / Japanese Yen", "Forex Minors"),
    MarketSymbol("CHFJPY", "Swiss Franc / Japanese Yen", "Forex Minors"),
    MarketSymbol("EURAUD", "Euro / Australian Dollar", "Forex Minors"),
    MarketSymbol("GBPAUD", "British Pound / Australian Dollar", "Forex Minors"),
    MarketSymbol("EURCAD", "Euro / Canadian Dollar", "Forex Minors"),
    MarketSymbol("GBPCAD", "British Pound / Canadian Dollar", "Forex Minors"),
    MarketSymbol("USDZAR", "US Dollar / South African Rand", "Forex Exotics"),
    MarketSymbol("USDTRY", "US Dollar / Turkish Lira", "Forex Exotics"),
    MarketSymbol("USDMXN", "US Dollar / Mexican Peso", "Forex Exotics"),
    MarketSymbol("USDNOK", "US Dollar / Norwegian Krone", "Forex Exotics"),
    MarketSymbol("USDSEK", "US Dollar / Swedish Krona", "Forex Exotics"),
    MarketSymbol("XAUUSD", "Gold Spot / US Dollar", "Metals"),
    MarketSymbol("XAGUSD", "Silver Spot / US Dollar", "Metals"),
    MarketSymbol("XPTUSD", "Platinum Spot / US Dollar", "Metals"),
    MarketSymbol("XPDUSD", "Palladium Spot / US Dollar", "Metals"),
    MarketSymbol("USOIL", "WTI Crude Oil", "Energies"),
    MarketSymbol("UKOIL", "Brent Crude Oil", "Energies"),
    MarketSymbol("NATGAS", "Natural Gas", "Energies"),
    MarketSymbol("US30", "Dow Jones 30", "Indices"),
    MarketSymbol("US500", "S&P 500", "Indices"),
    MarketSymbol("NAS100", "Nasdaq 100", "Indices"),
    MarketSymbol("GER40", "Germany 40", "Indices"),
    MarketSymbol("UK100", "FTSE 100", "Indices"),
    MarketSymbol("FRA40", "France 40", "Indices"),
    MarketSymbol("JPN225", "Japan 225", "Indices"),
    MarketSymbol("BTCUSD", "Bitcoin / US Dollar", "Crypto"),
    MarketSymbol("ETHUSD", "Ethereum / US Dollar", "Crypto"),
    MarketSymbol("SOLUSD", "Solana / US Dollar", "Crypto"),
    MarketSymbol("XRPUSD", "XRP / US Dollar", "Crypto"),
    MarketSymbol("LTCUSD", "Litecoin / US Dollar", "Crypto"),
    MarketSymbol("AAPL", "Apple CFD", "Stock CFDs"),
    MarketSymbol("MSFT", "Microsoft CFD", "Stock CFDs"),
    MarketSymbol("NVDA", "NVIDIA CFD", "Stock CFDs"),
    MarketSymbol("TSLA", "Tesla CFD", "Stock CFDs"),
    MarketSymbol("AMZN", "Amazon CFD", "Stock CFDs"),
    MarketSymbol("META", "Meta CFD", "Stock CFDs"),
    MarketSymbol("GOOGL", "Alphabet CFD", "Stock CFDs"),
)


def market_universe() -> list[dict[str, str]]:
    return [
        {"symbol": item.symbol, "name": item.name, "group": item.group}
        for item in DEFAULT_MARKET_UNIVERSE
    ]


def default_watchlist(limit: int = 12) -> list[MarketSymbol]:
    return list(DEFAULT_MARKET_UNIVERSE[:limit])
