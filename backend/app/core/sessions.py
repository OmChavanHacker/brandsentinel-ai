import hashlib, threading, uuid
from app.core.audit_ledger import AuditLedger
from app.core.workflow import Workflow, WorkflowTransitionError

SCENARIOS = {
    "expired": "Our product uses 80% recycled packaging and is the best choice on the market.",
    "superlative": "Meet the Aurora Pay Wallet, the number one solution on the market! Guaranteed returns for all users.",
    "unverified": "Send money home with zero fees this summer. Customers reduce transfer costs by 40% using our sustainable packaging.",
}

def sha256_text(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

class Session:
    def __init__(self) -> None:
        self.workflow = Workflow()
        self.ledger = AuditLedger()
        self.reviewed_hash: str | None = None
        self.needs_legal: bool = False
        self.lock = threading.Lock()

class SessionStore:
    def __init__(self, max_sessions: int = 500) -> None:
        self._sessions: dict[str, Session] = {}
        self._max = max_sessions
        self._lock = threading.Lock()

    def create(self, scenario: str = "expired") -> tuple[str, Session, dict]:
        with self._lock:
            if len(self._sessions) >= self._max:
                self._sessions.pop(next(iter(self._sessions)))
            sid = uuid.uuid4().hex
            s = Session()
            self._sessions[sid] = s
        content = SCENARIOS.get(scenario, SCENARIOS["expired"])
        entry = s.ledger.append("WORKSPACE_LOADED", "SYSTEM", {"scenario": scenario})
        return sid, s, {"session_id": sid, "content": content, "state": s.workflow.state.value, "audit_head": entry["hash"]}

    def get(self, sid: str) -> Session:
        s = self._sessions.get(sid)
        if not s:
            raise WorkflowTransitionError("Session expired or not found. Reload the demo.", "SESSION_NOT_FOUND")
        return s

