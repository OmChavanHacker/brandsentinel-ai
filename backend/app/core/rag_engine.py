from __future__ import annotations
import logging, os, re, threading
from dataclasses import dataclass
from datetime import date
from time import perf_counter
from typing import Any

log = logging.getLogger("brandsentinel.rag")
MODEL_NAME = "all-MiniLM-L6-v2"
THRESHOLDS = {"embedding": 0.28, "lexical_fallback": 0.08}
REASON_NO_TERM_SUPPORT = "NO_TERM_SUPPORT"

@dataclass(frozen=True)
class PolicySource:
    rule_id: str
    section: str
    passage: str
    expiry_date: str | None
    kind: str
    terms: tuple[str, ...]
    rewrite: str | None = None
    effective_from: str | None = None

KNOWLEDGE_BASE: tuple[PolicySource, ...] = (
    PolicySource("VG-01", "Voice Guide S1.2", "Avoid absolute or unsupported superlatives such as 'best', 'number one', and 'unbeatable'.", None, "violation", ("best", "number one", "unbeatable")),
    PolicySource("CP-2.1-2025", "Claims Policy S2.1", "The 2025 sustainability statistic: 80% recycled packaging is approved only through 2025-12-31.", "2025-12-31", "expired_fact", ("80% recycled", "80% recycled packaging"), rewrite="Our packaging programme is being updated; see our latest sustainability report."),
    PolicySource("CP-2.1-2027", "Claims Policy S2.1", "The 2027 sustainability statistic: 95% recycled packaging is approved from 2027-01-01 through 2027-12-31.", "2027-12-31", "future_fact", ("95% recycled", "95% recycled packaging"), effective_from="2027-01-01"),
    PolicySource("VG-03", "Voice Guide S2.3", "Use direct, clear language and state product benefits without unverifiable comparisons.", None, "guidance", ("clear", "direct")),
)

_TERM_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    s.rule_id: [re.compile(rf"(?<!\w){re.escape(t)}(?!\w)", re.IGNORECASE) for t in s.terms]
    for s in KNOWLEDGE_BASE
}

CLAIM_RE = re.compile(r"\d+(?:[.,]\d+)?\s?%|\b(?:proven|guarantee[sd]?|reduc(?:e|es|ed)|increase[sd]?|faster|safer|customers?|users?|zero fees)\b", re.IGNORECASE)
_WORDS_RE = re.compile(r"[a-z0-9%]+")

def _first_hit(source: PolicySource, sentence: str) -> str | None:
    for pattern in _TERM_PATTERNS[source.rule_id]:
        match = pattern.search(sentence)
        if match:
            return match.group(0)
    return None

def _strip_terms(sentence: str, terms: tuple[str, ...]) -> str | None:
    out = sentence
    for term in terms:
        out = re.sub(rf"(?<!\w){re.escape(term)}(?!\w)\s*,?\s*", " ", out, flags=re.IGNORECASE)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([,.;!?])", r"\1", out)
    out = re.sub(r",\s*,", ",", out).strip()
    if out and sentence[:1].isupper():
        out = out[0].upper() + out[1:]
    if len(out) < 3 or out == sentence.strip():
        return None
    return out

