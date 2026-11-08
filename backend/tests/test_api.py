import unittest
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

if __name__ == "__main__":
    unittest.main()
