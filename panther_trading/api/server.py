from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from panther_trading.api.snapshot import broker_status, build_dashboard_snapshot
from panther_trading.config import load_config
from panther_trading.data.markets import market_universe
from panther_trading.journal import TradeJournal
from panther_trading.live_guard import LiveTradingGate
from panther_trading.demo_auto import DemoAutoRunner, DemoAutoTrader
from panther_trading.positions import PaperPositionBook
from panther_trading.research import StrategyResearchLab
from panther_trading.brokers import create_broker
from panther_trading.validation import EdgeValidationGate


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = PROJECT_ROOT / "web"
JOURNAL = TradeJournal(PROJECT_ROOT / "var/trade_journal.jsonl")
POSITIONS = PaperPositionBook(PROJECT_ROOT / "var/paper_positions.jsonl")
DEMO_AUTO = DemoAutoRunner(
    DemoAutoTrader(PROJECT_ROOT / "config/demo.yaml", PROJECT_ROOT / "var/demo_auto_state.json"),
    interval_seconds=load_config(PROJECT_ROOT / "config/demo.yaml").demo_auto.interval_seconds,
)


class PantherRequestHandler(BaseHTTPRequestHandler):
    server_version = "PantherTradingHTTP/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/health":
            self._send_json({"status": "ok"})
            return
        if path == "/api/markets":
            self._send_json({"markets": market_universe()})
            return
        if path == "/api/broker/status":
            broker = parse_qs(parsed.query).get("broker", [None])[0]
            self._send_json({"broker": broker_status(kind=broker)})
            return
        if path == "/api/live/readiness":
            self._send_json({"liveReadiness": self._live_readiness()})
            return
        if path == "/api/validation/edge":
            self._send_json({"edgeValidation": self._edge_validation()})
            return
        if path == "/api/demo-auto/status":
            self._send_json({"demoAuto": DEMO_AUTO.status()})
            return
        if path == "/api/research/strategies":
            query = parse_qs(parsed.query)
            symbol = query.get("symbol", ["EURUSD"])[0].upper()
            timeframe = query.get("timeframe", ["M15"])[0].upper()
            self._send_json(StrategyResearchLab(create_broker("simulated")).run(symbol, timeframe=timeframe))
            return
        if path == "/api/journal":
            self._send_json({"entries": JOURNAL.latest()})
            return
        if path == "/api/positions":
            self._send_json({"positions": POSITIONS.latest()})
            return
        if path == "/api/snapshot":
            symbol = parse_qs(parsed.query).get("symbol", [None])[0]
            self._send_json(build_dashboard_snapshot(PROJECT_ROOT / "config/demo.yaml", symbol=symbol))
            return
        self._send_static(path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/journal/decision":
            try:
                payload = self._read_json_body()
                updated = JOURNAL.decide(
                    entry_id=str(payload["id"]),
                    decision=str(payload["decision"]),
                    note=payload.get("note"),
                )
                position = None
                if updated["approval_status"] == "approved":
                    config = load_config(PROJECT_ROOT / "config/demo.yaml")
                    position = POSITIONS.open_from_journal(
                        updated,
                        volume=config.execution.default_volume,
                        max_open_positions=config.risk.max_open_positions,
                        max_positions_per_symbol=config.risk.max_positions_per_symbol,
                    )
                self._send_json({"entry": updated, "position": position})
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/positions/close":
            try:
                payload = self._read_json_body()
                updated = POSITIONS.close(
                    position_id=str(payload["id"]),
                    reason=str(payload.get("reason", "manual_stop")),
                    close_price=payload.get("closePrice"),
                )
                self._send_json({"position": updated})
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/positions/close-all":
            try:
                payload = self._read_json_body()
                closed = POSITIONS.close_all(reason=str(payload.get("reason", "emergency_stop")))
                self._send_json({"positions": closed})
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/live/arm":
            try:
                payload = self._read_json_body()
                readiness = self._live_readiness(
                    approval_status=payload.get("approvalStatus"),
                    requested_volume=payload.get("volume"),
                    unlock_phrase=payload.get("unlockPhrase"),
                )
                status = HTTPStatus.OK if readiness["armed"] else HTTPStatus.FORBIDDEN
                self._send_json({"liveReadiness": readiness}, status=status)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/mt5/sync-history":
            try:
                payload = self._read_json_body()
                days = int(payload.get("days", 30))
                if days < 1 or days > 365:
                    raise ValueError("History sync days must be between 1 and 365")
                broker = create_broker("mt5")
                if not hasattr(broker, "get_closed_trades"):
                    raise ValueError("Configured broker cannot export closed trades")
                imported = [
                    POSITIONS.import_closed_trade(trade)
                    for trade in broker.get_closed_trades(days=days)  # type: ignore[attr-defined]
                ]
                self._send_json(
                    {
                        "imported": len(imported),
                        "positions": imported,
                        "edgeValidation": self._edge_validation(),
                    }
                )
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/demo-auto/cycle":
            try:
                self._send_json({"demoAuto": DEMO_AUTO.run_once()})
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/demo-auto/start":
            try:
                self._send_json({"demoAuto": DEMO_AUTO.start()})
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/demo-auto/stop":
            self._send_json({"demoAuto": DEMO_AUTO.stop()})
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        payload = json.loads(body or "{}")
        if not isinstance(payload, dict):
            raise ValueError("Expected JSON object")
        return payload

    def _live_readiness(
        self,
        approval_status: str | None = None,
        requested_volume: float | None = None,
        unlock_phrase: str | None = None,
    ) -> dict:
        config = load_config(PROJECT_ROOT / "config/demo.yaml")
        edge_validation = self._edge_validation()
        readiness = LiveTradingGate(config.execution).readiness(
            broker_status=broker_status(),
            approval_status=approval_status,
            requested_volume=requested_volume,
            unlock_phrase=unlock_phrase,
            edge_validation_status=edge_validation["status"],
        )
        return {
            "enabled": readiness.enabled,
            "armed": readiness.armed,
            "reasons": list(readiness.reasons),
            "checklist": list(readiness.checklist),
        }

    def _edge_validation(self) -> dict:
        config = load_config(PROJECT_ROOT / "config/demo.yaml")
        return EdgeValidationGate(config.validation).evaluate(POSITIONS.latest(limit=1000)).to_dict()

    def _send_static(self, path: str) -> None:
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        target = (WEB_ROOT / relative).resolve()

        if not target.is_file() or WEB_ROOT not in target.parents:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run(host: str = "127.0.0.1", port: int = 8080) -> None:
    server = ThreadingHTTPServer((host, port), PantherRequestHandler)
    print(f"PANTHER dashboard running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping PANTHER dashboard")
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PANTHER dashboard server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8080, type=int)
    args = parser.parse_args()
    run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
