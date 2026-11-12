import hashlib
import logging
import os
import re
import threading
import uuid
from typing import Literal
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from app.core.auth import current_user, login, require_brand_lead
from app.core.audit_report import create_signed_audit_report
from app.core.evidence import verify_pack
from app.core.policy_ingestion import MAX_POLICY_BYTES, PolicyValidationError, parse_policy_file
from app.core.rag_engine import RagEngine
from app.core.sessions import SCENARIOS, SessionStore, sha256_text
from app.core.workflow import WorkflowState, WorkflowTransitionError

log = logging.getLogger("brandsentinel")
app = FastAPI(title="BrandSentinel AI")

ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]
configured_origins = os.environ.get("ALLOWED_ORIGINS")
if configured_origins is None:
    ORIGINS.append("*")
else:
    ORIGINS.extend(origin.strip() for origin in configured_origins.split(",") if origin.strip())
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys(ORIGINS)),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = RagEngine()
store = SessionStore()
policy_jobs: dict[str, dict] = {}
policy_jobs_lock = threading.Lock()
policy_signoffs: dict[str, list[str]] = {}

@app.on_event("startup")
def startup_warm() -> None:
    engine.warm()

class SessionRequest(BaseModel):
    scenario: Literal["expired", "superlative", "unverified", "financial"] = "expired"

class DraftUpdate(BaseModel):
    content: str = Field(max_length=20000)

class ReviewRequest(BaseModel):
    session_id: str
    content: str = Field(min_length=1, max_length=20000)

class ActionRequest(BaseModel):
    session_id: str
    action: Literal["send_for_approval", "approve"]
    role: Literal["CREATOR", "MANAGER", "LEGAL", "MARKETING_HEAD", "LEGAL_COUNSEL", "BRAND_LEAD"]
    content: str = Field(min_length=1, max_length=20000)

class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)
    role: str | None = None

def _stage_policy_job(job_id: str, filename: str, raw: bytes, raw_sha: str, version: str) -> None:
    with policy_jobs_lock:
        policy_jobs[job_id]["status"] = "processing"
    try:
        rules = parse_policy_file(filename, raw)
        snapshot = engine.stage_policy(rules, raw_sha, version)
        with policy_jobs_lock:
            policy_jobs[job_id].update({
                "status": "staged",
                "version": snapshot.version,
                "rule_count": len(snapshot.rules),
            })
    except (PolicyValidationError, ValueError) as exc:
        with policy_jobs_lock:
            policy_jobs[job_id].update({"status": "failed", "error": str(exc)})
    except Exception as exc:
        log.exception("Policy staging failed for job %s", job_id)
        with policy_jobs_lock:
            policy_jobs[job_id].update({"status": "failed", "error": f"Policy staging failed: {exc}"})

@app.post("/api/login")
def api_login(req: LoginRequest) -> dict:
    return login(req.username, req.password, req.role)

@app.post("/api/policies/stage", status_code=202)
async def stage_policy(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    version_tag: str = Form(default=""),
    user: dict = Depends(current_user),
) -> dict:
    require_brand_lead(user)
    filename = file.filename or ""
    raw = await file.read(MAX_POLICY_BYTES + 1)
    await file.close()
    if len(raw) > MAX_POLICY_BYTES:
        raise HTTPException(status_code=413, detail="Policy file exceeds the 2 MB limit.")
    suffix = os.path.splitext(filename)[1].lower()
    if suffix not in {".csv", ".json", ".md", ".markdown"}:
        raise HTTPException(status_code=415, detail="Supported file types are CSV, JSON, and Markdown.")
    raw_sha = hashlib.sha256(raw).hexdigest()
    version = version_tag.strip() or raw_sha[:16]
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", version):
        raise HTTPException(status_code=422, detail="Version tag may contain only letters, numbers, '.', '_' and '-'.")
    try:
        rules = parse_policy_file(filename, raw)
    except PolicyValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    job_id = uuid.uuid4().hex
    with policy_jobs_lock:
        policy_jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "version": version,
            "sha256": raw_sha,
            "impact": {
                "before": {
                    "version": engine.active_policy().version,
                    "rule_count": len(engine.active_policy().rules),
                },
                "after": {"version": version, "rule_count": len(rules)},
                "added_rule_ids": sorted(
                    {rule.rule_id for rule in rules}
                    - {rule.rule_id for rule in engine.active_policy().rules}
                ),
                "removed_rule_ids": sorted(
                    {rule.rule_id for rule in engine.active_policy().rules}
                    - {rule.rule_id for rule in rules}
                ),
            },
        }
    background_tasks.add_task(_stage_policy_job, job_id, filename, raw, raw_sha, version)
    return {"job_id": job_id, "status": "queued", "version": version, "sha256": raw_sha}

