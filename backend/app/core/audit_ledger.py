import hmac, os, threading, hashlib, json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

LEDGER_KEY = os.environ.get("LEDGER_HMAC_KEY", "dev-only-change-me").encode()
GENESIS_HASH = "0" * 64

def canonical_json(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))

class AuditLedger:
    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    @staticmethod
    def _digest(unsigned: dict[str, Any]) -> str:
        return hmac.new(LEDGER_KEY, canonical_json(unsigned).encode("utf-8"), hashlib.sha256).hexdigest()

    def append(self, event_type: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            prev = self._entries[-1]["hash"] if self._entries else GENESIS_HASH
            entry = {
                "sequence": len(self._entries) + 1,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": event_type,
                "actor": actor,
                "payload": payload,
                "previous_hash": prev,
            }
            entry["hash"] = self._digest(entry)
            self._entries.append(entry)
            return deepcopy(entry)

    def entries(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self._entries)

    def verify(self, entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        chain = self.entries() if entries is None else entries
        statuses = ["unverifiable"] * len(chain)
        expected_prev = GENESIS_HASH
        for i, item in enumerate(chain):
            unsigned = {k: v for k, v in item.items() if k != "hash"}
            failure = None
            if item.get("sequence") != i + 1:
                failure = "sequence mismatch"
            elif item.get("previous_hash") != expected_prev:
                failure = "previous hash mismatch"
            elif not hmac.compare_digest(str(item.get("hash")), self._digest(unsigned)):
                failure = "content hash mismatch"
            if failure:
                statuses[i] = "broken"
                return {"valid": False, "failure": failure, "sequence": i + 1, "checked_entries": len(chain), "statuses": statuses}
            statuses[i] = "ok"
            expected_prev = item["hash"]
        return {"valid": True, "checked_entries": len(chain), "head_hash": expected_prev, "statuses": statuses}

    def simulate_tamper(self) -> dict[str, Any]:
        sandbox = self.entries()
        before = self.verify(self.entries())
        if not sandbox:
            return {"before": before, "after": before, "diff": None, "entries": []}
        target = sandbox[len(sandbox) // 2]
        original = deepcopy(target["payload"])
        target["payload"] = {**target["payload"], "tampered": True}
        return {
            "before": before,
            "after": self.verify(sandbox),
            "entries": sandbox,
            "diff": {"sequence": target["sequence"], "field": "payload", "before": original, "after": target["payload"]},
        }
