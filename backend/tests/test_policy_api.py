import json
import unittest

from fastapi.testclient import TestClient

from app.main import app


class TestPolicyApi(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_only_brand_lead_can_stage_and_activate_policy(self):
        other = self.client.post(
            "/api/login",
            json={"username": "maya.creator", "password": "demo-maya"},
        ).json()
        upload = self.client.post(
            "/api/policies/stage",
            headers={"Authorization": f"Bearer {other['token']}"},
            files={"file": ("rules.json", b"[]", "application/json")},
        )
        self.assertEqual(upload.status_code, 403)

        brand = self.client.post(
            "/api/login",
            json={"username": "rahul.brand", "password": "demo-rahul"},
        ).json()
        raw = json.dumps([{
            "rule_id": "API-1",
            "section": "Claims",
            "passage": "Avoid saying amazing.",
            "kind": "violation",
            "terms": ["amazing"],
        }]).encode()
        staged = self.client.post(
            "/api/policies/stage",
            headers={"Authorization": f"Bearer {brand['token']}"},
            files={"file": ("rules.json", raw, "application/json")},
            data={"version_tag": "api-test"},
        )
        self.assertEqual(staged.status_code, 202)
        job = self.client.get(
            f"/api/policies/jobs/{staged.json()['job_id']}",
            headers={"Authorization": f"Bearer {brand['token']}"},
        )
        self.assertEqual(job.status_code, 200)
        self.assertEqual(job.json()["status"], "staged")

        legal = self.client.post(
            "/api/login",
            json={"username": "priya.legal", "password": "demo-priya"},
        ).json()
        signoff = self.client.post(
            "/api/policies/api-test/signoff",
            headers={"Authorization": f"Bearer {legal['token']}"},
        )
        self.assertEqual(signoff.status_code, 200)
        self.assertEqual(signoff.json()["signoffs"], ["priya.legal"])

        activated = self.client.post(
            "/api/policies/api-test/activate",
            headers={"Authorization": f"Bearer {brand['token']}"},
        )
        self.assertEqual(activated.status_code, 200)
        self.assertEqual(activated.json()["version"], "api-test")

    def test_policy_staging_requires_authentication(self):
        response = self.client.post(
            "/api/policies/stage",
            files={"file": ("rules.csv", b"rule_id\n", "text/csv")},
        )
        self.assertEqual(response.status_code, 401)

    def test_invalid_policy_file_returns_422_with_line_number(self):
        brand = self.client.post(
            "/api/login",
            json={"username": "rahul.brand", "password": "demo-rahul"},
        ).json()
        response = self.client.post(
            "/api/policies/stage",
            headers={"Authorization": f"Bearer {brand['token']}"},
            files={
                "file": (
                    "sample_rulebook_bad.csv",
                    b"rule_id,section,passage,kind,terms\nBAD-1,Claims,Missing terms,violation,\n",
                    "text/csv",
                )
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("Line 2", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
