"use client";

import { useEffect, useState } from "react";
import {
  CheckCircle2,
  AlertTriangle,
  ShieldAlert,
  RefreshCw,
  Lock,
  History,
  ShieldCheck,
  Trash2
} from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const JSON_HEADERS = { "Content-Type": "application/json" };

type Finding = {
  rule_id: string;
  kind: string;
  section: string;
  expiry_date?: string | null;
  sentence: string;
  matched_term: string;
  reason: string;
  suggested_rewrite: string | null;
  advice: string;
};

type HumanItem = {
  sentence: string;
  reason: string;
  route_to: string;
  status: string;
  nearest_rule?: string;
  score?: number;
};

type Suppressed = {
  candidate: string;
  nearest_rule: string;
  score: number;
  reason_code: string;
  reason: string;
};

type ReviewResult = {
  grounded: Finding[];
  human_review: HumanItem[];
  suppressed: Suppressed[];
  state: string;
  audit_head: string;
  needs_legal: boolean;
  trace: {
    claim_isolation_ms: number;
    deterministic_ms: number;
    vector_rag_ms: number;
    total_ms: number;
    retrieval_mode: string;
    validator: string;
    claims_checked: number;
    suppressed_count: number;
  };
};

function ChainStrip({ entries, statuses }: { entries: any[]; statuses: string[] }) {
  const tone: Record<string, string> = {
    ok: "bg-emerald-950/90 text-emerald-300 border-emerald-700/60",
    broken: "bg-rose-900 text-white border-rose-500 font-bold",
    unverifiable: "bg-slate-800 text-slate-400 border-slate-700",
  };
  return (
    <ol aria-label="Audit chain" className="flex flex-wrap items-center gap-1.5 py-1">
      {entries.map((e, i) => {
        const st = statuses?.[i] ?? "unverifiable";
        return (
          <li key={e.sequence} className="flex items-center gap-1.5">
            <span className={`rounded border px-2 py-1 font-mono text-[11px] ${tone[st] ?? tone.unverifiable}`}>
              #{e.sequence} {e.hash?.slice(0, 6)}
              <span className="ml-1 opacity-75">({st})</span>
            </span>
            {i < entries.length - 1 && <span className="text-slate-500 font-mono">→</span>}
          </li>
        );
      })}
    </ol>
  );
}

