import pytest

from app.config import settings


@pytest.fixture
def open_browse_roots(monkeypatch):
    """Allow browsing anywhere for tests exercising listing behavior."""
    monkeypatch.setattr(settings, "allowed_browse_roots", ["/"])


class TestFileBrowser:
    def test_list_directory(self, client, tmp_path, open_browse_roots):
        (tmp_path / "sub").mkdir()
        (tmp_path / "test.pdf").write_bytes(b"%PDF-1.4 fake")
        (tmp_path / "test.txt").write_text("hello")

        resp = client.get("/api/files/browse", params={"path": str(tmp_path)})
        assert resp.status_code == 200
        entries = resp.json()
        names = {e["name"] for e in entries}
        assert "sub" in names
        assert "test.pdf" in names
        assert "test.txt" not in names

    def test_directory_entry_is_dir(self, client, tmp_path, open_browse_roots):
        (tmp_path / "sub").mkdir()
        resp = client.get("/api/files/browse", params={"path": str(tmp_path)})
        sub = next(e for e in resp.json() if e["name"] == "sub")
        assert sub["is_dir"] is True

    def test_nonexistent_path(self, client, open_browse_roots):
        resp = client.get("/api/files/browse", params={"path": "/nonexistent/path"})
        assert resp.status_code == 404

    def test_pdf_page_count(self, client, sample_duplex_pdf, open_browse_roots):
        resp = client.get("/api/files/info", params={"path": str(sample_duplex_pdf)})
        assert resp.status_code == 200
        assert resp.json()["page_count"] == 20


class TestBrowseRootEnforcement:
    def test_browse_outside_roots_forbidden(self, client, tmp_path, monkeypatch):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        monkeypatch.setattr(settings, "allowed_browse_roots", [str(allowed)])

        resp = client.get("/api/files/browse", params={"path": str(outside)})
        assert resp.status_code == 403

    def test_browse_inside_roots_allowed(self, client, tmp_path, monkeypatch):
        allowed = tmp_path / "allowed"
        (allowed / "sub").mkdir(parents=True)
        monkeypatch.setattr(settings, "allowed_browse_roots", [str(allowed)])

        resp = client.get("/api/files/browse", params={"path": str(allowed)})
        assert resp.status_code == 200

    def test_traversal_escape_forbidden(self, client, tmp_path, monkeypatch):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        monkeypatch.setattr(settings, "allowed_browse_roots", [str(allowed)])

        resp = client.get(
            "/api/files/browse", params={"path": str(allowed / ".." / "..")}
        )
        assert resp.status_code == 403

    def test_info_outside_roots_forbidden(self, client, sample_duplex_pdf, tmp_path, monkeypatch):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        monkeypatch.setattr(settings, "allowed_browse_roots", [str(allowed)])

        resp = client.get("/api/files/info", params={"path": str(sample_duplex_pdf)})
        assert resp.status_code == 403
