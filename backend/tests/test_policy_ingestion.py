import hashlib
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from app.core.policy_ingestion import PolicyValidationError, parse_policy_file
from app.core.rag_engine import PolicySource, RagEngine
from app.core.policy_store import PolicyStore


class TestPolicyIngestion(unittest.TestCase):
    def test_parses_json_csv_and_markdown(self):
        examples = (
            (
                "rules.json",
                b'[{"rule_id":"R-1","section":"S1","passage":"Avoid claims.","kind":"violation","terms":["best","number one"]}]',
            ),
            (
                "rules.csv",
                b"rule_id,section,passage,kind,terms\nR-1,S1,Avoid claims.,violation,best|number one\n",
            ),
            (
                "rules.md",
                b"| rule_id | section | passage | kind | terms |\n| --- | --- | --- | --- | --- |\n| R-1 | S1 | Avoid claims. | violation | best; number one |\n",
            ),
        )
        for filename, raw in examples:
            with self.subTest(filename=filename):
                rules = parse_policy_file(filename, raw)
                self.assertEqual(rules[0].rule_id, "R-1")
                self.assertEqual(rules[0].terms, ("best", "number one"))

    def test_rejects_missing_terms_and_invalid_dates(self):
        with self.assertRaises(PolicyValidationError):
            parse_policy_file(
                "rules.json",
                b'[{"rule_id":"R-1","section":"S1","passage":"Avoid claims.","kind":"violation"}]',
            )
        with self.assertRaises(PolicyValidationError):
            parse_policy_file(
                "rules.json",
                b'[{"rule_id":"R-1","section":"S1","passage":"Avoid claims.","kind":"violation","terms":["best"],"expiry_date":"tomorrow"}]',
            )

    def test_policy_store_stages_away_from_active_and_swaps_atomically(self):
        store = PolicyStore(lambda _passages: None)
        original = PolicySource("R-1", "S1", "Avoid best.", None, "violation", ("best",))
        replacement = PolicySource("R-2", "S2", "Avoid amazing.", None, "violation", ("amazing",))
        first = store.stage([original], hashlib.sha256(b"one").hexdigest(), "one")
        store.activate(first.version, "test")
        staged = store.stage([replacement], hashlib.sha256(b"two").hexdigest(), "two")

        self.assertIs(store.active(), first)
        self.assertEqual(staged.rules, (replacement,))
        self.assertIs(store.activate("two", "test"), staged)
        self.assertIs(store.active(), staged)
        self.assertEqual(store.history(), ["one", "two"])

    def test_snapshot_vectors_are_detached_and_immutable(self):
        source_vectors = np.array([[0.25, 0.75]], dtype=np.float32)
        store = PolicyStore(lambda _passages: source_vectors)
        rule = PolicySource("R-1", "S1", "Avoid best.", None, "violation", ("best",))

        snapshot = store.stage([rule], hashlib.sha256(b"vectors").hexdigest(), "vectors")
        source_vectors[0, 0] = 9.0

        self.assertEqual(float(snapshot.vectors[0, 0]), 0.25)
        with self.assertRaises(ValueError):
            snapshot.vectors[0, 0] = 1.0
        with self.assertRaises(ValueError):
            snapshot.vectors.setflags(write=True)

    def test_embedding_runs_without_blocking_active_snapshot_reads(self):
        embedding_started = threading.Event()
        allow_embedding_to_finish = threading.Event()
        should_block = threading.Event()

        def embed(_passages):
            if should_block.is_set():
                embedding_started.set()
                if not allow_embedding_to_finish.wait(timeout=5):
                    raise TimeoutError("Test embedding was not released.")
            return None

        store = PolicyStore(embed)
        first_rule = PolicySource("R-1", "S1", "Avoid best.", None, "violation", ("best",))
        next_rule = PolicySource("R-2", "S2", "Avoid amazing.", None, "violation", ("amazing",))
        active = store.stage([first_rule], hashlib.sha256(b"first").hexdigest(), "first")
        store.activate(active.version, "test")
        should_block.set()

        with ThreadPoolExecutor(max_workers=2) as executor:
            staging = executor.submit(
                store.stage,
                [next_rule],
                hashlib.sha256(b"next").hexdigest(),
                "next",
            )
            try:
                self.assertTrue(embedding_started.wait(timeout=2))
                active_read = executor.submit(store.active)
                self.assertIs(active_read.result(timeout=1), active)
            finally:
                allow_embedding_to_finish.set()

            staged = staging.result(timeout=2)

        self.assertEqual(staged.version, "next")
        self.assertIs(store.active(), active)

    def test_engine_uses_active_snapshot_for_review(self):
        engine = RagEngine(enable_embeddings=False)
        engine.warm()
        rule = PolicySource("CUSTOM-1", "Custom", "Avoid the phrase amazing.", None, "violation", ("amazing",))
        snapshot = engine.stage_policy([rule], hashlib.sha256(b"custom").hexdigest(), "custom-1")
        self.assertEqual(engine.review("This is amazing.")["trace"]["policy_version"], "builtin-1")
        engine.activate_policy(snapshot.version, "test-user")
        result = engine.review("This is amazing.")
        self.assertEqual(result["trace"]["policy_version"], "custom-1")
        self.assertEqual(result["grounded"][0]["rule_id"], "CUSTOM-1")


if __name__ == "__main__":
    unittest.main()