@app.get("/api/policies/jobs/{job_id}")
def get_policy_job(job_id: str, _user: dict = Depends(current_user)) -> dict:
    with policy_jobs_lock:
        job = policy_jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Policy staging job not found.")
        return dict(job)

@app.get("/api/policies")
def get_policies(_user: dict = Depends(current_user)) -> dict:
    active = engine.active_policy()
    staged = engine.staged_policies()
    return {
        "active": {
            "version": active.version,
            "sha256": active.sha256,
            "created_at": active.created_at,
            "rule_count": len(active.rules),
        },
        "staged": [
            {"version": snapshot.version, "sha256": snapshot.sha256, "rule_count": len(snapshot.rules)}
            for snapshot in staged
        ],
        "history": engine.policy_history(),
    }

@app.post("/api/policies/{version}/activate")
def activate_policy(version: str, user: dict = Depends(current_user)) -> dict:
    require_brand_lead(user)
    try:
        snapshot = engine.activate_policy(version, user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "success": True,
        "version": snapshot.version,
        "sha256": snapshot.sha256,
        "rule_count": len(snapshot.rules),
    }

@app.post("/api/policies/{version}/signoff")
def signoff_policy(version: str, user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "LEGAL_COUNSEL":
        raise HTTPException(status_code=403, detail="LEGAL_COUNSEL role required.")
    if version not in {snapshot.version for snapshot in engine.staged_policies()}:
        raise HTTPException(status_code=404, detail="Staged policy version not found.")
    with policy_jobs_lock:
        signers = policy_signoffs.setdefault(version, [])
        if user["id"] not in signers:
            signers.append(user["id"])
        return {"version": version, "signoffs": list(signers)}

@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}

@app.post("/api/session")
def create_session(req: SessionRequest) -> dict:
    _, _, payload = store.create(req.scenario)
    return payload

@app.get("/api/session/demo")
def demo_session(scenario: Literal["expired", "superlative", "unverified", "financial"] = "expired") -> dict:
    _, _, payload = store.create(scenario)
    return payload

def _session_payload(session_id: str, session) -> dict:
    return {
        "id": session_id,
        "session_id": session_id,
        "content": session.content,
        "state": session.workflow.state.value,
        "version": session.version,
        "risk_class": session.risk_class,
        "findings": session.findings,
        "approvals": session.approvals,
        "ledger": session.ledger.entries(),
        "audit_head": session.ledger.entries()[-1]["hash"] if session.ledger.entries() else "",
        "policy_version": session.policy_version,
        "scenario": session.scenario,
        "review": session.review_result,
        "invalidation_message": session.invalidation_message,
    }

@app.get("/api/session/{session_id}")
def get_session(session_id: str) -> dict:
    session = store.get(session_id)
    with session.lock:
        return _session_payload(session_id, session)

@app.patch("/api/session/{session_id}")
def update_session(session_id: str, draft: DraftUpdate, authorization: str = Header(default="")) -> dict:
    session = store.get(session_id)
    actor = current_user(authorization)["id"] if authorization else "CREATOR"
    with session.lock:
        changed = draft.content != session.content
        if changed:
            had_approvals = bool(session.approvals)
            session.content = draft.content
            session.version += 1
            session.approvals.clear()
            session.reviewed_hash = None
            session.findings = {"grounded": [], "human_review": [], "suppressed": []}
            session.review_result = None
            session.workflow.state = WorkflowState.WORKSPACE_LOADED
            session.invalidation_message = (
                "Previous sign-offs invalidated due to content mutation" if had_approvals else None
            )
            session.ledger.append("CONTENT_MUTATED", actor, {
                "version": session.version,
                "content_sha256": sha256_text(draft.content),
                "signoffs_invalidated": had_approvals,
            })
        return _session_payload(session_id, session)

