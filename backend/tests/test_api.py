import unittest
import io
import json
import zipfile
from fastapi.testclient import TestClient
from app.main import app

class TestApiEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_full_governance_and_security_flow(self):
        # 1. Create isolated session
        r = self.client.post("/api/session", json={"scenario": "expired"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        sid = data["session_id"]
        content = data["content"]

        # 2. Run review: must catch both CP-2.1-2025 (expired) and VG-01 (superlative)
        rev = self.client.post("/api/review", json={"session_id": sid, "content": content}).json()
        rule_ids = [f["rule_id"] for f in rev["grounded"]]
        self.assertIn("CP-2.1-2025", rule_ids)
        self.assertIn("VG-01", rule_ids)

        # 3. Content binding check: tampering with text before approval must return 409
        bad = self.client.post("/api/action", json={
            "session_id": sid, "action": "send_for_approval", "role": "CREATOR", "content": content + " modified"
        })
        self.assertEqual(bad.status_code, 409)

        # 4. Valid send_for_approval and Manager approval
        s1 = self.client.post("/api/action", json={
            "session_id": sid, "action": "send_for_approval", "role": "CREATOR", "content": content
        })
        self.assertEqual(s1.status_code, 200)
        self.assertEqual(s1.json()["state"], "PENDING_MANAGER")

        s2 = self.client.post("/api/action", json={
            "session_id": sid, "action": "approve", "role": "MANAGER", "content": content
        })
        self.assertEqual(s2.status_code, 200)
        self.assertEqual(s2.json()["state"], "APPROVED")

        # 5. Re-running review after APPROVED must NOT return 500
        rev2 = self.client.post("/api/review", json={"session_id": sid, "content": content})
        self.assertEqual(rev2.status_code, 200)
        self.assertEqual(rev2.json()["state"], "REVIEWED")

        # 6. Audit verify & sandbox tamper check
        aud = self.client.get(f"/api/audit?session_id={sid}").json()
        self.assertTrue(aud["verification"]["valid"])
        tamp = self.client.post(f"/api/audit/simulate-tamper?session_id={sid}").json()
        self.assertFalse(tamp["after"]["valid"])

    def test_health_is_public_and_returns_status_only(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_cors_preflight_allows_api_headers_and_methods(self):
        response = self.client.options(
            "/api/session",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type,idempotency-key",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            response.headers["access-control-allow-origin"],
            {"*", "http://localhost:3000"},
        )
        self.assertIn("POST", response.headers["access-control-allow-methods"])
        allowed_headers = response.headers["access-control-allow-headers"].lower()
        for header in ("authorization", "content-type", "idempotency-key"):
            self.assertIn(header, allowed_headers)

    def test_cors_preflight_allows_loopback_alias(self):
        response = self.client.options(
            "/api/session",
            headers={
                "Origin": "http://127.0.0.1:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            response.headers["access-control-allow-origin"],
            {"*", "http://127.0.0.1:3000"},
        )

    def test_financial_session_restores_and_enforces_separation_of_duties(self):
        created = self.client.post("/api/session", json={"scenario": "financial"})
        self.assertEqual(created.status_code, 200)
        sid = created.json()["session_id"]
        content = created.json()["content"]
        self.assertIn("guaranteed 18% annual return", content)

        review = self.client.post("/api/review", json={"session_id": sid, "content": content})
        self.assertEqual(review.status_code, 200)
        self.assertEqual(review.json()["risk_class"], "HIGH")
        self.assertTrue(review.json()["grounded"])
        sent = self.client.post("/api/action", json={
            "session_id": sid, "action": "send_for_approval", "role": "CREATOR", "content": content,
        })
        self.assertEqual(sent.json()["state"], "PENDING_DUAL")

        sam_marketing = self.client.post("/api/login", json={
            "username": "sam.dual", "password": "demo-sam", "role": "MARKETING_HEAD",
        }).json()["token"]
        first = self.client.post("/api/action", headers={"Authorization": f"Bearer {sam_marketing}"}, json={
            "session_id": sid, "action": "approve", "role": "MARKETING_HEAD", "content": content,
        })
        self.assertEqual(first.status_code, 200)

        sam_legal = self.client.post("/api/login", json={
            "username": "sam.dual", "password": "demo-sam", "role": "LEGAL_COUNSEL",
        }).json()["token"]
        blocked = self.client.post("/api/action", headers={"Authorization": f"Bearer {sam_legal}"}, json={
            "session_id": sid, "action": "approve", "role": "LEGAL_COUNSEL", "content": content,
        })
        self.assertEqual(blocked.status_code, 403)
        self.assertIn("One person cannot fill both slots", blocked.json()["message"])

        changed = self.client.patch(f"/api/session/{sid}", json={"content": content + " "})
        self.assertIn("Previous sign-offs invalidated", changed.json()["invalidation_message"])
        reviewed = self.client.post("/api/review", json={
            "session_id": sid, "content": content + " ",
        })
        self.assertEqual(reviewed.status_code, 200)
        resent = self.client.post("/api/action", json={
            "session_id": sid, "action": "send_for_approval", "role": "CREATOR", "content": content + " ",
        })
        self.assertEqual(resent.json()["state"], "PENDING_DUAL")

        for username, password, role in (
            ("marcus.marketing", "demo-marcus", "MARKETING_HEAD"),
            ("priya.legal", "demo-priya", "LEGAL_COUNSEL"),
        ):
            token = self.client.post("/api/login", json={
                "username": username, "password": password, "role": role,
            }).json()["token"]
            approved = self.client.post("/api/action", headers={"Authorization": f"Bearer {token}"}, json={
                "session_id": sid, "action": "approve", "role": role, "content": content + " ",
            })
            self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["state"], "APPROVED")

        restored = self.client.get(f"/api/session/{sid}").json()
        self.assertEqual(restored["content"], content + " ")
        self.assertEqual(restored["state"], "APPROVED")
        self.assertEqual(len(restored["approvals"]), 2)
        self.assertTrue(restored["ledger"])

        restored_after = self.client.patch(f"/api/session/{sid}", json={"content": content + "  "}).json()
        self.assertEqual(restored_after["state"], "WORKSPACE_LOADED")
        self.assertEqual(restored_after["approvals"], [])
        self.assertEqual(restored_after["invalidation_message"], "Previous sign-offs invalidated due to content mutation")

    def test_signed_pack_verification_detects_tampered_pdf_hash(self):
        sid = self.client.post("/api/session", json={"scenario": "expired"}).json()["session_id"]
        login = self.client.post("/api/login", json={
            "username": "maya.creator", "password": "demo-maya",
        }).json()
        response = self.client.get(
            f"/api/audit/report?session_id={sid}",
            headers={"Authorization": f"Bearer {login['token']}"},
        )
        self.assertEqual(response.status_code, 200)
        verified = self.client.post("/api/audit/verify-pack", files={
            "file": ("report.zip", response.content, "application/zip"),
        })
        self.assertTrue(verified.json()["valid"])
        self.assertEqual(len(verified.json()["checks"]), 4)

        source = zipfile.ZipFile(io.BytesIO(response.content))
        tampered = io.BytesIO()
        with zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in source.namelist():
                contents = source.read(name)
                if name == "compliance-report.pdf":
                    contents += b"tampered"
                archive.writestr(name, contents)
        failed = self.client.post("/api/audit/verify-pack", files={
            "file": ("tampered.zip", tampered.getvalue(), "application/zip"),
        })
        self.assertFalse(failed.json()["valid"])
        pdf_check = next(check for check in failed.json()["checks"] if check["name"].startswith("PDF bytes"))
        self.assertFalse(pdf_check["passed"])

    def test_marketing_persona_can_approve_standard_risk(self):
        created = self.client.post("/api/session", json={"scenario": "expired"}).json()
        sid = created["session_id"]
        content = created["content"]
        self.client.post("/api/review", json={"session_id": sid, "content": content})
        submitted = self.client.post("/api/action", json={
            "session_id": sid, "action": "send_for_approval", "role": "CREATOR", "content": content,
        })
        self.assertEqual(submitted.json()["state"], "PENDING_MANAGER")
        token = self.client.post("/api/login", json={
            "username": "marcus.marketing", "password": "demo-marcus", "role": "MARKETING_HEAD",
        }).json()["token"]
        approved = self.client.post("/api/action", headers={"Authorization": f"Bearer {token}"}, json={
            "session_id": sid, "action": "approve", "role": "MARKETING_HEAD", "content": content,
        })
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["state"], "APPROVED")

if __name__ == "__main__":
    unittest.main()