class RagEngine:
    def __init__(self, enable_embeddings: bool = True) -> None:
        self._enabled = enable_embeddings and os.environ.get("DISABLE_EMBEDDINGS", "0") != "1"
        self._model: Any | None = None
        self._vectors: Any | None = None
        self._warmed = False
        self._warm_lock = threading.Lock()
        self.retrieval_mode = "lexical_fallback"

    def warm(self) -> str:
        with self._warm_lock:
            if self._warmed:
                return self.retrieval_mode
            if self._enabled:
                try:
                    from sentence_transformers import SentenceTransformer
                    local_only = os.environ.get("EMBEDDING_LOCAL_ONLY", "0") == "1"
                    model = SentenceTransformer(MODEL_NAME, local_files_only=local_only)
                    vectors = model.encode([s.passage for s in KNOWLEDGE_BASE], normalize_embeddings=True)
                    model.encode(["warm-up query"], normalize_embeddings=True)
                    self._model, self._vectors = model, vectors
                    self.retrieval_mode = "embedding"
                except Exception:
                    self._model = self._vectors = None
                    self.retrieval_mode = "lexical_fallback"
            self._warmed = True
            return self.retrieval_mode

    @staticmethod
    def _lexical_score(sentence: str, source: PolicySource) -> float:
        words = set(_WORDS_RE.findall(sentence.lower()))
        source_words = set(_WORDS_RE.findall(source.passage.lower()))
        return len(words & source_words) / max(1, len(words | source_words))

    def _nearest(self, sentence: str) -> tuple[float, PolicySource]:
        if self._model is not None and self._vectors is not None:
            query = self._model.encode([sentence], normalize_embeddings=True)[0]
            scores = self._vectors @ query
            best = int(scores.argmax())
            return float(scores[best]), KNOWLEDGE_BASE[best]
        return max(((self._lexical_score(sentence, s), s) for s in KNOWLEDGE_BASE), key=lambda pair: pair[0])

    @staticmethod
    def isolate_claims(content: str) -> list[str]:
        return [item.strip() for item in re.split(r"(?<=[.!?])\s+|\n+", content) if item.strip()]

    def review(self, content: str, today: date | None = None) -> dict[str, Any]:
        if not self._warmed:
            self.warm()
        today = today or date.today()
        grounded: list[dict[str, Any]] = []
        human_review: list[dict[str, Any]] = []
        suppressed: list[dict[str, Any]] = []

        t_start = perf_counter()
        sentences = self.isolate_claims(content)
        claim_isolation_s = perf_counter() - t_start
        deterministic_s = 0.0
        retrieval_s = 0.0
        threshold = THRESHOLDS[self.retrieval_mode]

        for sentence in sentences:
            t0 = perf_counter()
            supported = False
            for source in KNOWLEDGE_BASE:
                term = _first_hit(source, sentence)
                if term is None or source.kind == "guidance":
                    continue
                supported = True
                outcome = self._evaluate(source, sentence, term, today)
                if outcome is None:
                    continue
                lane, item = outcome
                (grounded if lane == "grounded" else human_review).append(item)
            deterministic_s += perf_counter() - t0

            if not supported and CLAIM_RE.search(sentence):
                t1 = perf_counter()
                score, nearest = self._nearest(sentence)
                retrieval_s += perf_counter() - t1
                if score >= threshold:
                    reason = f"Retrieval proposed rule {nearest.rule_id} but lacks approved term support. Routed to Legal."
                    suppressed.append({
                        "candidate": sentence,
                        "nearest_rule": nearest.rule_id,
                        "score": round(score, 2),
                        "reason_code": REASON_NO_TERM_SUPPORT,
                        "reason": f"Retrieval matched {nearest.rule_id} at similarity {score:.2f}, but lacks approved term support.",
                    })
                else:
                    reason = "No approved source supports this claim. Cite evidence or obtain Legal approval."
                human_review.append(self._review_item(sentence, reason, nearest_rule=nearest.rule_id, score=round(score, 2)))

        grounded.sort(key=lambda f: f["kind"] != "expired_fact")
        total_s = perf_counter() - t_start
        return {
            "grounded": grounded,
            "human_review": human_review,
            "suppressed": suppressed,
            "trace": {
                "claim_isolation_ms": round(claim_isolation_s * 1000, 2),
                "deterministic_ms": round(deterministic_s * 1000, 2),
                "vector_rag_ms": round(retrieval_s * 1000, 2),
                "total_ms": round(total_s * 1000, 2),
                "retrieval_mode": self.retrieval_mode,
                "validator": "cite-or-stay-silent",
                "claims_checked": len(sentences),
                "suppressed_count": len(suppressed),
            },
        }

    def _evaluate(self, source: PolicySource, sentence: str, term: str, today: date) -> tuple[str, dict[str, Any]] | None:
        if source.kind == "violation":
            return "grounded", self._finding(source, sentence, term, "Grounded policy violation", _strip_terms(sentence, source.terms))
        if source.kind in {"expired_fact", "future_fact"}:
            if source.effective_from and today < date.fromisoformat(source.effective_from):
                return "human_review", self._review_item(sentence, "Known policy source is not yet effective; Legal must confirm publication timing.", nearest_rule=source.rule_id)
            if source.expiry_date and today > date.fromisoformat(source.expiry_date):
                return "grounded", self._finding(source, sentence, term, "Approved fact is expired", source.rewrite)
        return None

    @staticmethod
    def _finding(source: PolicySource, sentence: str, term: str, reason: str, rewrite: str | None) -> dict[str, Any]:
        return {
            "rule_id": source.rule_id,
            "kind": source.kind,
            "section": source.section,
            "source_passage": source.passage,
            "expiry_date": source.expiry_date,
            "sentence": sentence,
            "matched_term": term,
            "reason": reason,
            "suggested_rewrite": rewrite,
            "advice": "Remove the unsupported claim or provide an approved source." if rewrite is None else "Review the suggested rewrite, then apply or edit it.",
        }

    @staticmethod
    def _review_item(sentence: str, reason: str, **extra: Any) -> dict[str, Any]:
        return {"sentence": sentence, "reason": reason, "route_to": "LEGAL", "status": "NEEDS_HUMAN_REVIEW", **extra}
