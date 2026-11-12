from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, Mapping

import numpy as np

if TYPE_CHECKING:
    from app.core.rag_engine import PolicySource


@dataclass(frozen=True)
class PolicySnapshot:
    version: str
    sha256: str
    created_at: str
    rules: tuple[PolicySource, ...]
    patterns: Mapping[str, tuple[Any, ...]]
    vectors: Any | None


class PolicyStore:
    def __init__(self, embed_fn: Callable[[list[str]], Any | None]) -> None:
        self._embed = embed_fn
        self._lock = threading.Lock()
        self._active: PolicySnapshot | None = None
        self._staged: dict[str, PolicySnapshot] = {}
        self._history: list[str] = []

    def active(self) -> PolicySnapshot:
        with self._lock:
            if self._active is None:
                raise RuntimeError("No active policy snapshot.")
            return self._active

    def stage(self, rules: list[PolicySource], raw_sha: str, version_tag: str) -> PolicySnapshot:
        if not version_tag.strip():
            raise ValueError("A policy version is required.")
        if not rules:
            raise ValueError("A policy snapshot must contain at least one rule.")
        rule_ids = [rule.rule_id for rule in rules]
        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("Policy rule IDs must be unique.")
        with self._lock:
            if version_tag in self._staged:
                raise ValueError(f"Version {version_tag} is already staged.")
        snapshot = self._build_snapshot(rules, raw_sha, version_tag)
        with self._lock:
            if version_tag in self._staged:
                raise ValueError(f"Version {version_tag} is already staged.")
            self._staged[snapshot.version] = snapshot
        return snapshot

    def activate(self, version: str, actor: str) -> PolicySnapshot:
        del actor
        with self._lock:
            if version not in self._staged:
                raise ValueError(f"Version {version} not staged.")
            self._active = self._staged[version]
            self._history.append(version)
            return self._active

    def staged(self) -> list[PolicySnapshot]:
        with self._lock:
            return list(self._staged.values())

    def history(self) -> list[str]:
        with self._lock:
            return list(self._history)

    def _build_snapshot(
        self, rules: list[PolicySource], raw_sha: str, version_tag: str
    ) -> PolicySnapshot:
        immutable_rules = tuple(rules)
        import re

        patterns = MappingProxyType({
            rule.rule_id: tuple(
                re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)
                for term in rule.terms
            )
            for rule in immutable_rules
        })
        passages = [rule.passage for rule in immutable_rules]
        vectors = self._immutable_vectors(self._embed(passages), len(immutable_rules))
        return PolicySnapshot(
            version=version_tag,
            sha256=raw_sha,
            created_at=datetime.now(timezone.utc).isoformat(),
            rules=immutable_rules,
            patterns=patterns,
            vectors=vectors,
        )

    @staticmethod
    def _immutable_vectors(vectors: Any | None, rule_count: int) -> Any | None:
        if vectors is None:
            return None

        detach = getattr(vectors, "detach", None)
        if callable(detach):
            vectors = detach()
        cpu = getattr(vectors, "cpu", None)
        if callable(cpu):
            vectors = cpu()
        to_numpy = getattr(vectors, "numpy", None)
        if callable(to_numpy):
            vectors = to_numpy()

        array = np.asarray(vectors)
        if array.ndim != 2 or array.shape[0] != rule_count or array.shape[1] == 0:
            raise ValueError("Policy embeddings must contain one non-empty vector per rule.")
        if not np.issubdtype(array.dtype, np.number):
            raise ValueError("Policy embeddings must contain numeric values.")

        # Back the array with immutable bytes so a caller cannot re-enable writes.
        return np.frombuffer(array.tobytes(order="C"), dtype=array.dtype).reshape(array.shape)
