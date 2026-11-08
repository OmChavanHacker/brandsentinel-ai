import logging, os
from typing import Literal
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from app.core.rag_engine import RagEngine
from app.core.sessions import SessionStore, sha256_text
from app.core.workflow import WorkflowTransitionError

log = logging.getLogger("brandsentinel")
app = FastAPI(title="BrandSentinel AI")

ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

engine = RagEngine()
store = SessionStore()

@app.on_event("startup")
def startup_warm() -> None:
    engine.warm()

class SessionRequest(BaseModel):
    scenario: Literal["expired", "superlative", "unverified"] = "expired"

class ReviewRequest(BaseModel):
    session_id: str
    content: str = Field(min_length=1, max_length=20000)

class ActionRequest(BaseModel):
    session_id: str
    action: Literal["send_for_approval", "approve"]
    role: Literal["CREATOR", "MANAGER", "LEGAL"]
    content: str = Field(min_length=1, max_length=20000)

@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "retrieval_mode": engine.retrieval_mode}

@app.post("/api/session")
def create_session(req: SessionRequest) -> dict:
    _, _, payload = store.create(req.scenario)
    return payload

@app.get("/api/session/demo")
def demo_session(scenario: Literal["expired", "superlative", "unverified"] = "expired") -> dict:
    _, _, payload = store.create(scenario)
    return payload

@app.post("/api/review")
def review(req: ReviewRequest) -> dict:
    s = store.get(req.session_id)
    with s.lock:
        result = engine.review(req.content)
        state = s.workflow.transition("review", "CREATOR")
        s.reviewed_hash = sha256_text(req.content)
        s.needs_legal = bool(result["human_review"])
        e = s.ledger.append("CONTENT_REVIEWED", "CREATOR", {
            "content_sha256": s.reviewed_hash,
            "needs_legal": s.needs_legal,
            "rule_ids": [f["rule_id"] for f in result["grounded"]],
            "finding_counts": {k: len(result[k]) for k in ("grounded", "human_review", "suppressed")},
        })
    return {**result, "state": state.value, "audit_head": e["hash"], "needs_legal": s.needs_legal}

@app.post("/api/action")
def action(req: ActionRequest) -> dict:
    s = store.get(req.session_id)
    with s.lock:
        if sha256_text(req.content) != s.reviewed_hash:
            raise WorkflowTransitionError("The draft changed after review. Run the governance check again.", "CONTENT_CHANGED")
        state = s.workflow.transition(req.action, req.role, s.needs_legal)
        e = s.ledger.append("WORKFLOW_ACTION", req.role, {"action": req.action, "state": state.value, "content_sha256": s.reviewed_hash})
    return {"success": True, "state": state.value, "audit_head": e["hash"]}

@app.get("/api/audit")
def audit(session_id: str) -> dict:
    s = store.get(session_id)
    return {"entries": s.ledger.entries(), "verification": s.ledger.verify()}

@app.get("/api/audit/verify")
def verify_audit(session_id: str) -> dict:
    return store.get(session_id).ledger.verify()

@app.post("/api/audit/simulate-tamper")
def simulate_tamper(session_id: str) -> dict:
    return store.get(session_id).ledger.simulate_tamper()

STATUS = {"ROLE_NOT_AUTHORIZED": 403, "INVALID_TRANSITION": 409, "CONTENT_CHANGED": 409, "SESSION_NOT_FOUND": 404}

@app.exception_handler(WorkflowTransitionError)
async def workflow_error(_, exc: WorkflowTransitionError):
    return JSONResponse(status_code=STATUS.get(exc.code, 409), content={"success": False, "code": exc.code, "message": exc.message})

@app.exception_handler(Exception)
async def unexpected(_, exc: Exception):
    log.exception("unhandled error")
    return JSONResponse(status_code=500, content={"success": False, "code": "INTERNAL", "message": "Something went wrong. Your draft is unchanged. Please retry."})
