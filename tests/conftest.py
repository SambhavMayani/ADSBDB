"""No internet in default tests. Loopback supports isolated HTTP/Chroma checks."""
import socket
import pytest


@pytest.fixture(autouse=True)
def offline_by_default(monkeypatch, request):
    if request.node.get_closest_marker('models'):
        return
    original = socket.socket.connect
    def connect(sock, address):
        if isinstance(address, tuple) and len(address) > 1 and address[1] in (9000, 9001):
            raise AssertionError('Production MinIO endpoints are forbidden in pytest')
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', 'localhost', '::1'):
            raise AssertionError('Unexpected external network in offline test')
        return original(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', connect)
    monkeypatch.setenv('HF_HUB_OFFLINE', '1')
    monkeypatch.setenv('TRANSFORMERS_OFFLINE', '1')
    monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'False')
    monkeypatch.delenv('SECURITY_ALERT_WEBHOOK_URL', raising=False)
