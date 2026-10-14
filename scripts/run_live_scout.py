from __future__ import annotations

import time
from pathlib import Path

from panther_trading.config import load_config
from panther_trading.live_scout import LiveScoutRunner, LiveScoutTrader


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config/demo.yaml"


def main() -> None:
    config = load_config(CONFIG_PATH)
    trader = LiveScoutTrader(CONFIG_PATH)
    runner = LiveScoutRunner(trader, interval_seconds=config.live_scout.interval_seconds)
    runner.start()
    print(
        f"PANTHER live scout running every {config.live_scout.interval_seconds}s. "
        "Live submissions still require explicit approval."
    )
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        runner.stop()
        print("PANTHER live scout stopped")


if __name__ == "__main__":
    main()
