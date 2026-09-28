"""Validation failures must not echo one-time archive passwords."""

from fastapi.testclient import TestClient

from httpserver.main import create_app


def test_invalid_preflight_request_does_not_echo_secret(caplog):
    secret = "never-log-this-archive-password"
    app = create_app()
    response = TestClient(app).post(
        "/api/evidence-intake/jobs", json=[{"password": secret}]
    )
    assert response.status_code == 422
    assert secret not in response.text
    assert secret not in caplog.text