@app.post("/api/review")
def review(req: ReviewRequest) -> dict:
    s = store.get(req.session_id)
    with s.lock:
        if req.content != s.content:
            had_approvals = bool(s.approvals)
            s.content = req.content
            s.version += 1
            s.approvals.clear()
            s.invalidation_message = (
                "Previous sign-offs invalidated due to content mutation" if had_approvals else None
            )
        result = engine.review(req.content)
        state = s.workflow.transition("review", "CREATOR")
        s.reviewed_hash = sha256_text(req.content)
        s.risk_class = "HIGH" if s.scenario == "financial" or any(
            phrase in req.content.lower()
            for phrase in ("guaranteed", "zero risk", "risk-free", "18% annual return")
        ) else "STANDARD"
        s.needs_legal = bool(result["human_review"]) or s.risk_class == "HIGH"
        s.findings = {
            "grounded": result["grounded"],
            "human_review": result["human_review"],
            "suppressed": result["suppressed"],
        }
        s.review_result = result
        s.policy_version = result["trace"]["policy_version"]
        e = s.ledger.append("CONTENT_REVIEWED", "CREATOR", {
            "content_sha256": s.reviewed_hash,
            "needs_legal": s.needs_legal,
            "policy_version": result["trace"]["policy_version"],
            "policy_sha256": result["trace"]["policy_sha256"],
            "rule_ids": [f["rule_id"] for f in result["grounded"]],
            "finding_counts": {k: len(result[k]) for k in ("grounded", "human_review", "suppressed")},
        })
    return {**result, "state": state.value, "audit_head": e["hash"], "needs_legal": s.needs_legal,
            "risk_class": s.risk_class, "version": s.version, "approvals": s.approvals,
            "policy_version": s.policy_version, "invalidation_message": s.invalidation_message}

@app.post("/api/action")
def action(req: ActionRequest, authorization: str = Header(default="")) -> dict:
    s = store.get(req.session_id)
    user = current_user(authorization) if authorization else {"id": f"legacy:{req.role}", "role": req.role}
    with s.lock:
        if sha256_text(req.content) != s.reviewed_hash:
            raise WorkflowTransitionError("The draft changed after review. Run the governance check again.", "CONTENT_CHANGED")
        role = user["role"]
        if req.action == "send_for_approval":
            if s.workflow.state.value != "REVIEWED":
                raise WorkflowTransitionError("Run governance check before sending for approval.", "INVALID_TRANSITION")
            s.workflow.state = (
                WorkflowState.PENDING_DUAL if s.needs_legal else WorkflowState.PENDING_MANAGER
            )
        elif req.action == "approve":
            if s.workflow.state.value == "PENDING_DUAL":
                if role not in ("MARKETING_HEAD", "LEGAL_COUNSEL"):
                    raise WorkflowTransitionError("MARKETING_HEAD or LEGAL_COUNSEL role required.", "ROLE_NOT_AUTHORIZED")
                if any(approval["role"] == role for approval in s.approvals):
                    raise WorkflowTransitionError(f"{role} sign-off is already recorded.", "INVALID_TRANSITION")
                if any(approval["actor"] == user["id"] for approval in s.approvals):
                    raise WorkflowTransitionError("One person cannot fill both slots.", "ROLE_NOT_AUTHORIZED")
                s.approvals.append({"actor": user["id"], "role": role})
                if {item["role"] for item in s.approvals} == {"MARKETING_HEAD", "LEGAL_COUNSEL"}:
                    s.workflow.state = WorkflowState.APPROVED
            else:
                legacy_role = {
                    "MANAGER": "MANAGER",
                    "LEGAL": "LEGAL",
                    "MARKETING_HEAD": "MANAGER",
                    "LEGAL_COUNSEL": "LEGAL",
                }.get(role, role)
                state = s.workflow.transition("approve", legacy_role, s.needs_legal)
                s.approvals.append({"actor": user["id"], "role": role})
        else:
            raise WorkflowTransitionError(f"Unknown action: {req.action}", "INVALID_TRANSITION")
        state = s.workflow.state
        e = s.ledger.append("WORKFLOW_ACTION", user["id"], {
            "action": req.action, "role": role, "state": state.value,
            "content_sha256": s.reviewed_hash, "approvals": [dict(item) for item in s.approvals],
        })
    return {**_session_payload(req.session_id, s), "success": True, "audit_head": e["hash"]}

@app.get("/api/audit")
def audit(session_id: str) -> dict:
    s = store.get(session_id)
    return {"entries": s.ledger.entries(), "verification": s.ledger.verify()}

@app.get("/api/audit/verify")
def verify_audit(session_id: str) -> dict:
    return store.get(session_id).ledger.verify()

@app.get("/api/audit/report")
def signed_audit_report(session_id: str, _user: dict = Depends(current_user)) -> Response:
    session = store.get(session_id)
    entries = session.ledger.entries()
    verification = session.ledger.verify(entries)
    report = create_signed_audit_report(session_id, entries, verification)
    return Response(
        content=report,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="brandsentinel-audit-{session_id}.zip"',
        },
    )

@app.post("/api/audit/verify-pack")
async def verify_audit_pack(file: UploadFile = File(...)) -> dict:
    package_bytes = await file.read(20 * 1024 * 1024 + 1)
    await file.close()
    if len(package_bytes) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audit pack exceeds the 20 MB limit.")
    try:
        return verify_pack(package_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

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
