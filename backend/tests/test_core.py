import unittest
from datetime import date
from app.core.rag_engine import RagEngine
from app.core.audit_ledger import AuditLedger
from app.core.workflow import Workflow, WorkflowTransitionError

class TestCoreSuite(unittest.TestCase):
    def setUp(self):
        self.engine = RagEngine(enable_embeddings=False)
        self.engine.warm()

    def test_expired_and_superlative_both_trigger(self):
        text = "Our product uses 80% recycled packaging and is the best choice."
        res = self.engine.review(text, today=date(2026, 6, 1))
        ids = [f["rule_id"] for f in res["grounded"]]
        self.assertIn("CP-2.1-2025", ids)
        self.assertIn("VG-01", ids)
        self.assertEqual(res["grounded"][0]["rule_id"], "CP-2.1-2025")

    def test_unsupported_claim_routes_to_legal(self):
        res = self.engine.review("Customers reduce transfer costs by 40%.")
        self.assertEqual(len(res["human_review"]), 1)
        self.assertEqual(res["human_review"][0]["route_to"], "LEGAL")

    def test_whole_word_matching(self):
        res = self.engine.review("We bestow awards to users.")
        self.assertEqual(len(res["grounded"]), 0)

    def test_ledger_hmac_and_midchain_tamper(self):
        ledger = AuditLedger()
        for i in range(5):
            ledger.append(f"EV_{i}", "SYSTEM", {"i": i})
        self.assertTrue(ledger.verify()["valid"])
        tamper = ledger.simulate_tamper()
        self.assertFalse(tamper["after"]["valid"])
        self.assertIn("broken", tamper["after"]["statuses"])
        self.assertTrue(ledger.verify()["valid"])

    def test_workflow_reopen_after_approval(self):
        wf = Workflow()
        wf.transition("review", "CREATOR")
        wf.transition("send_for_approval", "CREATOR", needs_legal=False)
        wf.transition("approve", "MANAGER")
        self.assertEqual(wf.state.value, "APPROVED")
        wf.transition("review", "CREATOR")
        self.assertEqual(wf.state.value, "REVIEWED")

if __name__ == "__main__":
    unittest.main()
