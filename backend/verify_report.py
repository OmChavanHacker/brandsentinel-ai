#!/usr/bin/env python3
"""Usage: python verify_report.py report.pdf report.sig.json --pubkey backend/keys/report_signing.pub.pem"""
import argparse, base64, hashlib, json, sys
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from pypdf import PdfReader


def canonical(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("pdf")
    p.add_argument("sig")
    p.add_argument("--pubkey", required=True)
    a = p.parse_args()
    with open(a.sig, "r", encoding="utf-8") as sig_file:
        sig = json.load(sig_file)
    with open(a.pdf, "rb") as pdf_file:
        pdf = pdf_file.read()
    with open(a.pubkey, "rb") as pubkey_file:
        pub = load_pem_public_key(pubkey_file.read())

    checks = []
    payload = {k: v for k, v in sig.items() if k != "signature"}
    try:
        pub.verify(base64.b64decode(sig["signature"]), canonical(payload))
        ok = True
    except InvalidSignature:
        ok = False
    checks.append(("Signature is valid for the published key", ok))
    checks.append(("PDF bytes match the signed hash", hashlib.sha256(pdf).hexdigest() == sig["pdf_sha256"]))
    att = PdfReader(a.pdf).attachments.get("manifest.json")
    manifest = json.loads(att[0]) if att else None
    checks.append((
        "Embedded manifest matches the signed hash",
        bool(manifest) and hashlib.sha256(canonical(manifest)).hexdigest() == sig["manifest_sha256"],
    ))
    ledger = (manifest or {}).get("ledger", [])
    linked = all(
        entry["previous_hash"] == (ledger[index - 1]["hash"] if index else "0" * 64)
        for index, entry in enumerate(ledger)
    )
    checks.append(("Ledger blocks are correctly linked", bool(ledger) and linked))
    for name, ok in checks:
        print(("PASS  " if ok else "FAIL  ") + name)
    sys.exit(0 if all(ok for _, ok in checks) else 1)


if __name__ == "__main__":
    main()
