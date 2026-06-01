import io

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas as pdf_canvas

VALID_TEMPLATE = {
    "name": "Test Template",
    "description": "A test template for unit tests",
    "page_format": "DUPLEX",
    "has_insert": False,
    "feed_direction": "ASCENDING",
}

VALID_REGION = {
    "name": "Account Number",
    "role": "GROUP_BOUNDARY",
    "page": 1,
    "x": 72,
    "y": 690,
    "width": 200,
    "height": 25,
    "match_type": "REGEX",
    "match_pattern": r"Account:\s*(\d+)",
    "priority": 0,
}


class TestTemplateCRUD:
    def test_create_template(self, client):
        resp = client.post("/api/templates", json=VALID_TEMPLATE)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test Template"
        assert data["id"] is not None
        assert data["description"] == "A test template for unit tests"
        assert data["page_format"] == "DUPLEX"

    def test_list_templates(self, client):
        client.post("/api/templates", json=VALID_TEMPLATE)
        resp = client.get("/api/templates")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get_template(self, client):
        create = client.post("/api/templates", json=VALID_TEMPLATE)
        tid = create.json()["id"]
        resp = client.get(f"/api/templates/{tid}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test Template"

    def test_update_template(self, client):
        create = client.post("/api/templates", json=VALID_TEMPLATE)
        tid = create.json()["id"]
        updated = {**VALID_TEMPLATE, "name": "Updated Name", "has_insert": True}
        resp = client.put(f"/api/templates/{tid}", json=updated)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"
        assert resp.json()["has_insert"] is True

    def test_delete_template(self, client):
        create = client.post("/api/templates", json=VALID_TEMPLATE)
        tid = create.json()["id"]
        resp = client.delete(f"/api/templates/{tid}")
        assert resp.status_code == 204
        resp = client.get(f"/api/templates/{tid}")
        assert resp.status_code == 404

    def test_get_nonexistent_returns_404(self, client):
        resp = client.get("/api/templates/999")
        assert resp.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.delete("/api/templates/999")
        assert resp.status_code == 404

    def test_update_nonexistent_returns_404(self, client):
        resp = client.put("/api/templates/999", json=VALID_TEMPLATE)
        assert resp.status_code == 404

    def test_create_template_with_custom_embed(self, client):
        data = {
            **VALID_TEMPLATE,
            "embed_config": {
                "barcode": {
                    "anchor": "top-left",
                    "x_offset_pt": 18,
                    "y_offset_pt": 18,
                    "module_size_mm": 0.75,
                    "quiet_zone_mm": 4.0,
                    "dpi": 300,
                },
                "human_readable": {"enabled": False},
            },
        }
        resp = client.post("/api/templates", json=data)
        assert resp.status_code == 201
        assert resp.json()["embed_config"]["barcode"]["anchor"] == "top-left"
        assert resp.json()["embed_config"]["barcode"]["module_size_mm"] == 0.75


class TestRegionCRUD:
    def test_create_region(self, client):
        create = client.post("/api/templates", json=VALID_TEMPLATE)
        tid = create.json()["id"]
        resp = client.post(f"/api/templates/{tid}/regions", json=VALID_REGION)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Account Number"
        assert data["template_id"] == tid
        assert data["role"] == "GROUP_BOUNDARY"

    def test_update_region(self, client):
        create = client.post("/api/templates", json=VALID_TEMPLATE)
        tid = create.json()["id"]
        region = client.post(f"/api/templates/{tid}/regions", json=VALID_REGION).json()
        updated = {**VALID_REGION, "name": "Updated Region", "priority": 5}
        resp = client.put(
            f"/api/templates/{tid}/regions/{region['id']}", json=updated
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Region"
        assert resp.json()["priority"] == 5

    def test_delete_region(self, client):
        create = client.post("/api/templates", json=VALID_TEMPLATE)
        tid = create.json()["id"]
        region = client.post(f"/api/templates/{tid}/regions", json=VALID_REGION).json()
        resp = client.delete(f"/api/templates/{tid}/regions/{region['id']}")
        assert resp.status_code == 204

    def test_save_all_regions(self, client):
        create = client.post("/api/templates", json=VALID_TEMPLATE)
        tid = create.json()["id"]
        regions_data = [
            {
                "name": "Region 1",
                "role": "GROUP_BOUNDARY",
                "page": 1,
                "x": 72, "y": 700,
                "width": 200, "height": 30,
                "match_type": "REGEX",
                "match_pattern": r"Account:\s*(\d+)",
                "priority": 0,
            },
            {
                "name": "Region 2",
                "role": "PAGE_COUNTER",
                "page": 1,
                "x": 72, "y": 670,
                "width": 200, "height": 30,
                "match_type": "REGEX",
                "match_pattern": r"Page \d+ of \d+",
                "priority": 1,
            },
        ]
        resp = client.put(
            f"/api/templates/{tid}/regions",
            json={"regions": regions_data},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_save_regions_replaces_existing(self, client):
        """PUT /regions should replace existing regions, not append."""
        create = client.post("/api/templates", json=VALID_TEMPLATE)
        tid = create.json()["id"]
        # Create one region
        client.post(f"/api/templates/{tid}/regions", json=VALID_REGION)
        # Replace with two regions
        regions_data = [
            {
                "name": "Replacement A",
                "role": "GROUP_BOUNDARY",
                "page": 1,
                "x": 72, "y": 700,
                "width": 200, "height": 30,
                "match_type": "EXACT",
                "match_pattern": None,
                "priority": 0,
            },
            {
                "name": "Replacement B",
                "role": "CUSTOM",
                "page": 1,
                "x": 100, "y": 100,
                "width": 50, "height": 50,
                "match_type": "NUMERIC",
                "match_pattern": None,
                "priority": 2,
            },
        ]
        resp = client.put(
            f"/api/templates/{tid}/regions",
            json={"regions": regions_data},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_region_on_nonexistent_template_returns_404(self, client):
        resp = client.post("/api/templates/999/regions", json=VALID_REGION)
        assert resp.status_code == 404


class TestTemplateUploadAndDetect:
    def test_upload_sample(self, client):
        create = client.post("/api/templates", json=VALID_TEMPLATE)
        tid = create.json()["id"]

        buf = io.BytesIO()
        c = pdf_canvas.Canvas(buf, pagesize=letter)
        c.drawString(72, 700, "Test Page")
        c.save()
        buf.seek(0)

        resp = client.post(
            f"/api/templates/{tid}/upload-sample",
            files={"file": ("sample.pdf", buf, "application/pdf")},
        )
        assert resp.status_code == 200
        assert "sample_url" in resp.json()

    def test_serve_sample(self, client):
        create = client.post("/api/templates", json=VALID_TEMPLATE)
        tid = create.json()["id"]

        buf = io.BytesIO()
        c = pdf_canvas.Canvas(buf, pagesize=letter)
        c.drawString(72, 700, "Test Page")
        c.save()
        buf.seek(0)

        client.post(
            f"/api/templates/{tid}/upload-sample",
            files={"file": ("sample.pdf", buf, "application/pdf")},
        )
        resp = client.get(f"/api/templates/{tid}/sample")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"

    def test_serve_sample_not_found(self, client):
        resp = client.get("/api/templates/999/sample")
        assert resp.status_code == 404

    def test_detect_no_sample_returns_400(self, client):
        create = client.post("/api/templates", json=VALID_TEMPLATE)
        tid = create.json()["id"]
        resp = client.post(f"/api/templates/{tid}/test-detect")
        assert resp.status_code == 400

    def test_detect_on_sample_multi_doc(self, client, sample_multi_doc_pdf):
        """Run detection on the sample multi-doc PDF and verify 3 docs detected."""
        create = client.post("/api/templates", json=VALID_TEMPLATE)
        tid = create.json()["id"]

        # Upload the sample multi-doc PDF
        with open(sample_multi_doc_pdf, "rb") as f:
            resp = client.post(
                f"/api/templates/{tid}/upload-sample",
                files={"file": ("sample.pdf", f, "application/pdf")},
            )
        assert resp.status_code == 200

        # Create regions matching the sample_multi_doc_pdf content layout.
        # The PDF draws at reportlab coordinates: x=72, y varies.
        # Doc 1: y=700 "Account: 1001", y=680 "Page 1 of 1", y=660 "ID: 123456789"
        # Doc 2: y=700 "Account: 1002", y=680 "Page 1 of 2", y=660 "ID: 987654321"
        # Doc 3: y=700 "Account: 1003", y=680 "Page 1 of 1", y=660 "ID: 555666777"

        group_region = {
            "name": "Account Number",
            "role": "GROUP_BOUNDARY",
            "page": 1,
            "x": 72,
            "y": 690,
            "width": 200,
            "height": 25,
            "match_type": "REGEX",
            "match_pattern": r"Account:\s*(\d+)",
            "priority": 0,
        }
        counter_region = {
            "name": "Page Counter",
            "role": "PAGE_COUNTER",
            "page": 1,
            "x": 72,
            "y": 670,
            "width": 200,
            "height": 25,
            "match_type": "REGEX",
            "match_pattern": r"Page \d+ of \d+",
            "priority": 0,
        }
        uid_region = {
            "name": "Unique ID",
            "role": "UNIQUE_ID",
            "page": 1,
            "x": 72,
            "y": 650,
            "width": 200,
            "height": 25,
            "match_type": "REGEX",
            "match_pattern": r"ID:\s*(\d+)",
            "priority": 0,
        }

        client.post(f"/api/templates/{tid}/regions", json=group_region)
        client.post(f"/api/templates/{tid}/regions", json=counter_region)
        client.post(f"/api/templates/{tid}/regions", json=uid_region)

        resp = client.post(
            f"/api/templates/{tid}/test-detect",
            json={"page_format": "DUPLEX"},
        )
        assert resp.status_code == 200
        data = resp.json()
        docs = data["docs"]
        assert len(docs) == 3  # 3 documents

        # Doc 1: 1 sheet, ID 123456789
        assert docs[0]["sheet_count"] == 1
        assert docs[0]["unique_id"] == 123456789
        # Doc 2: 2 sheets, ID 987654321
        assert docs[1]["sheet_count"] == 2
        assert docs[1]["unique_id"] == 987654321
        # Doc 3: 1 sheet, ID 555666777
        assert docs[2]["sheet_count"] == 1
        assert docs[2]["unique_id"] == 555666777

    def test_detect_uses_template_page_format_by_default(self, client, sample_multi_doc_pdf):
        """When no page_format is sent in the request, use the template's default."""
        create = client.post(
            "/api/templates",
            json={**VALID_TEMPLATE, "page_format": "DUPLEX"},
        )
        tid = create.json()["id"]

        with open(sample_multi_doc_pdf, "rb") as f:
            client.post(
                f"/api/templates/{tid}/upload-sample",
                files={"file": ("sample.pdf", f, "application/pdf")},
            )

        group_region = {
            "name": "Account Number",
            "role": "GROUP_BOUNDARY",
            "page": 1,
            "x": 72, "y": 690,
            "width": 200, "height": 25,
            "match_type": "REGEX",
            "match_pattern": r"Account:\s*(\d+)",
            "priority": 0,
        }
        client.post(f"/api/templates/{tid}/regions", json=group_region)

        resp = client.post(f"/api/templates/{tid}/test-detect")
        assert resp.status_code == 200
        assert len(resp.json()["docs"]) == 3
