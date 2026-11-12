"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import {
  CheckCircle2,
  AlertTriangle,
  ShieldAlert,
  RefreshCw,
  Lock,
  History,
  ShieldCheck,
  Trash2,
  UploadCloud
} from "lucide-react";
import { API_BASE_URL as API, apiFetch } from "../lib/api";

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
  risk_class?: string;
  version?: number;
  policy_version?: string;
  approvals?: { actor: string; role: string }[];
  invalidation_message?: string;
  trace: {
    claim_isolation_ms: number;
    deterministic_ms: number;
    vector_rag_ms: number;
    total_ms: number;
    retrieval_mode: string;
    policy_version: string;
    policy_sha256: string;
    validator: string;
    claims_checked: number;
    suppressed_count: number;
  };
};

type PolicyInfo = {
  active: { version: string; sha256: string; rule_count: number };
  staged: Array<{ version: string; sha256: string; rule_count: number }>;
  history: string[];
};

type Scenario = "expired" | "superlative" | "unverified" | "financial";
type Persona = {
  id: string;
  name: string;
  username: string;
  password: string;
  roles: string[];
};
const PERSONAS: Persona[] = [
  { id: "maya.creator", name: "Maya", username: "maya.creator", password: "demo-maya", roles: ["CREATOR"] },
  { id: "rahul.brand", name: "Rahul", username: "rahul.brand", password: "demo-rahul", roles: ["BRAND_LEAD"] },
  { id: "marcus.marketing", name: "Marcus", username: "marcus.marketing", password: "demo-marcus", roles: ["MARKETING_HEAD"] },
  { id: "priya.legal", name: "Priya", username: "priya.legal", password: "demo-priya", roles: ["LEGAL_COUNSEL"] },
  { id: "sam.dual", name: "Sam", username: "sam.dual", password: "demo-sam", roles: ["MARKETING_HEAD", "LEGAL_COUNSEL"] },
];

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
  const [sessionVersion, setSessionVersion] = useState<number>(1);
  const [riskClass, setRiskClass] = useState<string>("STANDARD");
  const [activePolicyVersion, setActivePolicyVersion] = useState<string>("");
  const [approvals, setApprovals] = useState<{ actor: string; role: string }[]>([]);
  const [content, setContent] = useState<string>("");
  const [role, setRole] = useState<string>("CREATOR");
  const [scenario, setScenario] = useState<Scenario>("expired");
  const [token, setToken] = useState<string>("");
  const [persona, setPersona] = useState<Persona>(PERSONAS[0]);
  const [showCredentials, setShowCredentials] = useState<boolean>(false);
  const [showTour, setShowTour] = useState<boolean>(true);
  const [tourSteps, setTourSteps] = useState<boolean[]>(Array(8).fill(false));
  const [showPackVerifier, setShowPackVerifier] = useState<boolean>(false);
  const [packVerification, setPackVerification] = useState<{ valid: boolean; checks: { name: string; passed: boolean }[] } | null>(null);
  const [packBusy, setPackBusy] = useState<boolean>(false);
  const [showPolicyDrawer, setShowPolicyDrawer] = useState<boolean>(false);
  const [policyImpact, setPolicyImpact] = useState<any>(null);
  const [invalidationMessage, setInvalidationMessage] = useState<string>("");
  const [review, setReview] = useState<ReviewResult | null>(null);
  const [status, setStatus] = useState<string>("WORKSPACE_LOADED");
  const [auditHead, setAuditHead] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [busy, setBusy] = useState<boolean>(false);
  const [isStale, setIsStale] = useState<boolean>(false);
  const [pendingFix, setPendingFix] = useState<Finding | null>(null);
  const [showAuditModal, setShowAuditModal] = useState<boolean>(false);
  const [auditData, setAuditData] = useState<any>(null);
  const [policyToken, setPolicyToken] = useState<string>("");
  const [policyUsername, setPolicyUsername] = useState<string>("");
  const [policyPassword, setPolicyPassword] = useState<string>("");
  const [policyVersion, setPolicyVersion] = useState<string>("");
  const [policyFile, setPolicyFile] = useState<File | null>(null);
  const [policyData, setPolicyData] = useState<PolicyInfo | null>(null);
  const [policyMessage, setPolicyMessage] = useState<string>("");
  const [policyBusy, setPolicyBusy] = useState<boolean>(false);
  const [packPassed, setPackPassed] = useState<boolean>(false);
  const [packFailed, setPackFailed] = useState<boolean>(false);
  const draftSaveTimer = useRef<number | null>(null);

  const setTourStep = (index: number) => {
    setTourSteps((steps) => steps.map((done, current) => current === index ? true : done));
  };

  const signInPersona = async (selected: Persona, selectedRole = selected.roles[0]) => {
    const res = await apiFetch(`${API}/api/login`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ username: selected.username, password: selected.password, role: selectedRole }),
    });
    const data = await res.json();
    setPersona(selected);
    setRole(data.role);
    setToken(data.token);
    sessionStorage.setItem("bs_token", data.token);
    sessionStorage.setItem("bs_persona", selected.id);
    sessionStorage.setItem("bs_role", data.role);
    const canManagePolicy = data.role === "BRAND_LEAD" || data.role === "LEGAL_COUNSEL";
    setPolicyToken(canManagePolicy ? data.token : "");
    setPolicyData(null);
    if (canManagePolicy) {
      const policies = await apiFetch(`${API}/api/policies`, {
        headers: { Authorization: `Bearer ${data.token}` },
      });
      setPolicyData(await policies.json());
    }
  };

  const restoreFromServer = (data: any) => {
    setSessionId(data.id || data.session_id);
    const localDraft = sessionStorage.getItem("bs_draft");
    setContent(localDraft ?? data.content);
    setStatus(data.state);
    setSessionVersion(data.version || 1);
    setRiskClass(data.risk_class || "STANDARD");
    setApprovals(data.approvals || []);
    setActivePolicyVersion(data.policy_version || "");
    setAuditData({ entries: data.ledger || [] });
    setAuditHead(data.audit_head || data.ledger?.[data.ledger.length - 1]?.hash || "");
    setScenario(data.scenario || "expired");
    setReview(data.review || null);
    const changedAfterApproval = localDraft !== null
      && localDraft !== data.content
      && (data.approvals?.length > 0 || data.state === "PENDING_DUAL" || data.state === "APPROVED");
    setInvalidationMessage(data.invalidation_message || (changedAfterApproval ? "Previous sign-offs invalidated due to content mutation" : ""));
    sessionStorage.setItem("bs_session", data.id || data.session_id);
    setIsStale(Boolean(data.invalidation_message) || (localDraft !== null && localDraft !== data.content));
  };

  const initSession = async (sc: Scenario) => {
    setBusy(true);
    setError("");
    setPendingFix(null);
    try {
      const res = await apiFetch(`${API}/api/session`, {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({ scenario: sc }),
      });
      const data = await res.json();
      setSessionId(data.session_id);
      sessionStorage.setItem("bs_session", data.session_id);
      sessionStorage.removeItem("bs_draft");
      setContent(data.content);
      setStatus(data.state);
      setAuditHead(data.audit_head);
      setSessionVersion(data.version || 1);
      setRiskClass(data.risk_class || "STANDARD");
      setApprovals(data.approvals || []);
      setActivePolicyVersion(data.policy_version || "");
      setIsStale(false);
      setScenario(sc);
      setReview(null);
      setInvalidationMessage("");
      setTourSteps(Array(8).fill(false));
    } catch (e: any) {
      setError(e.message || "Failed to connect to backend server.");
    } finally {
      setBusy(false);
    }
  };

  const load = (sc: Scenario) => initSession(sc);

  useEffect(() => {
    let active = true;
    const sid = sessionStorage.getItem("bs_session");
    const tok = sessionStorage.getItem("bs_token");
    const personaId = sessionStorage.getItem("bs_persona");
    const restoredRole = sessionStorage.getItem("bs_role");
    if (tok) setToken(tok);
    if (personaId) {
      const restoredPersona = PERSONAS.find((item) => item.id === personaId);
      if (restoredPersona) {
        setPersona(restoredPersona);
        const activeRole = restoredRole && restoredPersona.roles.includes(restoredRole)
          ? restoredRole
          : restoredPersona.roles[0];
        setRole(activeRole);
        if (activeRole === "BRAND_LEAD" || activeRole === "LEGAL_COUNSEL") {
          setPolicyToken(tok || "");
          if (tok) {
            void apiFetch(`${API}/api/policies`, {
              headers: { Authorization: `Bearer ${tok}` },
            }).then((response) => response.json()).then((data) => {
              if (active) setPolicyData(data);
            }).catch((e: unknown) => {
              if (active) setError(e instanceof Error ? e.message : "Could not restore policy status.");
            });
          }
        }
      }
    }
    const restore = sid
      ? apiFetch(`${API}/api/session/${encodeURIComponent(sid)}`, {
          headers: tok ? { Authorization: `Bearer ${tok}` } : {},
        }).then((res) => res.json()).then((data) => {
          if (active) restoreFromServer(data);
        }).catch(async () => {
          sessionStorage.removeItem("bs_session");
          if (active) await load("expired");
        })
      : load("expired");
    void restore;
    if (!tok) {
      void signInPersona(PERSONAS[0]).catch((e: unknown) => {
        if (active) setError(e instanceof Error ? e.message : "Could not sign in as the demo creator.");
      });
    }
    return () => { active = false; };
  }, []);

  const handleScenarioChange = (sc: Scenario) => {
    setScenario(sc);
    initSession(sc);
  };

  const restoreCurrentSession = async () => {
    if (!sessionId) return;
    const response = await apiFetch(`${API}/api/session/${encodeURIComponent(sessionId)}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    restoreFromServer(await response.json());
  };

  const runCheck = async () => {
    if (!sessionId || !content.trim()) return;
    setBusy(true);
    setError("");
    setPendingFix(null);
    try {
      const res = await apiFetch(`${API}/api/review`, {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({ session_id: sessionId, content }),
      });
      const data: ReviewResult = await res.json();
      setReview(data);
      setStatus(data.state);
      setAuditHead(data.audit_head);
      setSessionVersion(data.version || sessionVersion);
      setRiskClass(data.risk_class || "STANDARD");
      setApprovals(data.approvals || []);
      setActivePolicyVersion(data.policy_version || data.trace.policy_version);
      setInvalidationMessage(data.invalidation_message || "");
      setIsStale(false);
      if (data.risk_class === "HIGH") setTourStep(0);
      if (invalidationMessage) setTourStep(4);
      if (policyData && data.trace.policy_version === policyData.active.version) setTourStep(7);
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
      const res = await apiFetch(`${API}/api/action`, {
        method: "POST",
        headers: { ...JSON_HEADERS, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          session_id: sessionId,
          action,
          role,
          content,
        }),
      });
      const data = await res.json();
      setStatus(data.state);
      setAuditHead(data.audit_head);
      setApprovals(data.approvals || []);
      setSessionVersion(data.version || sessionVersion);
      setReview((previous) => previous ? { ...previous, approvals: data.approvals } : previous);
      if (action === "send_for_approval" && data.state === "PENDING_DUAL") setTourStep(2);
      if (data.state === "APPROVED") setTourStep(5);
    } catch (e: any) {
      if (e instanceof Error && e.message.includes("(409 Conflict)")) {
        try {
          await restoreCurrentSession();
        } catch (restoreError: unknown) {
          const restoreMessage = restoreError instanceof Error ? restoreError.message : "Session refresh failed.";
          setError(`${e.message} ${restoreMessage}`);
          return;
        }
      }
      setError(e.message || "Action transition failed.");
      if (persona.id === "sam.dual" && e.message?.includes("One person cannot fill both slots")) setTourStep(3);
    } finally {
      setBusy(false);
    }
  };

  const openAudit = async () => {
    if (!sessionId) return;
    setBusy(true);
    try {
      const res = await apiFetch(`${API}/api/audit?session_id=${sessionId}`);
      const data = await res.json();
      setAuditData(data);
      setShowAuditModal(true);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load audit trail.");
    } finally {
      setBusy(false);
    }
  };

  const verifyChainNow = async () => {
    if (!sessionId) return;
    try {
      const res = await apiFetch(`${API}/api/audit/verify?session_id=${sessionId}`);
      const v = await res.json();
      setAuditData((prev: any) => ({ ...prev, verification: v }));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Verification call failed.");
    }
  };

  const triggerTamper = async () => {
    if (!sessionId) return;
    try {
      const res = await apiFetch(`${API}/api/audit/simulate-tamper?session_id=${sessionId}`, {
        method: "POST",
      });
      const data = await res.json();
      setAuditData((prev: any) => ({ ...prev, tamper: data }));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Tamper simulation failed.");
    }
  };

  const refreshPolicies = async (token = policyToken) => {
    const res = await apiFetch(`${API}/api/policies`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = await res.json();
    setPolicyData(data);
    return data as PolicyInfo;
  };

  const loginBrandLead = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPolicyBusy(true);
    setPolicyMessage("");
    try {
      const res = await apiFetch(`${API}/api/login`, {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({ username: policyUsername, password: policyPassword, role: "BRAND_LEAD" }),
      });
      const data = await res.json();
      if (data.role !== "BRAND_LEAD") throw new Error("Policy management requires a BRAND_LEAD account.");
      setPolicyToken(data.token);
      setPolicyPassword("");
      await refreshPolicies(data.token);
      setPolicyMessage(`Signed in as ${data.user}.`);
    } catch (e: any) {
      setPolicyMessage(e.message || "Sign-in failed.");
    } finally {
      setPolicyBusy(false);
    }
  };

  const stagePolicy = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!policyFile) {
      setPolicyMessage("Choose a CSV, JSON, or Markdown rulebook first.");
      return;
    }
    setPolicyBusy(true);
    setPolicyMessage("Uploading rulebook…");
    try {
      const form = new FormData();
      form.append("file", policyFile);
      if (policyVersion.trim()) form.append("version_tag", policyVersion.trim());
      const res = await apiFetch(`${API}/api/policies/stage`, {
        method: "POST",
        headers: { Authorization: `Bearer ${policyToken}` },
        body: form,
      });
      const data = await res.json();
      setPolicyImpact(data.impact ?? null);
      setPolicyMessage(`Staging ${data.version}…`);
      for (let attempt = 0; attempt < 240; attempt += 1) {
        await new Promise<void>((resolve) => window.setTimeout(resolve, 750));
        const jobRes = await apiFetch(`${API}/api/policies/jobs/${data.job_id}`, {
          headers: { Authorization: `Bearer ${policyToken}` },
        });
        const job = await jobRes.json();
        if (job.status === "staged") {
          setPolicyMessage(`Version ${job.version} staged with ${job.rule_count} rules. Activate it when ready.`);
          await refreshPolicies();
          return;
        }
        if (job.status === "failed") throw new Error(job.error || "Policy staging failed.");
      }
      throw new Error("Policy staging is taking longer than expected. Check policy status again later.");
    } catch (e: any) {
      setPolicyMessage(e.message || "Policy upload failed.");
    } finally {
      setPolicyBusy(false);
    }
  };

  const activatePolicy = async (version: string) => {
    setPolicyBusy(true);
    setPolicyMessage("");
    let activatedVersion: string | null = null;
    try {
      const res = await apiFetch(`${API}/api/policies/${encodeURIComponent(version)}/activate`, {
        method: "POST",
        headers: { Authorization: `Bearer ${policyToken}` },
      });
      const data = await res.json();
      activatedVersion = data.version;
      if (review && review.trace.policy_version !== activatedVersion) setIsStale(true);
      await refreshPolicies();
      setPolicyMessage(`Policy version ${activatedVersion} is now active.`);
    } catch (e: any) {
      setPolicyMessage(activatedVersion
        ? `Policy version ${activatedVersion} is active, but the status refresh failed: ${e.message || "Refresh failed."}`
        : e.message || "Policy activation failed.");
    } finally {
      setPolicyBusy(false);
    }
  };

  const signOffPolicy = async (version: string) => {
    setPolicyBusy(true);
    setPolicyMessage("");
    try {
      await apiFetch(`${API}/api/policies/${encodeURIComponent(version)}/signoff`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      setPolicyMessage(`Legal sign-off recorded for ${version}.`);
    } catch (e: unknown) {
      setPolicyMessage(e instanceof Error ? e.message : "Policy sign-off failed.");
    } finally {
      setPolicyBusy(false);
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
    sessionStorage.setItem("bs_draft", content.replace(pendingFix.sentence, () => pendingFix.suggested_rewrite!));
    setTourStep(1);
    setPendingFix(null);
    setIsStale(true);
  };

  const saveDraft = (nextContent: string) => {
    sessionStorage.setItem("bs_draft", nextContent);
    if (draftSaveTimer.current) window.clearTimeout(draftSaveTimer.current);
    if (!sessionId) return;
    draftSaveTimer.current = window.setTimeout(() => {
      void apiFetch(`${API}/api/session/${encodeURIComponent(sessionId)}`, {
        method: "PATCH",
        headers: { ...JSON_HEADERS, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ content: nextContent }),
      }).then((res) => res.json()).then((data) => {
        setStatus(data.state);
        setSessionVersion(data.version || sessionVersion);
        setApprovals(data.approvals || []);
        setInvalidationMessage(data.invalidation_message || "");
        setAuditHead(data.audit_head || "");
      }).catch((e: unknown) => setError(e instanceof Error ? e.message : "Draft could not be saved."));
    }, 350);
  };

  const resetDemo = async () => {
    sessionStorage.removeItem("bs_session");
    sessionStorage.removeItem("bs_draft");
    await signInPersona(PERSONAS[0]);
    await load("expired");
  };

  const downloadAuditPack = async () => {
    if (!sessionId) return;
    setBusy(true);
    try {
      const response = await apiFetch(`${API}/api/audit/report?session_id=${encodeURIComponent(sessionId)}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `brandsentinel-audit-${sessionId}.zip`;
      link.click();
      URL.revokeObjectURL(url);
      setShowPackVerifier(true);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not download the signed audit pack.");
    } finally {
      setBusy(false);
    }
  };

  const verifyPack = async (file?: File) => {
    if (!file) return;
    setPackBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await apiFetch(`${API}/api/audit/verify-pack`, { method: "POST", body: form });
      const result = await response.json();
      setPackVerification(result);
      setPackPassed((passed) => passed || result.valid);
      setPackFailed((failed) => failed || !result.valid);
      if (packPassed && !result.valid) setTourStep(6);
      if (result.valid) setPackPassed(true);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not verify the uploaded audit pack.");
    } finally {
      setPackBusy(false);
    }
  };

  const downloadSampleRulebook = (valid: boolean) => {
    const csv = valid
      ? "rule_id,section,passage,kind,terms,rewrite\nJUDGE-01,Claims,Substantiate guaranteed returns,violation,guaranteed|zero risk,Describe verified outcomes without guarantees\n"
      : "rule_id,section,passage,kind,terms,rewrite\nJUDGE-BAD,Claims,This rule has no trigger terms,violation,,\n";
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = valid ? "sample_rulebook_good.csv" : "sample_rulebook_bad.csv";
    link.click();
    URL.revokeObjectURL(url);
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
          <button
            onClick={openAudit}
            className="flex items-center gap-1.5 text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 px-3 py-1.5 rounded-lg transition"
          >
            <History className="w-3.5 h-3.5" />
            Audit Ledger
          </button>
        </div>
      </header>

      <nav className="relative flex flex-wrap items-center gap-2 border-b border-slate-800 bg-slate-900/40 px-6 py-2" aria-label="Demo personas">
        <span className="mr-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Demo accounts</span>
        {PERSONAS.map((item) => (
          <button
            key={item.id}
            onClick={() => { void signInPersona(item).catch((e: unknown) => setError(e instanceof Error ? e.message : "Persona sign-in failed.")); }}
            className={`rounded-full border px-3 py-1 text-xs transition ${
              persona.id === item.id ? "border-indigo-500 bg-indigo-600/20 text-indigo-200" : "border-slate-700 bg-slate-900 text-slate-300 hover:border-slate-500"
            }`}
          >
            {item.name}
          </button>
        ))}
        {persona.id === "sam.dual" && (
          <div className="ml-1 flex rounded-lg border border-slate-700 bg-slate-950 p-0.5" role="group" aria-label="Sam role">
            {persona.roles.map((samRole) => (
              <button
                key={samRole}
                onClick={() => { void signInPersona(persona, samRole).catch((e: unknown) => setError(e instanceof Error ? e.message : "Could not switch Sam's role.")); }}
                className={`rounded px-2 py-1 text-[10px] ${role === samRole ? "bg-slate-700 text-white" : "text-slate-400"}`}
              >
                {samRole === "MARKETING_HEAD" ? "as Marketing" : "as Legal"}
              </button>
            ))}
          </div>
        )}
        <span className="text-[10px] text-slate-500">{role.replace("_", " ")}</span>
        <button onClick={() => setShowCredentials((show) => !show)} className="ml-auto rounded border border-slate-700 px-2.5 py-1 text-[11px] text-slate-300 hover:bg-slate-800">
          Credentials
        </button>
        <button onClick={() => setShowPolicyDrawer((show) => !show)} className="rounded border border-indigo-800 px-2.5 py-1 text-[11px] text-indigo-300 hover:bg-indigo-950">
          {showPolicyDrawer ? "Close Policy Drawer" : "Policy Drawer"}
        </button>
        {showCredentials && (
          <div className="absolute right-6 top-11 z-30 w-80 rounded-xl border border-slate-700 bg-slate-900 p-4 shadow-xl">
            <p className="mb-2 text-xs font-semibold text-slate-200">Demo only — synthetic data</p>
            <ul className="space-y-1 text-[11px] text-slate-400">
              {PERSONAS.map((item) => <li key={item.id} className="flex justify-between gap-3"><span>{item.username}</span><code>{item.password}</code></li>)}
            </ul>
          </div>
        )}
      </nav>

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
              {(["expired", "superlative", "unverified", "financial"] as const).map((sc) => (
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
              <span className="flex items-center gap-3 font-mono text-[10px] text-slate-500">
                <span>Risk: <b className={riskClass === "HIGH" ? "text-rose-300" : "text-emerald-300"}>{riskClass}</b></span>
                <span>v{sessionVersion}</span>
                {activePolicyVersion && <span>Policy: {activePolicyVersion}</span>}
                {auditHead && <span>Head: {auditHead.slice(0, 10)}…</span>}
              </span>
            </div>

            <textarea
              id="draft-editor"
              value={content}
              onChange={(e) => {
                setContent(e.target.value);
                setIsStale(true);
                if (status === "PENDING_DUAL" || status === "APPROVED") {
                  setInvalidationMessage("Previous sign-offs invalidated due to content mutation");
                }
                saveDraft(e.target.value);
              }}
              placeholder="Type your own claim here to test governance (e.g. 'Our product is 100% safe and the best...')..."
              className="flex-1 min-h-[300px] w-full bg-slate-950/60 p-4 text-sm text-slate-100 focus:outline-none resize-none leading-relaxed font-sans placeholder:text-slate-600"
            />

            {isStale && (
              <div className="bg-amber-950/40 border-t border-amber-800/50 px-4 py-2 text-amber-300 text-xs flex items-center justify-between">
                <span>Draft or policy changed. Re-run governance check before approval.</span>
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
                  disabled={busy || isStale || status !== "REVIEWED" || !review}
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
          <div className="rounded-xl border border-indigo-900/70 bg-slate-900 p-4">
            <div className="flex items-center justify-between gap-3">
              <button onClick={() => setShowTour((show) => !show)} className="text-left text-sm font-semibold text-indigo-200">
                3-Minute Judge Tour: {tourSteps.filter(Boolean).length}/8 completed
              </button>
              <button onClick={() => { void resetDemo(); }} className="rounded border border-slate-700 px-2.5 py-1 text-[11px] text-slate-300 hover:bg-slate-800">Reset Demo</button>
            </div>
            {showTour && (
              <>
                <ol className="mt-3 space-y-1.5 text-[11px] text-slate-400">
                  {[
                    "Run a governance check on high-risk financial copy",
                    "Confirm a suggested fix in Lane A",
                    "Submit for dual approval",
                    "Demonstrate Sam's separation-of-duties block",
                    "Mutate content and re-run the check",
                    "Collect separate Marcus and Priya sign-offs",
                    "Download and verify both signed and tampered packs",
                    "Stage, diff, activate a policy, and re-check",
                  ].map((step, index) => (
                    <li key={step} className={tourSteps[index] ? "text-emerald-300" : ""}>
                      <span className="mr-2">{tourSteps[index] ? "✓" : `${index + 1}.`}</span>{step}
                    </li>
                  ))}
                </ol>
                <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-800 pt-3">
                  <button onClick={() => downloadSampleRulebook(true)} className="rounded border border-emerald-800 px-2.5 py-1.5 text-[10px] text-emerald-300 hover:bg-emerald-950">Download good CSV</button>
                  <button onClick={() => downloadSampleRulebook(false)} className="rounded border border-rose-900 px-2.5 py-1.5 text-[10px] text-rose-300 hover:bg-rose-950">Download bad CSV</button>
                  <button onClick={() => { void downloadAuditPack(); }} disabled={!sessionId || busy} className="rounded bg-indigo-600 px-2.5 py-1.5 text-[10px] font-semibold text-white disabled:opacity-50">Download signed .zip</button>
                </div>
                {showPackVerifier && (
                  <div
                    className="mt-3 rounded-lg border border-dashed border-slate-700 bg-slate-950 p-3"
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={(event) => {
                      event.preventDefault();
                      void verifyPack(event.dataTransfer.files[0]);
                    }}
                  >
                    <label className="block text-[11px] text-slate-300">
                      Drop signed or tampered .zip here, or choose a file
                      <input
                        type="file"
                        accept=".zip,application/zip"
                        disabled={packBusy}
                        onChange={(event) => { void verifyPack(event.target.files?.[0]); }}
                        className="mt-2 block w-full text-[10px] text-slate-400 file:mr-2 file:rounded file:border-0 file:bg-slate-800 file:px-2 file:py-1 file:text-[10px] file:text-slate-200"
                      />
                    </label>
                    {packBusy && <p className="mt-2 text-[10px] text-slate-400">Verifying pack…</p>}
                    {packVerification && (
                      <ul className="mt-2 space-y-1 text-[10px]">
                        {packVerification.checks.map((check) => (
                          <li key={check.name} className={check.passed ? "text-emerald-300" : "text-rose-300"}>
                            {check.passed ? "PASS" : "FAIL"} · {check.name}
                          </li>
                        ))}
                      </ul>
                    )}
                    {packPassed && packFailed && <p className="mt-2 text-[10px] text-emerald-300">Signed pack passed and tampered pack failed as expected.</p>}
                  </div>
                )}
              </>
            )}
          </div>

          {status === "PENDING_DUAL" && (
            <div className="rounded-lg border border-amber-700 bg-amber-950/60 px-4 py-3 text-xs text-amber-200">
              <p className="font-semibold">High-risk: 2 of 2 sign-offs required</p>
              <p className="mt-1 text-amber-300/80">{approvals.length} of 2 sign-offs recorded</p>
            </div>
          )}
          {invalidationMessage && <p role="status" className="rounded border border-amber-800 bg-amber-950/50 px-3 py-2 text-[11px] text-amber-200">{invalidationMessage}</p>}

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

      <section hidden={!showPolicyDrawer} className="mx-6 mb-6 rounded-xl border border-slate-800 bg-slate-900 p-4">
        <div className="mb-3 flex items-center justify-between border-b border-slate-800 pb-2">
          <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-indigo-300">
            <UploadCloud className="h-4 w-4" />
            Dynamic Policy Management
          </h2>
          {policyToken && (
            <button
              onClick={() => { setPolicyToken(""); setPolicyData(null); setPolicyMessage("Signed out."); }}
              className="text-xs text-slate-400 hover:text-white"
            >
              Sign out
            </button>
          )}
        </div>
        {!policyToken ? (
          <form onSubmit={loginBrandLead} className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-[11px] text-slate-400">
              Brand lead username
              <input
                value={policyUsername}
                onChange={(event) => setPolicyUsername(event.target.value)}
                autoComplete="username"
                required
                className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white"
              />
            </label>
            <label className="flex flex-col gap-1 text-[11px] text-slate-400">
              Password
              <input
                type="password"
                value={policyPassword}
                onChange={(event) => setPolicyPassword(event.target.value)}
                autoComplete="current-password"
                required
                className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white"
              />
            </label>
            <button
              disabled={policyBusy}
              className="rounded bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50"
            >
              {policyBusy ? "Signing in…" : "Sign in as Brand Lead"}
            </button>
          </form>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {role === "BRAND_LEAD" && <form onSubmit={stagePolicy} className="flex flex-wrap items-end gap-3">
              <label className="flex min-w-[220px] flex-col gap-1 text-[11px] text-slate-400">
                Rulebook (CSV, JSON, Markdown)
                <input
                  type="file"
                  accept=".csv,.json,.md,.markdown"
                  onChange={(event) => setPolicyFile(event.target.files?.[0] ?? null)}
                  required
                  className="max-w-full text-xs text-slate-300 file:mr-3 file:rounded file:border-0 file:bg-slate-800 file:px-3 file:py-2 file:text-xs file:text-slate-200"
                />
              </label>
              <label className="flex flex-col gap-1 text-[11px] text-slate-400">
                Version tag (optional)
                <input
                  value={policyVersion}
                  onChange={(event) => setPolicyVersion(event.target.value)}
                  maxLength={64}
                  placeholder="generated from file hash"
                  className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white"
                />
              </label>
              <button
                disabled={policyBusy || !policyFile}
                className="rounded bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50"
              >
                {policyBusy ? "Processing…" : "Stage Rulebook"}
              </button>
            </form>}
            <div className="space-y-2 text-xs">
              {policyImpact && (
                <div className="rounded border border-indigo-900 bg-slate-950 p-3 text-[11px]">
                  <p className="font-semibold text-indigo-200">Before / After Impact Diff</p>
                  <p className="mt-1 text-slate-400">
                    {policyImpact.before.version} ({policyImpact.before.rule_count} rules) → {policyImpact.after.version} ({policyImpact.after.rule_count} rules)
                  </p>
                  <p className="mt-1 text-emerald-300">Added: {policyImpact.added_rule_ids.join(", ") || "none"}</p>
                  <p className="text-rose-300">Removed: {policyImpact.removed_rule_ids.join(", ") || "none"}</p>
                </div>
              )}
              {policyData && (
                <>
                  <p className="text-slate-300">
                    Active: <b className="font-mono text-emerald-300">{policyData.active.version}</b>
                    <span className="ml-2 text-slate-500">({policyData.active.rule_count} rules)</span>
                  </p>
                  {review && (
                    <p className="text-slate-400">
                      Last check: <b className="font-mono text-slate-300">{review.trace.policy_version}</b>
                      {isStale && <span className="ml-2 text-amber-300">out of date</span>}
                    </p>
                  )}
                  {policyData.staged.filter((item) => item.version !== policyData.active.version).map((item) => (
                    <div key={item.version} className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-800 pt-2">
                      <span className="font-mono text-slate-300">{item.version} <span className="text-slate-500">· {item.rule_count} rules</span></span>
                      <div className="flex gap-2">
                        {role === "LEGAL_COUNSEL" && <button disabled={policyBusy} onClick={() => signOffPolicy(item.version)} className="rounded border border-emerald-800 px-3 py-1 text-emerald-300 disabled:opacity-50">Legal sign-off</button>}
                        {role === "BRAND_LEAD" && <button disabled={policyBusy} onClick={() => activatePolicy(item.version)} className="rounded border border-indigo-700 px-3 py-1 text-indigo-300 hover:bg-indigo-950 disabled:opacity-50">Activate snapshot</button>}
                      </div>
                    </div>
                  ))}
                </>
              )}
            </div>
          </div>
        )}
        {policyMessage && <p role="status" className="mt-3 text-xs text-slate-300">{policyMessage}</p>}
      </section>

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
