from __future__ import annotations

import csv
import io
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from app.core.rag_engine import PolicySource

MAX_POLICY_BYTES = 2 * 1024 * 1024
MAX_POLICY_RULES = 1000
ALLOWED_KINDS = {"violation", "expired_fact", "future_fact", "guidance"}

ALIASES = {
    "rule_id": ("rule_id", "id", "rule"),
    "section": ("section",),
    "passage": ("passage", "text", "policy", "content", "description"),
    "kind": ("kind", "type"),
    "terms": ("terms", "triggers", "keywords"),
    "expiry_date": ("expiry_date", "expires", "expires_at"),
    "effective_from": ("effective_from", "start_date"),
    "rewrite": ("rewrite", "suggested_rewrite"),
}


class PolicyValidationError(ValueError):
    pass


def parse_policy_file(filename: str, raw: bytes) -> list[PolicySource]:
    if len(raw) > MAX_POLICY_BYTES:
        raise PolicyValidationError("Policy file exceeds the 2 MB limit.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PolicyValidationError("Policy files must use UTF-8 encoding.") from exc

    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".json":
            records = _json_records(text)
        elif suffix == ".csv":
            records = _csv_records(text)
        elif suffix in {".md", ".markdown"}:
            records = _markdown_records(text)
        else:
            raise PolicyValidationError("Supported file types are CSV, JSON, and Markdown.")
        if not records:
            raise PolicyValidationError("The policy file contains no rules.")
        if len(records) > MAX_POLICY_RULES:
            raise PolicyValidationError(f"A policy file may contain at most {MAX_POLICY_RULES} rules.")
        return [_to_rule(record, index) for index, record in enumerate(records, start=1)]
    except (csv.Error, json.JSONDecodeError) as exc:
        raise PolicyValidationError(f"Could not parse policy file: {exc}") from exc


def _json_records(text: str) -> list[dict[str, Any]]:
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("rules")
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise PolicyValidationError("JSON must contain a list of rule objects (or an object with a 'rules' list).")
    return data


def _csv_records(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise PolicyValidationError("CSV must include a header row.")
    return [dict(row) for row in reader]


def _markdown_records(text: str) -> list[dict[str, Any]]:
    lines = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        raise PolicyValidationError("Markdown must contain a pipe-delimited table with a header.")

    def cells(line: str) -> list[str]:
        return [cell.strip() for cell in line.strip("|").split("|")]

    headers = cells(lines[0])
    data_lines = [
        line for line in lines[1:]
        if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells(line))
    ]
    return [dict(zip(headers, cells(line))) for line in data_lines]


def _to_rule(record: dict[str, Any], index: int) -> PolicySource:
    lowered = {str(key).strip().lower(): value for key, value in record.items()}

    def get(field: str) -> Any:
        return next((lowered[name] for name in ALIASES[field] if name in lowered), None)

    rule_id = _required_text(get("rule_id"), "rule_id", index)
    section = _required_text(get("section"), "section", index)
    passage = _required_text(get("passage"), "passage", index)
    kind = _required_text(get("kind"), "kind", index).lower()
    if kind not in ALLOWED_KINDS:
        raise PolicyValidationError(f"Rule {rule_id}: kind must be one of {', '.join(sorted(ALLOWED_KINDS))}.")
    terms_value = get("terms")
    if isinstance(terms_value, list):
        terms = tuple(dict.fromkeys(str(term).strip() for term in terms_value if str(term).strip()))
    elif isinstance(terms_value, str):
        terms = tuple(dict.fromkeys(part.strip() for part in re.split(r"[|;]", terms_value) if part.strip()))
    else:
        terms = ()
    if not terms:
        raise PolicyValidationError(f"Line {index + 1} (rule {rule_id}): at least one term is required.")
    if len(rule_id) > 128 or len(section) > 256 or len(passage) > 10000:
        raise PolicyValidationError(f"Rule {rule_id}: a field exceeds its maximum length.")

    expiry_date = _optional_date(get("expiry_date"), "expiry_date", rule_id)
    effective_from = _optional_date(get("effective_from"), "effective_from", rule_id)
    rewrite = _optional_text(record, ALIASES["rewrite"])
    return PolicySource(
        rule_id=rule_id,
        section=section,
        passage=passage,
        expiry_date=expiry_date,
        kind=kind,
        terms=terms,
        rewrite=rewrite,
        effective_from=effective_from,
    )


def _required_text(value: Any, field: str, index: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyValidationError(f"Rule {index}: {field} is required.")
    return value.strip()


def _optional_text(record: dict[str, Any], aliases: tuple[str, ...]) -> str | None:
    lowered = {str(key).strip().lower(): value for key, value in record.items()}
    value = next((lowered[name] for name in aliases if name in lowered), None)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_date(value: Any, field: str, rule_id: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        value = str(value)
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError as exc:
        raise PolicyValidationError(f"Rule {rule_id}: {field} must use YYYY-MM-DD.") from exc
