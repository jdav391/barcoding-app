from tests.test_routes.conftest import *  # noqa: reuse existing fixtures


class TestSessionRoutes:
    def test_create_session(self, client):
        r = client.post("/api/sessions", json={
            "name": "DLD Tuesday",
            "session_id": "2026-05-24-001",
            "date": "2026-05-24",
            "output_mode": "COMBINED",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "DLD Tuesday"
        assert data["session_id"] == "2026-05-24-001"
        assert data["output_mode"] == "COMBINED"

    def test_list_sessions(self, client):
        client.post("/api/sessions", json={
            "name": "Session A", "session_id": "2026-05-24-001",
        })
        client.post("/api/sessions", json={
            "name": "Session B", "session_id": "2026-05-24-002",
        })
        r = client.get("/api/sessions")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 2
        assert data[0]["session_id"] == "2026-05-24-002"

    def test_get_session(self, client):
        client.post("/api/sessions", json={
            "name": "Get Test", "session_id": "2026-05-24-010",
        })
        r = client.get("/api/sessions/2026-05-24-010")
        assert r.status_code == 200
        assert r.json()["name"] == "Get Test"

    def test_get_session_not_found(self, client):
        r = client.get("/api/sessions/nonexistent")
        assert r.status_code == 404

    def test_duplicate_session_id_rejected(self, client):
        client.post("/api/sessions", json={
            "name": "First", "session_id": "2026-05-24-DUP",
        })
        r = client.post("/api/sessions", json={
            "name": "Second", "session_id": "2026-05-24-DUP",
        })
        assert r.status_code == 409
