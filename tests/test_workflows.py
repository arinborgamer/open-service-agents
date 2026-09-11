import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
import zipfile
from unittest.mock import patch
from open_service_agents import models, payments, mail
from open_service_agents.storage import Store
from open_service_agents.pipeline import run_one, STAGES
from open_service_agents.exports import bundle, export_job
from open_service_agents.server import make_server
from open_service_agents.providers import Ollama


class Workflows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.env = patch.dict(os.environ, {"OSA_API_TOKEN": "a" * 48, "OSA_DOWNLOAD_SECRET": "d" * 48,
            "RAZORPAY_WEBHOOK_SECRET": "w" * 48, "OSA_MAIL_ENABLED": "false", "OSA_PAYMENT_MODE": "test"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.brief = models.brief(json.loads((Path(__file__).resolve().parents[1] / "examples/brief.json").read_text()))

    def ready(self):
        jid = self.store.enqueue(self.brief, "demo")
        self.assertEqual(run_one(self.store), jid)
        return jid

    def order(self, mode="demo"):
        jid = self.ready()
        payments.approve_product(self.store, jid, "guide", 9900, "INR", 3000)
        order = payments.checkout(self.store, "guide", "buyer@example.com", "demo")
        if mode != "demo":
            with self.store.connect() as db:
                db.execute("UPDATE orders SET mode=? WHERE id=?", (mode, order["id"]))
        return order

    def payload(self, order):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM orders WHERE id=?", (order["id"],)).fetchone()
        return {"event": "payment_link.paid", "payload": {
            "payment_link": {"entity": {"id": row["link_id"], "order_id": "order_1", "status": "paid", "amount": 9900, "amount_paid": 9900, "currency": "INR"}},
            "payment": {"entity": {"id": "pay_1", "order_id": "order_1", "status": "captured", "captured": True, "amount": 9900, "currency": "INR", "amount_refunded": 0}}}}

    def event(self, payload, eid="event_1", mode="demo"):
        raw = json.dumps(payload).encode()
        sig = hmac.new(b"w" * 48, raw, hashlib.sha256).hexdigest()
        return payments.webhook(self.store, raw, sig, eid, mode)

    def test_pipeline_exports_all_stages_and_excludes_private_context(self):
        jid = self.ready()
        job = self.store.job(jid)
        self.assertEqual(job["state"], "ready")
        self.assertEqual(set(job["artifacts"]), set(STAGES))
        z = zipfile.ZipFile(io.BytesIO(bundle(job)))
        self.assertEqual(set(z.namelist()), {"product.md", "product.html", "README.txt"})
        self.assertIn(b"DEMO FIXTURE", z.read("product.md"))
        self.assertNotIn(b"audience_notes", z.read("product.md"))
        export_job(self.store, jid, Path(self.tmp.name) / "exports")
        self.assertTrue((Path(self.tmp.name) / "exports/funnel-brief.zip").exists())

    def test_idempotent_enqueue_and_conflicting_key(self):
        a = self.store.enqueue(self.brief, "demo", "key")
        self.assertEqual(a, self.store.enqueue(self.brief, "demo", "key"))
        with self.assertRaises(ValueError):
            self.store.enqueue({**self.brief, "topic": "Different"}, "demo", "key")

    def test_checkpoint_resume_does_not_regenerate_finished_stage(self):
        jid = self.store.enqueue(self.brief, "demo")
        claimed = self.store.claim()
        saved = {"title": "Saved", "body": "Checkpoint", "citations": ["S1"]}
        self.store.save_artifact(claimed, "opportunity", saved)
        with self.store.connect() as db:
            db.execute("UPDATE jobs SET lease_until=0 WHERE id=?", (jid,))
        run_one(self.store)
        self.assertEqual(self.store.job(jid)["artifacts"]["opportunity"], saved)

    def test_concurrent_claim_single_owner(self):
        self.store.enqueue(self.brief, "demo")
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.store.claim())) for _ in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(sum(r is not None for r in results), 1)

    def test_stale_worker_cannot_write(self):
        jid = self.store.enqueue(self.brief, "demo")
        old = self.store.claim()
        with self.store.connect() as db:
            db.execute("UPDATE jobs SET lease_until=0 WHERE id=?", (jid,))
        self.store.claim()
        with self.assertRaises(RuntimeError):
            self.store.save_artifact(old, "opportunity", {})

    def test_retry_budget_terminates(self):
        jid = self.store.enqueue(self.brief, "demo")
        with patch("open_service_agents.pipeline.provider", side_effect=ValueError("private secret")):
            for _ in range(3):
                with self.assertRaises(ValueError): run_one(self.store)
                with self.store.connect() as db: db.execute("UPDATE jobs SET available=0")
        job = self.store.job(jid)
        self.assertEqual(job["state"], "failed")
        self.assertNotIn("private secret", job["error"])

    def test_only_known_citations_and_bounded_briefs(self):
        with self.assertRaises(ValueError): models.artifact({"title": "x", "body": "y", "citations": ["S999"]}, {"S1"})
        with self.assertRaises(ValueError): models.identifier("../../wallet")
        with self.assertRaises(ValueError): models.brief({**self.brief, "sources": []})

    def test_explicit_retry_only_failed_jobs_preserves_checkpoints(self):
        jid = self.store.enqueue(self.brief, "demo")
        with self.assertRaises(ValueError): self.store.retry(jid)
        claimed = self.store.claim()
        self.store.save_artifact(claimed, "opportunity", {"title": "Saved", "body": "Original", "citations": ["S1"]})
        with self.assertRaises(ValueError): self.store.retry(jid)
        with self.store.connect() as db:
            db.execute("UPDATE jobs SET state='failed',attempts=3 WHERE id=?", (jid,))
        self.store.retry(jid)
        self.assertEqual(self.store.job(jid)["attempts"], 0)
        run_one(self.store)
        self.assertEqual(self.store.job(jid)["artifacts"]["opportunity"]["title"], "Saved")
        with self.assertRaises(ValueError): self.store.retry(jid)

    def test_payment_delivery_idempotence_and_gross_share(self):
        order = self.order()
        signed = payments.token(order["id"])
        with self.assertRaises(ValueError): payments.download(self.store, signed)
        p = self.payload(order)
        self.assertEqual(self.event(p)["status"], "processed")
        self.assertEqual(self.event(p)["status"], "duplicate")
        self.event(p, "retry-other-id")
        self.assertTrue(payments.download(self.store, signed).startswith(b"PK"))
        totals = payments.ledger(self.store)["totals"]
        self.assertEqual(totals, [{"mode": "demo", "currency": "INR", "gross_minor": 9900, "accrued_partner_share_minor": 2970}])

    def test_forged_webhook_and_wrong_mode(self):
        order = self.order()
        with self.assertRaises(PermissionError): payments.webhook(self.store, b"{}", "0" * 64, "e", "demo")
        with self.assertRaises(ValueError): self.event(self.payload(order), mode="live")

    def test_amount_currency_capture_and_order_mismatch(self):
        order = self.order()
        for field, value in (("amount", 1), ("currency", "USD"), ("captured", False), ("order_id", "other")):
            p = self.payload(order)
            p["payload"]["payment"]["entity"][field] = value
            with self.assertRaises(ValueError): self.event(p)
        self.assertEqual(payments.ledger(self.store)["totals"], [])

    def test_refund_revokes_download_and_share(self):
        order = self.order()
        self.event(self.payload(order))
        self.event({"event": "refund.processed", "payload": {"refund": {"entity": {"payment_id": "pay_1"}}}}, "refund_1")
        with self.assertRaises(ValueError): payments.download(self.store, payments.token(order["id"]))
        self.assertEqual(payments.ledger(self.store)["totals"], [])
        self.event(self.payload(order), "late_paid")
        with self.assertRaises(ValueError): payments.download(self.store, payments.token(order["id"]))

    def test_refund_before_paid_is_not_overridden(self):
        order = self.order()
        self.event({"event": "refund.created", "payload": {"refund": {"entity": {"payment_id": "pay_1"}}}}, "refund_first")
        self.event(self.payload(order))
        with self.assertRaises(ValueError): payments.download(self.store, payments.token(order["id"]))
        self.assertEqual(payments.ledger(self.store)["totals"], [])

    def test_token_expiry_and_tampering(self):
        order = self.order()
        self.event(self.payload(order))
        with self.assertRaises(ValueError): payments.download(self.store, payments.token(order["id"], -1))
        with self.assertRaises(ValueError): payments.download(self.store, payments.token(order["id"]) + "x")

    def test_demo_cannot_be_sold(self):
        self.order()
        with self.assertRaises(ValueError): payments.checkout(self.store, "guide", "buyer@example.com", "live")

    def test_mail_optout_stops_scheduled_followups(self):
        mid = mail.draft(self.store, "person@example.com", "Hello", "Original specific proposal.", "requested information")
        mail.approve(self.store, mid)
        mail.suppress(self.store, "person@example.com", "not-interested")
        self.assertIsNone(mail.send_one(self.store))
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT state FROM mail WHERE id=?", (mid,)).fetchone()[0], "cancelled")

    def test_smtp_requires_explicit_configuration(self):
        mail.draft(self.store, "person@example.com", "Hello", "Body", "asked for information")
        with patch("smtplib.SMTP") as smtp:
            self.assertIsNone(mail.send_one(self.store))
            smtp.assert_not_called()

    def test_mail_header_injection_rejected(self):
        with self.assertRaises(ValueError): mail.draft(self.store, "person@example.com", "Hello\nBcc:bad@example.com", "Body", "basis")

    def test_ollama_truncation_never_becomes_success(self):
        with patch("open_service_agents.providers.request_json", return_value={"done_reason": "length", "message": {"content": "{}"}}):
            with self.assertRaises(ValueError): Ollama().generate("a", "b", {"brief": self.brief})

    def test_ollama_schema_requires_citations_from_supplied_sources(self):
        response = {"done_reason": "stop", "message": {"content": json.dumps({
            "title": "Section", "body": "Original draft", "citations": ["S1"]})}}
        with patch("open_service_agents.providers.request_json", return_value=response) as request:
            Ollama().generate("chapter_1", "Write section", {"brief": self.brief})
        schema = request.call_args.args[1]["format"]
        self.assertIsInstance(schema, dict)
        self.assertIn("citations", schema["required"])
        self.assertEqual(schema["properties"]["citations"]["items"]["enum"], ["S1"])
        self.assertEqual(schema["properties"]["citations"]["minItems"], 1)
        # A captured real response omitted citations. Never fill them in silently.
        with self.assertRaises(ValueError):
            models.artifact({"title": "Section", "body": "Original draft"}, {"S1"})

    def test_http_auth_and_async_submit(self):
        server = make_server(self.store, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = "http://127.0.0.1:" + str(server.server_port)
        self.assertEqual(json.load(urllib.request.urlopen(base + "/health"))["status"], "ok")
        with self.assertRaises(urllib.error.HTTPError) as e: urllib.request.urlopen(base + "/v1/jobs")
        self.assertEqual(e.exception.code, 401)
        req = urllib.request.Request(base + "/v1/jobs", data=json.dumps({"brief": self.brief, "provider": "demo"}).encode(), headers={"Authorization": "Bearer " + "a" * 48, "Content-Type": "application/json"})
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status, 202)
            self.assertIn("id", json.load(response))


if __name__ == "__main__":
    unittest.main()
