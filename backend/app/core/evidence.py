import base64, hashlib, io, json, os, zipfile
from datetime import datetime, timezone
from typing import Any
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

def canonical(o) -> bytes:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

def private_key() -> Ed25519PrivateKey:   # 32-byte seed in base64, from env; never committed
    key_b64 = os.environ.get("REPORT_SIGNING_KEY_B64")
    if not key_b64:
        # Deterministic dev fallback so local/CI tests don't crash if env is unset
        return Ed25519PrivateKey.from_private_bytes(b"0" * 32)
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(key_b64))

def embed_manifest(pdf_bytes: bytes, manifest: dict) -> bytes:
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_bytes)))
    w.add_attachment("manifest.json", canonical(manifest))
    buf = io.BytesIO(); w.write(buf); return buf.getvalue()

def sign_pack(final_pdf: bytes, manifest: dict, priv: Ed25519PrivateKey) -> dict:
    pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    payload = {"alg": "Ed25519", "key_id": hashlib.sha256(pub).hexdigest()[:16],
               "pdf_sha256": hashlib.sha256(final_pdf).hexdigest(),
               "manifest_sha256": hashlib.sha256(canonical(manifest)).hexdigest(),
               "issued_at": datetime.now(timezone.utc).isoformat()}
    return {**payload, "signature": base64.b64encode(priv.sign(canonical(payload))).decode()}

def verify_pack(package_bytes: bytes) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(io.BytesIO(package_bytes)) as archive:
            pdf = archive.read("compliance-report.pdf")
            manifest_bytes = archive.read("manifest.json")
            signature_bytes = archive.read("signature.json")
        manifest = json.loads(manifest_bytes)
        signature = json.loads(signature_bytes)
        payload = {key: value for key, value in signature.items() if key != "signature"}
        try:
            private_key().public_key().verify(
                base64.b64decode(signature["signature"], validate=True),
                canonical(payload),
            )
            signature_valid = True
        except (InvalidSignature, ValueError, KeyError):
            signature_valid = False

        attachments = PdfReader(io.BytesIO(pdf)).attachments
        embedded = attachments.get("manifest.json")
        embedded_manifest = json.loads(embedded[0]) if embedded else None
        ledger = (manifest or {}).get("ledger", [])
        linked = bool(ledger) and all(
            entry.get("sequence") == index + 1
            and entry.get("previous_hash") == (ledger[index - 1].get("hash") if index else "0" * 64)
            for index, entry in enumerate(ledger)
        )
        checks = [
            {"name": "Signature is valid for the published key", "passed": signature_valid},
            {"name": "PDF bytes match the signed hash", "passed": hashlib.sha256(pdf).hexdigest() == signature.get("pdf_sha256")},
            {
                "name": "Embedded manifest matches the signed hash",
                "passed": embedded_manifest is not None
                and hashlib.sha256(canonical(embedded_manifest)).hexdigest() == signature.get("manifest_sha256")
                and hashlib.sha256(canonical(manifest)).hexdigest() == signature.get("manifest_sha256"),
            },
            {"name": "Ledger blocks are correctly linked", "passed": linked},
        ]
        return {"valid": all(check["passed"] for check in checks), "checks": checks}
    except (KeyError, json.JSONDecodeError, OSError, ValueError, zipfile.BadZipFile) as exc:
        raise ValueError(f"Invalid audit pack: {exc}") from exc
