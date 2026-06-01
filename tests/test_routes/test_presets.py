VALID_PRESET = {
    "name": "Daily Single Sheet",
    "sheets_per_doc": 1,
    "page_format": "DUPLEX",
    "has_insert": False,
    "has_divert": False,
    "divert_overflow": False,
    "feed_direction": "ASCENDING",
    "id_source": "SEQUENTIAL",
    "embed_config": {
        "barcode": {
            "anchor": "bottom-right",
            "x_offset_pt": 36,
            "y_offset_pt": 36,
            "module_size_mm": 0.50,
            "quiet_zone_mm": 6.5,
            "dpi": 600,
        },
        "human_readable": {"enabled": False},
    },
}


class TestPresetCRUD:
    def test_create_preset(self, client):
        resp = client.post("/api/presets", json=VALID_PRESET)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Daily Single Sheet"
        assert data["id"] is not None

    def test_list_presets(self, client):
        client.post("/api/presets", json=VALID_PRESET)
        resp = client.get("/api/presets")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get_preset(self, client):
        create = client.post("/api/presets", json=VALID_PRESET)
        pid = create.json()["id"]
        resp = client.get(f"/api/presets/{pid}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Daily Single Sheet"

    def test_update_preset(self, client):
        create = client.post("/api/presets", json=VALID_PRESET)
        pid = create.json()["id"]
        updated = {**VALID_PRESET, "name": "Updated Name", "has_insert": True}
        resp = client.put(f"/api/presets/{pid}", json=updated)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"
        assert resp.json()["has_insert"] is True

    def test_delete_preset(self, client):
        create = client.post("/api/presets", json=VALID_PRESET)
        pid = create.json()["id"]
        resp = client.delete(f"/api/presets/{pid}")
        assert resp.status_code == 204
        resp = client.get(f"/api/presets/{pid}")
        assert resp.status_code == 404

    def test_get_nonexistent_returns_404(self, client):
        resp = client.get("/api/presets/999")
        assert resp.status_code == 404

    def test_invalid_sheets_per_doc(self, client):
        bad = {**VALID_PRESET, "sheets_per_doc": 0}
        resp = client.post("/api/presets", json=bad)
        assert resp.status_code == 422

    def test_create_preset_with_email_settings(self, client):
        r = client.post("/api/presets", json={
            "name": "Email Test",
            "sheets_per_doc": 1,
            "auto_email_enabled": True,
            "email_recipients": "shared@example.com, qa@example.com",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["auto_email_enabled"] is True
        assert data["email_recipients"] == "shared@example.com, qa@example.com"

    def test_create_preset_email_defaults(self, client):
        r = client.post("/api/presets", json={
            "name": "No Email",
            "sheets_per_doc": 1,
        })
        assert r.status_code == 201
        data = r.json()
        assert data["auto_email_enabled"] is False
        assert data["email_recipients"] is None
