from fastapi.testclient import TestClient

from recall.service import create_app


def test_fresh_and_repeated_migration(tmp_path):
    for _ in range(2):
        with TestClient(create_app(tmp_path / "test.db")) as client:
            assert client.get("/v1/health").json()["schema"] == "0007"


def test_owner_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("RECALL_TOKEN", "test-owner-token")
    with TestClient(create_app(tmp_path / "test.db")) as client:
        assert client.get("/v1/health").status_code == 401
        assert (
            client.get(
                "/v1/health", headers={"Authorization": "Bearer test-owner-token"}
            ).status_code
            == 200
        )
