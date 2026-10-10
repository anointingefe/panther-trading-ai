from http import HTTPStatus

from panther_trading.api.server import PantherRequestHandler


class DisconnectingHandler:
    _client_disconnect_errors = PantherRequestHandler._client_disconnect_errors

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        pass

    def end_headers(self):
        raise ConnectionAbortedError("client closed request")


def test_send_json_suppresses_client_disconnect_traceback() -> None:
    handler = DisconnectingHandler()

    PantherRequestHandler._send_json(handler, {"status": "ok"}, status=HTTPStatus.OK)

    assert handler.status == HTTPStatus.OK


if __name__ == "__main__":
    test_send_json_suppresses_client_disconnect_traceback()