export default function Home() {
  const [sessionId, setSessionId] = useState<string>("");
  const [content, setContent] = useState<string>("");
  const [role, setRole] = useState<"CREATOR" | "MANAGER" | "LEGAL">("CREATOR");
  const [scenario, setScenario] = useState<"expired" | "superlative" | "unverified">("expired");
  const [review, setReview] = useState<ReviewResult | null>(null);
  const [status, setStatus] = useState<string>("WORKSPACE_LOADED");
  const [auditHead, setAuditHead] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [busy, setBusy] = useState<boolean>(false);
  const [isStale, setIsStale] = useState<boolean>(false);
  const [pendingFix, setPendingFix] = useState<Finding | null>(null);
  const [showAuditModal, setShowAuditModal] = useState<boolean>(false);
  const [auditData, setAuditData] = useState<any>(null);

  const initSession = async (sc: "expired" | "superlative" | "unverified") => {
    setBusy(true);
    setError("");
    setPendingFix(null);
    try {
      const res = await fetch(`${API}/api/session`, {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({ scenario: sc }),
      });
      if (!res.ok) throw new Error("Backend server not responding. Make sure FastAPI is running on port 8000.");
      const data = await res.json();
      setSessionId(data.session_id);
      setContent(data.content);
      setStatus(data.state);
      setAuditHead(data.audit_head);
      setReview(null);
      setIsStale(false);
      setRole("CREATOR");
    } catch (e: any) {
      setError(e.message || "Failed to connect to backend server.");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    initSession("expired");
  }, []);

  const handleScenarioChange = (sc: "expired" | "superlative" | "unverified") => {
    setScenario(sc);
    initSession(sc);
  };

  const runCheck = async () => {
    if (!sessionId || !content.trim()) return;
    setBusy(true);
    setError("");
    setPendingFix(null);
    try {
      const res = await fetch(`${API}/api/review`, {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({ session_id: sessionId, content }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.message || "Review processing failed.");
      }
      const data: ReviewResult = await res.json();
      setReview(data);
      setStatus(data.state);
      setAuditHead(data.audit_head);
      setIsStale(false);
    } catch (e: any) {
      setError(e.message || "Error running review check. Is backend running?");
    } finally {
      setBusy(false);
    }
  };

  const handleAction = async (action: "send_for_approval" | "approve") => {
    if (!sessionId) return;
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`${API}/api/action`, {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({
          session_id: sessionId,
          action,
          role,
          content,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.message || "Action not allowed.");
      }
      const data = await res.json();
      setStatus(data.state);
      setAuditHead(data.audit_head);
      if (action === "send_for_approval") {
        setRole(review?.needs_legal ? "LEGAL" : "MANAGER");
      }
    } catch (e: any) {
      setError(e.message || "Action transition failed.");
    } finally {
      setBusy(false);
    }
  };

  const openAudit = async () => {
    if (!sessionId) return;
    setBusy(true);
    try {
      const res = await fetch(`${API}/api/audit?session_id=${sessionId}`);
      const data = await res.json();
      setAuditData(data);
      setShowAuditModal(true);
    } catch {
      setError("Failed to load audit trail from backend.");
    } finally {
      setBusy(false);
    }
  };

  const verifyChainNow = async () => {
    if (!sessionId) return;
    try {
      const res = await fetch(`${API}/api/audit/verify?session_id=${sessionId}`);
      const v = await res.json();
      setAuditData((prev: any) => ({ ...prev, verification: v }));
    } catch {
      setError("Verification call failed.");
    }
  };

  const triggerTamper = async () => {
    if (!sessionId) return;
    try {
      const res = await fetch(`${API}/api/audit/simulate-tamper?session_id=${sessionId}`, {
        method: "POST",
      });
      const data = await res.json();
      setAuditData((prev: any) => ({ ...prev, tamper: data }));
    } catch {
      setError("Tamper simulation failed.");
    }
  };

  const confirmFix = () => {
    if (!pendingFix || !pendingFix.suggested_rewrite) return;
    if (!content.includes(pendingFix.sentence)) {
      setError("That sentence changed in the editor. Re-run the check.");
      setPendingFix(null);
      return;
    }
    setContent(content.replace(pendingFix.sentence, () => pendingFix.suggested_rewrite!));
    setPendingFix(null);
    setIsStale(true);
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <header className="border-b border-slate-800 bg-slate-900/60 backdrop-blur-md px-6 py-4 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-lg bg-indigo-600 flex items-center justify-center font-bold text-white shadow-lg">
            BS
          </div>
          <div>
            <h1 className="text-lg font-semibold tracking-tight text-white flex items-center gap-2">
              BrandSentinel AI
              <span className="text-xs bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 px-2 py-0.5 rounded-full font-mono">
                Cite or Stay Silent
              </span>
            </h1>
            <p className="text-xs text-slate-400">Deterministic Hybrid Compliance Governance Engine</p>
          </div>
        </div>

        <div className="flex items-center gap-2 text-xs font-mono bg-slate-900 border border-slate-800 px-3 py-1.5 rounded-lg text-slate-300">
          <span>Det: <b className="text-indigo-400">{review?.trace ? `${review.trace.deterministic_ms}ms` : "—"}</b></span>
          <span className="text-slate-600">|</span>
          <span>RAG ({review?.trace?.retrieval_mode ?? "ready"}): <b className="text-indigo-400">{review?.trace ? `${review.trace.vector_rag_ms}ms` : "—"}</b></span>
          <span className="text-slate-600">|</span>
          <span>Total: <b className="text-emerald-400">{review?.trace ? `${review.trace.total_ms}ms` : "—"}</b></span>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex bg-slate-900 border border-slate-800 p-1 rounded-lg" role="group" aria-label="Role selector">
            {(["CREATOR", "MANAGER", "LEGAL"] as const).map((r) => (
              <button
                key={r}
                onClick={() => setRole(r)}
                className={`px-3 py-1 text-xs font-medium rounded-md transition-all ${
                  role === r ? "bg-indigo-600 text-white shadow" : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {r}
              </button>
            ))}
          </div>

          <button
            onClick={openAudit}
            className="flex items-center gap-1.5 text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 px-3 py-1.5 rounded-lg transition"
          >
            <History className="w-3.5 h-3.5" />
            Audit Ledger
          </button>
        </div>
      </header>

      {error && (
        <div className="bg-rose-950/90 border-b border-rose-800 px-6 py-3 text-rose-200 text-xs flex items-center justify-between shadow-lg">
          <span className="font-medium">⚠️ {error}</span>
          <button onClick={() => setError("")} aria-label="Dismiss error" className="hover:text-white font-bold px-2 py-1 bg-rose-900 rounded">✕</button>
        </div>
      )}

      <main className="flex-1 grid grid-cols-1 lg:grid-cols-12 gap-6 p-6">
        <section className="lg:col-span-7 flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <div className="flex gap-2">
              {(["expired", "superlative", "unverified"] as const).map((sc) => (
                <button
                  key={sc}
                  onClick={() => handleScenarioChange(sc)}
                  disabled={busy}
                  className={`text-xs px-3 py-1.5 rounded-lg border capitalize transition ${
                    scenario === sc
                      ? "bg-slate-800 border-indigo-500/50 text-white font-medium shadow"
                      : "bg-slate-900 border-slate-800 text-slate-400 hover:text-slate-300"
                  }`}
                >
                  {sc} Scenario
                </button>
              ))}
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => { setContent(""); setIsStale(true); }}
                className="flex items-center gap-1 text-[11px] bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 px-2.5 py-1 rounded transition"
                title="Clear Workspace"
              >
                <Trash2 className="w-3 h-3 text-rose-400" />
                Clear
              </button>
              <span className="text-xs font-mono text-slate-400 bg-slate-900 px-2.5 py-1 rounded border border-slate-800">
                State: <b className="text-indigo-400">{status}</b>
              </span>
            </div>
          </div>

          <div className="flex-1 flex flex-col bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
            <div className="border-b border-slate-800 bg-slate-900/50 px-4 py-2.5 flex items-center justify-between text-xs text-slate-400">
              <label htmlFor="draft-editor" className="font-medium text-slate-300">Draft Workspace (Type or edit custom claims freely)</label>
              {auditHead && (
                <span className="font-mono text-[11px] text-slate-500">
                  Head: {auditHead.slice(0, 10)}…
                </span>
              )}
            </div>

            <textarea
              id="draft-editor"
              value={content}
              onChange={(e) => {
                setContent(e.target.value);
                setIsStale(true);
              }}
              placeholder="Type your own claim here to test governance (e.g. 'Our product is 100% safe and the best...')..."
              className="flex-1 min-h-[300px] w-full bg-slate-950/60 p-4 text-sm text-slate-100 focus:outline-none resize-none leading-relaxed font-sans placeholder:text-slate-600"
            />

            {isStale && (
              <div className="bg-amber-950/40 border-t border-amber-800/50 px-4 py-2 text-amber-300 text-xs flex items-center justify-between">
                <span>Draft changed. Re-run governance check before approval.</span>
                <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 bg-amber-900/60 rounded">Unverified</span>
              </div>
            )}

            <div className="border-t border-slate-800 bg-slate-900/50 px-4 py-3 flex items-center justify-between gap-3">
              <button
                onClick={runCheck}
                disabled={busy}
                className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs font-semibold px-4 py-2 rounded-lg transition shadow-md shadow-indigo-600/20"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${busy ? "animate-spin" : ""}`} />
                Run Governance Check
              </button>

              <div className="flex gap-2">
                <button
                  onClick={() => handleAction("send_for_approval")}
                  disabled={busy || isStale || status === "APPROVED" || !review}
                  className="text-xs bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-slate-200 border border-slate-700 px-3.5 py-2 rounded-lg transition"
                >
                  Send for Approval
                </button>
                <button
                  onClick={() => handleAction("approve")}
                  disabled={busy || isStale || status === "APPROVED" || !review}
                  className="flex items-center gap-1.5 text-xs bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-white font-semibold px-4 py-2 rounded-lg transition shadow-md shadow-emerald-600/20"
                >
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  Approve
                </button>
              </div>
            </div>
          </div>
        </section>

        <section className="lg:col-span-5 flex flex-col gap-4" aria-live="polite">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col gap-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-rose-400 flex items-center gap-2 border-b border-slate-800 pb-2">
              <ShieldAlert className="w-4 h-4" />
              Lane A · Grounded Violations ({review?.grounded?.length || 0})
            </h2>
            <div className="space-y-3 max-h-[240px] overflow-y-auto pr-1">
              {review?.grounded && review.grounded.length > 0 ? (
                review.grounded.map((f, i) => (
                  <div key={i} className="bg-slate-950/70 border border-rose-900/40 rounded-lg p-3 text-xs space-y-2">
                    <div className="flex justify-between items-center text-rose-300 font-mono text-[11px]">
                      <span>{f.rule_id} · {f.section}</span>
                      <span className="capitalize text-slate-400">{f.kind.replace("_", " ")}</span>
                    </div>
                    <p className="text-slate-200">
                      Matched <mark className="bg-rose-900/70 text-rose-200 px-1 rounded">{f.matched_term}</mark> in: &ldquo;{f.sentence}&rdquo;
                    </p>
                    <p className="text-slate-400 text-[11px]">{f.reason}</p>
                    {f.suggested_rewrite && (
                      <div className="pt-2 border-t border-slate-800">
                        {pendingFix === f ? (
                          <div role="group" aria-label="Proposed change" className="rounded border border-slate-700 bg-slate-900 p-2 text-xs space-y-1.5">
                            <p><del className="bg-rose-950 text-rose-300 px-1">{f.sentence}</del></p>
                            <p><ins className="bg-emerald-950 text-emerald-300 px-1 no-underline">{f.suggested_rewrite}</ins></p>
                            <div className="flex gap-2 pt-1">
                              <button onClick={confirmFix} className="rounded bg-emerald-700 hover:bg-emerald-600 text-white px-2.5 py-1 text-[11px] font-semibold">Confirm Apply</button>
                              <button onClick={() => setPendingFix(null)} className="rounded bg-slate-700 hover:bg-slate-600 text-slate-200 px-2.5 py-1 text-[11px]">Cancel</button>
                            </div>
                          </div>
                        ) : (
                          <div className="flex justify-between items-center gap-2">
                            <span className="text-emerald-400 text-[11px]">Suggested: {f.suggested_rewrite}</span>
                            <button
                              onClick={() => setPendingFix(f)}
                              className="shrink-0 bg-emerald-700 hover:bg-emerald-600 text-white px-2.5 py-1 rounded text-[11px] font-medium"
                            >
                              Preview Fix
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))
              ) : (
                <p className="text-xs text-slate-500 py-3 text-center">
                  {review ? `${review.trace.claims_checked} claims checked, no grounded violations.` : "Run governance check to inspect claims."}
                </p>
              )}
            </div>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col gap-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-amber-400 flex items-center gap-2 border-b border-slate-800 pb-2">
              <AlertTriangle className="w-4 h-4" />
              Lane B · Needs Human Review ({review?.human_review?.length || 0})
            </h2>
            <div className="space-y-3 max-h-[180px] overflow-y-auto pr-1">
              {review?.human_review && review.human_review.length > 0 ? (
                review.human_review.map((h, i) => (
                  <div key={i} className="bg-slate-950/70 border border-amber-900/40 rounded-lg p-3 text-xs space-y-2">
                    <div className="flex justify-between items-center text-amber-400 font-mono text-[11px]">
                      <span>Route to: {h.route_to}</span>
                      {h.score !== undefined && <span>Nearest: {h.nearest_rule} ({h.score})</span>}
                    </div>
                    <p className="text-slate-200">&ldquo;{h.sentence}&rdquo;</p>
                    <p className="text-slate-400 text-[11px]">{h.reason}</p>
                  </div>
                ))
              ) : (
                <p className="text-xs text-slate-500 py-3 text-center">No claims requiring human escalation.</p>
              )}
            </div>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col gap-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-2 border-b border-slate-800 pb-2">
              <Lock className="w-3.5 h-3.5" />
              Lane C · Suppressed Candidates ({review?.suppressed?.length || 0})
            </h2>
            <div className="space-y-3 max-h-[150px] overflow-y-auto pr-1">
              {review?.suppressed && review.suppressed.length > 0 ? (
                review.suppressed.map((s, i) => (
                  <div key={i} className="bg-slate-950/70 border border-slate-800 rounded-lg p-3 text-xs space-y-1">
                    <div className="flex justify-between text-slate-400 font-mono text-[11px]">
                      <span>Rule: {s.nearest_rule} (Sim: {s.score})</span>
                      <span className="text-amber-400">{s.reason_code}</span>
                    </div>
                    <p className="text-slate-200">&ldquo;{s.candidate}&rdquo;</p>
                    <p className="text-slate-400 text-[11px]">{s.reason}</p>
                  </div>
                ))
              ) : (
                <p className="text-xs text-slate-500 py-2 text-center">No retrieval candidates suppressed.</p>
              )}
            </div>
          </div>
        </section>
      </main>

      {showAuditModal && auditData && (
        <div role="dialog" aria-modal="true" aria-label="Cryptographic Audit Ledger" className="fixed inset-0 bg-black/75 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-3xl w-full p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="font-semibold text-white flex items-center gap-2">
                <History className="w-4 h-4 text-indigo-400" />
                HMAC-SHA256 Tamper-Evident Audit Ledger
              </h3>
              <button onClick={() => setShowAuditModal(false)} aria-label="Close modal" className="text-slate-400 hover:text-white">✕</button>
            </div>

            <div className="p-3 bg-slate-950 rounded-lg border border-slate-800 flex flex-wrap items-center justify-between gap-2 text-xs">
              <div>
                <span className="text-slate-400">Live Chain Status: </span>
                <span className={auditData.verification?.valid ? "text-emerald-400 font-bold" : "text-rose-400 font-bold"}>
                  {auditData.verification?.valid ? "VERIFIED VALID (Intact)" : "BROKEN"}
                </span>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={verifyChainNow}
                  className="flex items-center gap-1 bg-indigo-900/60 hover:bg-indigo-800 text-indigo-200 border border-indigo-700/50 text-[11px] px-2.5 py-1 rounded transition"
                >
                  <ShieldCheck className="w-3.5 h-3.5" />
                  Verify Chain
                </button>
                <button
                  onClick={triggerTamper}
                  className="bg-rose-900/60 hover:bg-rose-800 text-rose-200 border border-rose-700/50 text-[11px] px-2.5 py-1 rounded transition"
                >
                  Simulate Tamper (Sandbox)
                </button>
              </div>
            </div>

            <div className="space-y-1.5 text-xs">
              <div className="text-slate-400 font-semibold">Live Chain Blocks:</div>
              <ChainStrip entries={auditData.entries || []} statuses={auditData.verification?.statuses || []} />
            </div>

            {auditData.tamper && (
              <div className="p-3 bg-rose-950/30 border border-rose-800/60 rounded-lg text-xs space-y-2 text-rose-200">
                <div className="font-bold text-rose-300">
                  Sandbox Copy Tampered: Entry #{auditData.tamper.diff?.sequence} was modified. Its stored HMAC no longer matches its content, so downstream blocks cannot be trusted.
                </div>
                <ChainStrip entries={auditData.tamper.entries || []} statuses={auditData.tamper.after?.statuses || []} />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
