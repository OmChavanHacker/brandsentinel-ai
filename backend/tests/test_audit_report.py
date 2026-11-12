import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.core.evidence import canonical
from app.main import app


class TestSignedAuditReport(unittest.TestCase):
    def test_signed_report_contains_verifiable_pdf_and_manifest(self):
        seed = b"report-signing-test-seed-0000000"
        self.assertEqual(len(seed), 32)
        private = Ed25519PrivateKey.from_private_bytes(seed)
        entries = [{
            "sequence": 1,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "event_type": "WORKSPACE_LOADED",
            "actor": "SYSTEM",
            "payload": {"scenario": "expired"},
            "previous_hash": "0" * 64,
            "hash": "1" * 64,
        }]
        verification = {
            "valid": True,
            "checked_entries": 1,
            "head_hash": "1" * 64,
            "statuses": ["ok"],
        }

        with patch.dict(os.environ, {"REPORT_SIGNING_KEY_B64": base64.b64encode(seed).decode()}):
            from app.core.audit_report import create_signed_audit_report

            package_bytes = create_signed_audit_report("test-session", entries, verification)

        with zipfile.ZipFile(io.BytesIO(package_bytes)) as package:
            pdf_bytes = package.read("compliance-report.pdf")
            manifest_bytes = package.read("manifest.json")
            signature = json.loads(package.read("signature.json"))

        manifest = json.loads(manifest_bytes)
        self.assertEqual(manifest["session_id"], "test-session")
        self.assertEqual(manifest["ledger"], entries)
        self.assertEqual(signature["pdf_sha256"], hashlib.sha256(pdf_bytes).hexdigest())
        self.assertEqual(
            signature["manifest_sha256"],
            hashlib.sha256(canonical(manifest)).hexdigest(),
        )

        signed_payload = {key: value for key, value in signature.items() if key != "signature"}
        private.public_key().verify(
            base64.b64decode(signature["signature"]),
            canonical(signed_payload),
        )
        attachments = PdfReader(io.BytesIO(pdf_bytes)).attachments
        self.assertEqual(attachments["manifest.json"][0], manifest_bytes)

        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = os.path.join(temp_dir, "report.pdf")
            signature_path = os.path.join(temp_dir, "report.sig.json")
            public_key_path = os.path.join(temp_dir, "report.pub.pem")
            with open(pdf_path, "wb") as file:
                file.write(pdf_bytes)
            with open(signature_path, "w", encoding="utf-8") as file:
                json.dump(signature, file)
            with open(public_key_path, "wb") as file:
                file.write(private.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))

            result = subprocess.run(
                [
                    sys.executable,
                    os.path.join(os.path.dirname(__file__), "..", "verify_report.py"),
                    pdf_path,
                    signature_path,
                    "--pubkey",
                    public_key_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "PASS  Signature is valid for the published key",
                "PASS  PDF bytes match the signed hash",
                "PASS  Embedded manifest matches the signed hash",
                "PASS  Ledger blocks are correctly linked",
            ],
        )

    def test_report_endpoint_requires_auth_and_returns_signed_package(self):
        client = TestClient(app)
        session_response = client.post("/api/session", json={"scenario": "expired"})
        session_id = session_response.json()["session_id"]

        unauthorized = client.get(f"/api/audit/report?session_id={session_id}")
        self.assertEqual(unauthorized.status_code, 401)

        login = client.post(
            "/api/login",
            json={"username": "maya.creator", "password": "demo-maya"},
        )
        token = login.json()["token"]
        response = client.get(
            f"/api/audit/report?session_id={session_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(response.content)) as package:
            self.assertEqual(
                set(package.namelist()),
                {"compliance-report.pdf", "manifest.json", "signature.json"},
            )
            manifest = json.loads(package.read("manifest.json"))
            signature = json.loads(package.read("signature.json"))
        self.assertEqual(manifest["session_id"], session_id)
        self.assertTrue(manifest["verification"]["valid"])
        self.assertEqual(signature["alg"], "Ed25519")


if __name__ == "__main__":
    unittest.main()
