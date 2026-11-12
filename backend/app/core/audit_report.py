from __future__ import annotations

import html
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from app.core.evidence import canonical, embed_manifest, private_key, sign_pack


def _render_pdf(manifest: dict[str, Any]) -> bytes:
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=letter,
        rightMargin=42,
        leftMargin=42,
        topMargin=42,
        bottomMargin=42,
        title="BrandSentinel AI Compliance Audit Report",
        author="BrandSentinel AI",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "AuditTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        fontSize=18,
        leading=22,
        spaceAfter=16,
    )
    payload_style = ParagraphStyle(
        "AuditPayload",
        parent=styles["BodyText"],
        fontName="Courier",
        fontSize=7,
        leading=9,
        wordWrap="CJK",
    )
    hash_style = ParagraphStyle(
        "AuditHash",
        parent=payload_style,
        textColor=colors.HexColor("#444444"),
    )

    verification = manifest["verification"]
    status = "VALID" if verification["valid"] else "INVALID"
    story = [
        Paragraph("BrandSentinel AI Compliance Audit Report", title_style),
        Paragraph(f"<b>Session:</b> {html.escape(manifest['session_id'])}", styles["BodyText"]),
        Paragraph(f"<b>Issued:</b> {html.escape(manifest['generated_at'])}", styles["BodyText"]),
        Paragraph(f"<b>Ledger verification:</b> {status}", styles["BodyText"]),
        Paragraph(
            f"<b>Entries checked:</b> {verification['checked_entries']}",
            styles["BodyText"],
        ),
    ]
    if verification.get("head_hash"):
        story.append(Paragraph(
            f"<b>Ledger head:</b> {html.escape(verification['head_hash'])}",
            hash_style,
        ))
    if verification.get("failure"):
        story.append(Paragraph(
            f"<b>Verification failure:</b> {html.escape(verification['failure'])}",
            styles["BodyText"],
        ))
    story.append(Spacer(1, 16))

    entries = manifest["ledger"]
    if not entries:
        story.append(Paragraph("No audit entries were recorded.", styles["BodyText"]))
    for index, entry in enumerate(entries):
        story.append(Paragraph(
            f"Entry {entry['sequence']}: {html.escape(str(entry['event_type']))}",
            styles["Heading2"],
        ))
        story.append(Paragraph(
            f"<b>Timestamp:</b> {html.escape(str(entry['timestamp']))}<br/>"
            f"<b>Actor:</b> {html.escape(str(entry['actor']))}",
            styles["BodyText"],
        ))
        payload = html.escape(json.dumps(entry["payload"], sort_keys=True, ensure_ascii=False))
        story.append(Paragraph(f"<b>Payload:</b> {payload}", payload_style))
        story.append(Paragraph(
            f"<b>Entry hash:</b> {html.escape(str(entry['hash']))}",
            hash_style,
        ))
        if index < len(entries) - 1:
            story.append(Spacer(1, 12))

    document.build(story)
    return output.getvalue()


def create_signed_audit_report(
    session_id: str,
    entries: list[dict[str, Any]],
    verification: dict[str, Any],
) -> bytes:
    manifest = {
        "schema": "brandsentinel.audit-report.v1",
        "session_id": session_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ledger": entries,
        "verification": verification,
    }
    manifest_bytes = canonical(manifest)
    pdf = embed_manifest(_render_pdf(manifest), manifest)
    signature = sign_pack(pdf, manifest, private_key())

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("compliance-report.pdf", pdf)
        package.writestr("manifest.json", manifest_bytes)
        package.writestr(
            "signature.json",
            json.dumps(signature, sort_keys=True, indent=2, ensure_ascii=False).encode("utf-8"),
        )
    return archive.getvalue()
