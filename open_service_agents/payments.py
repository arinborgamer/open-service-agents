"""Razorpay checkout, verified fulfillment, revocable access, and gross-share accounting."""
import base64
import hashlib
import hmac
import json
import os
import re
import time
import uuid
from .models import email, identifier
from .providers import request_json
from .exports import bundle


def secret(name):
    value = os.environ.get(name, "")
    if len(value) < 32:
        raise ValueError(f"{name} must have at least 32 characters.")
    return value


def token(order_id, ttl=604800):
    payload = f"{order_id}.{int(time.time()) + ttl}"
    signature = hmac.new(secret("OSA_DOWNLOAD_SECRET").encode(), payload.encode(), hashlib.sha256).hexdigest()
    return payload + "." + signature


def download(store, signed):
    try:
        oid, expires, signature = signed.split(".")
        expected = hmac.new(secret("OSA_DOWNLOAD_SECRET").encode(), f"{oid}.{expires}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected) or int(expires) <= time.time():
            raise ValueError("Invalid or expired download.")
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid or expired download.") from exc
    with store.connect() as db:
        row = db.execute("SELECT p.job_id,p.approved FROM orders o JOIN products p ON p.id=o.product_id WHERE o.id=? AND o.state='paid'", (oid,)).fetchone()
        if not row or not row["approved"]:
            raise ValueError("Order has no active entitlement.")
    return bundle(store.job(row["job_id"]))


def approve_product(store, job_id, pid, amount, currency="INR", partner_bps=0):
    identifier(pid)
    if type(amount) is not int or not 100 <= amount <= 100_000_000:
        raise ValueError("Amount must be an integer in minor units, from 100 to 100000000.")
    if not re.fullmatch(r"[A-Z]{3}", currency) or not 0 <= partner_bps <= 10000:
        raise ValueError("Invalid currency or partner share (basis points 0-10000).")
    job = store.job(job_id)
    if job["state"] != "ready":
        raise ValueError("Complete and review all stages first.")
    with store.connect() as db:
        # Immutable approval snapshot: new contents/prices need a new product ID.
        db.execute("INSERT INTO products VALUES(?,?,?,?,?,1)", (pid, job_id, amount, currency, partner_bps))
    return pid


def checkout(store, pid, customer_email, mode=None):
    customer_email = email(customer_email)
    mode = mode or os.environ.get("OSA_PAYMENT_MODE", "test")
    if mode not in ("demo", "test", "live"):
        raise ValueError("Invalid payment mode.")
    with store.connect() as db:
        p = db.execute("SELECT * FROM products WHERE id=? AND approved=1", (pid,)).fetchone()
    if not p:
        raise ValueError("Product is not approved.")
    if mode != "demo" and store.job(p["job_id"])["provider"] == "demo":
        raise ValueError("Demo fixtures cannot be sold through a payment provider.")
    key = os.environ.get("RAZORPAY_KEY_ID", "")
    if mode != "demo":
        if not key.startswith("rzp_" + mode + "_") or not os.environ.get("RAZORPAY_KEY_SECRET"):
            raise ValueError("Razorpay credentials missing or mode mismatch.")
        if mode == "live" and os.environ.get("OSA_LIVE_PAYMENTS") != "true":
            raise ValueError("Live payments have not been enabled.")
    oid = uuid.uuid4().hex
    with store.connect() as db:
        db.execute("INSERT INTO orders(id,product_id,email,amount,currency,state,mode,created) VALUES(?,?,?,?,?,'creating',?,?)",
                   (oid, pid, customer_email, p["amount"], p["currency"], mode, time.time()))
    try:
        if mode == "demo":
            response = {"id": "plink_demo_" + oid, "short_url": "demo://" + oid}
        else:
            auth = base64.b64encode((key + ":" + os.environ["RAZORPAY_KEY_SECRET"]).encode()).decode()
            response = request_json("https://api.razorpay.com/v1/payment_links", {
                "amount": p["amount"], "currency": p["currency"], "accept_partial": False,
                "description": pid, "reference_id": oid, "customer": {"email": customer_email},
                "notify": {"sms": False, "email": False}, "reminder_enable": False,
                "notes": {"osa_order_id": oid}}, {"Authorization": "Basic " + auth})
        with store.connect() as db:
            db.execute("UPDATE orders SET link_id=?,url=?,state='pending' WHERE id=?", (response["id"], response["short_url"], oid))
    except Exception:
        with store.connect() as db:
            db.execute("UPDATE orders SET state='uncertain' WHERE id=?", (oid,))
        raise ValueError("Checkout outcome uncertain. Inspect Razorpay by reference_id before creating another link.") from None
    return {"id": oid, "url": response["short_url"], "mode": mode}


def webhook(store, raw, signature, event_id, mode=None):
    mode = mode or os.environ.get("OSA_PAYMENT_MODE", "test")
    expected = hmac.new(secret("RAZORPAY_WEBHOOK_SECRET").encode(), raw, hashlib.sha256).hexdigest()
    if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
        raise PermissionError("Invalid webhook signature.")
    if not isinstance(event_id, str) or not event_id or len(event_id) > 200:
        raise ValueError("Missing event ID.")
    event = json.loads(raw)
    kind = event.get("event")
    payload = event.get("payload", {})
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS revoked_payments (payment_id TEXT PRIMARY KEY)")
        if db.execute("SELECT 1 FROM events WHERE id=?", (mode + ":" + event_id,)).fetchone():
            return {"status": "duplicate"}
        if kind == "payment_link.paid":
            link = payload["payment_link"]["entity"]
            payment = payload["payment"]["entity"]
            order = db.execute("SELECT o.*,p.partner_bps FROM orders o JOIN products p ON p.id=o.product_id WHERE o.link_id=?", (link["id"],)).fetchone()
            if not order or order["mode"] != mode:
                raise ValueError("Unknown order or payment-mode mismatch.")
            if (link.get("status") != "paid" or link.get("amount_paid") != order["amount"]
                    or link.get("amount") != order["amount"] or link.get("currency") != order["currency"]
                    or payment.get("status") != "captured" or payment.get("captured") is not True
                    or payment.get("amount") != order["amount"] or payment.get("currency") != order["currency"]
                    or not link.get("order_id") or payment.get("order_id") != link["order_id"]):
                raise ValueError("Payment is not a full matching captured payment.")
            if order["payment_id"] and order["payment_id"] != payment["id"]:
                raise ValueError("Order already has another payment.")
            revoked = payment.get("amount_refunded", 0) > 0 or db.execute("SELECT 1 FROM revoked_payments WHERE payment_id=?", (payment["id"],)).fetchone()
            if revoked or order["state"] == "refunded":
                db.execute("UPDATE orders SET state='refunded',payment_id=? WHERE id=?", (payment["id"], order["id"]))
                db.execute("DELETE FROM ledger WHERE payment_id=?", (payment["id"],))
                db.execute("UPDATE transfers SET state=CASE WHEN state IN ('draft','approved','cancelled') THEN 'cancelled' ELSE 'needs-reconciliation' END,error='Refund/dispute: inspect provider and reverse transfer if needed' WHERE payment_id=? AND mode=?", (payment["id"], mode))
            else:
                db.execute("UPDATE orders SET state='paid',payment_id=? WHERE id=?", (payment["id"], order["id"]))
                db.execute("INSERT OR IGNORE INTO ledger VALUES(?,?,?,?,?,?)", (payment["id"], order["id"], order["amount"], order["amount"] * order["partner_bps"] // 10000, order["currency"], mode))
                # Transactional fulfillment uses the checkout email, never an event-supplied address.
                signed = token(order["id"])
                base = os.environ.get("OSA_PUBLIC_URL", "http://127.0.0.1:8787").rstrip("/")
                if mode == "live":
                    body = f"Your product is ready. Download within seven days: {base}/download/{signed}"
                    db.execute("INSERT OR IGNORE INTO mail(id,recipient,subject,body,state,evidence,due) VALUES(?,?,?,?,?,?,?)",
                               ("delivery_" + order["id"], order["email"], "Your digital product", body, "approved", "paid order " + order["id"], time.time()))
        elif kind in ("refund.created", "refund.processed", "payment.refunded", "payment.dispute.created"):
            if kind.startswith("refund."):
                payment_id = payload["refund"]["entity"]["payment_id"]
            elif kind == "payment.dispute.created":
                payment_id = payload["dispute"]["entity"]["payment_id"]
            else:
                payment_id = payload["payment"]["entity"]["id"]
            db.execute("INSERT OR IGNORE INTO revoked_payments VALUES(?)", (payment_id,))
            # Conservative: any refund/dispute suspends download and accrued share for manual reconciliation.
            db.execute("UPDATE orders SET state='refunded' WHERE payment_id=? AND mode=?", (payment_id, mode))
            db.execute("DELETE FROM ledger WHERE payment_id=? AND mode=?", (payment_id, mode))
            db.execute("UPDATE transfers SET state=CASE WHEN state IN ('draft','approved','cancelled') THEN 'cancelled' ELSE 'needs-reconciliation' END,error='Refund/dispute: inspect provider and reverse transfer if needed' WHERE payment_id=? AND mode=?", (payment_id,mode))
        db.execute("INSERT INTO events VALUES(?,?)", (mode + ":" + event_id, time.time()))
    return {"status": "processed"}


def ledger(store):
    with store.connect() as db:
        rows = [dict(r) for r in db.execute("SELECT mode,currency,SUM(gross) gross_minor,SUM(partner_share) accrued_partner_share_minor FROM ledger GROUP BY mode,currency")]
    return {"basis": "gross receipts before fees/taxes; refunded/disputed receipts excluded; not bank settlements or a wallet", "totals": rows}
