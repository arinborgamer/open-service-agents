import argparse
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path
from . import config, models, payments, mail
from .exports import export_job, pdf_export
from .pipeline import run_one
from .providers import provider, search
from .storage import Store


def output(value):
    print(json.dumps(value, indent=2, ensure_ascii=True))


def main():
    parser = argparse.ArgumentParser(prog="osa", description="Original digital-product and creator-partnership agents.")
    parser.add_argument("--data", default=os.environ.get("OSA_DATA_DIR", ".local/data"))
    parser.add_argument("--env-file", default=".local/runtime.env")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Create private local config and random keys.")
    sub.add_parser("doctor", help="Check configuration without showing secrets.")
    outlook = sub.add_parser('outlook-connect', help='Owner-run Microsoft browser sign-in; does not send mail or enable workers.')
    outlook.add_argument('--with-inbox', action='store_true', help='Also request mailbox access for correlated reply monitoring.')
    sub.add_parser('outlook-status', help='Report configuration/cache presence, not token contents.')
    sub.add_parser('outlook-verify', help='Verify Outlook SMTP authentication without sending an email.')
    submit = sub.add_parser("submit")
    submit.add_argument("brief")
    submit.add_argument("--provider", choices=("demo", "ollama"), default="ollama")
    submit.add_argument("--key")
    worker = sub.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--interval", type=float, default=5)
    inbox_worker = sub.add_parser('mail-worker', help='Independently sync correlated replies and send approved mail.')
    inbox_worker.add_argument('--once', action='store_true')
    inbox_worker.add_argument('--interval', type=float, default=60)
    sub.add_parser('sync-inbox')
    sub.add_parser("jobs")
    inspect = sub.add_parser("show")
    inspect.add_argument("id")
    retry = sub.add_parser("retry", help="Explicitly retry a failed job, retaining completed stages.")
    retry.add_argument("id")
    export = sub.add_parser("export")
    export.add_argument("id")
    export.add_argument("--out", default=".local/exports")
    pdf = sub.add_parser("pdf")
    pdf.add_argument("id")
    pdf.add_argument("--out", default=".local/output/pdf/product.pdf")
    discover = sub.add_parser("discover")
    discover.add_argument("query")
    ask = sub.add_parser("ask")
    ask.add_argument("brief")
    ask.add_argument("question")
    ask.add_argument("--provider", choices=("demo", "ollama"), default="ollama")
    product = sub.add_parser("approve-product")
    product.add_argument("job_id")
    product.add_argument("id")
    product.add_argument("--amount", type=int, required=True, help="Minor currency units, e.g. 9900 for INR 99.")
    product.add_argument("--currency", default="INR")
    product.add_argument("--partner-bps", type=int, default=0)
    checkout = sub.add_parser("checkout")
    checkout.add_argument("id")
    checkout.add_argument("email")
    checkout.add_argument("--demo", action="store_true")
    demo = sub.add_parser("simulate-payment", help="Sign a local fixture for a DEMO order only.")
    demo.add_argument("order_id")
    delivery = sub.add_parser("delivery-link")
    delivery.add_argument("order_id")
    sub.add_parser("ledger")
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    draft = sub.add_parser("draft-mail")
    draft.add_argument("recipient")
    draft.add_argument("subject")
    draft.add_argument("body_file")
    draft.add_argument("--basis", required=True)
    draft.add_argument("--delay-hours", type=float, default=0)
    approval = sub.add_parser("approve-mail")
    approval.add_argument("id")
    sub.add_parser("mail-queue")
    reply = sub.add_parser("record-reply")
    reply.add_argument("email")
    reply.add_argument("--status", choices=("interested", "not-interested", "opt-out"), required=True)
    args = parser.parse_args()
    config.load_env(args.env_file)
    try:
        if args.command == "init":
            output({"config": config.initialize(args.env_file), "secrets": "generated privately"})
            return
        if args.command in ('outlook-connect', 'outlook-status', 'outlook-verify'):
            from . import microsoft_auth
            if args.command == 'outlook-connect':
                print('Sign in only on Microsoft\'s browser page. Review the requested permissions. No email will be sent.', flush=True)
                output(microsoft_auth.connect(args.with_inbox))
            elif args.command == 'outlook-verify':
                output(microsoft_auth.verify())
            else:
                output(microsoft_auth.status())
            return
        if args.command == "doctor":
            output({"python": sys.version.split()[0], "model": os.environ.get("OSA_MODEL", "granite4:3b"),
                    "operator_token": bool(os.environ.get("OSA_API_TOKEN")), "payment_mode": os.environ.get("OSA_PAYMENT_MODE", "test"),
                    "razorpay_configured": bool(os.environ.get("RAZORPAY_KEY_ID") and os.environ.get("RAZORPAY_KEY_SECRET")),
                    "smtp_enabled": os.environ.get("OSA_MAIL_ENABLED") == "true", "search_configured": bool(os.environ.get("BRAVE_API_KEY"))})
            return
        store = Store(args.data)
        if args.command == "submit":
            b = models.brief(json.loads(Path(args.brief).read_text(encoding="utf-8-sig")))
            output({"id": store.enqueue(b, args.provider, args.key), "provider": args.provider})
        elif args.command == "worker":
            while True:
                try:
                    jid = run_one(store)
                    sent = None  # Independent mail-worker keeps replies responsive during long model jobs.
                    if jid or sent or args.once:
                        output({"completed_job": jid, "mail": sent})
                except Exception as exc:
                    output({"error": type(exc).__name__, "detail": "Check job state and provider configuration; no fixture substitution."})
                    if args.once:
                        raise SystemExit(1)
                if args.once:
                    break
                time.sleep(max(1, args.interval))
        elif args.command in ('mail-worker', 'sync-inbox'):
            from .campaigns import sync_inbox
            from .transfers import send_one as send_transfer
            while True:
                try:
                    result = sync_inbox(store)
                    sent = mail.send_one(store) if args.command == 'mail-worker' else None
                    transfer = send_transfer(store) if args.command == 'mail-worker' else None
                    output({'inbox':result, 'mail':sent,'transfer':transfer})
                except Exception as exc:
                    output({'error':type(exc).__name__, 'detail':'Mailbox cycle failed; sending skipped. Check private configuration.'})
                    if args.command == 'sync-inbox' or args.once:
                        raise SystemExit(1)
                if args.command == 'sync-inbox' or args.once:
                    break
                time.sleep(max(10, args.interval))
        elif args.command == "jobs":
            output(store.jobs())
        elif args.command == "show":
            output(store.job(args.id))
        elif args.command == "retry":
            output({"id": store.retry(args.id), "state": "queued"})
        elif args.command == "export":
            output({"directory": export_job(store, args.id, args.out)})
        elif args.command == "pdf":
            output({"pdf": pdf_export(store, args.id, args.out)})
        elif args.command == "discover":
            output(search(args.query))
        elif args.command == "ask":
            b = models.brief(json.loads(Path(args.brief).read_text(encoding="utf-8-sig")))
            result = provider(args.provider).generate("advice", "Answer the business question from evidence. Explain unknowns and a concrete next experiment. You are an independent adviser, not Iman or another real person.", {"brief": b, "question": args.question})
            output(models.artifact(result, {s["id"] for s in b["sources"]}))
        elif args.command == "approve-product":
            output({"id": payments.approve_product(store, args.job_id, args.id, args.amount, args.currency, args.partner_bps)})
        elif args.command == "checkout":
            output(payments.checkout(store, args.id, args.email, "demo" if args.demo else None))
        elif args.command == "simulate-payment":
            with store.connect() as db:
                order = db.execute("SELECT * FROM orders WHERE id=? AND mode='demo'", (args.order_id,)).fetchone()
            if not order:
                raise ValueError("Simulation accepts only demo orders.")
            payment = {"id": "pay_demo_" + order["id"], "order_id": "order_demo_" + order["id"], "amount": order["amount"], "currency": order["currency"], "captured": True, "status": "captured", "amount_refunded": 0}
            link = {"id": order["link_id"], "order_id": payment["order_id"], "amount": order["amount"], "amount_paid": order["amount"], "currency": order["currency"], "status": "paid"}
            raw = json.dumps({"event": "payment_link.paid", "payload": {"payment_link": {"entity": link}, "payment": {"entity": payment}}}).encode()
            sig = hmac.new(payments.secret("RAZORPAY_WEBHOOK_SECRET").encode(), raw, hashlib.sha256).hexdigest()
            output(payments.webhook(store, raw, sig, "event_demo_" + order["id"], "demo"))
        elif args.command == "delivery-link":
            signed = payments.token(args.order_id)
            payments.download(store, signed)  # Fail if unpaid, refunded, or unapproved.
            output({"url": os.environ.get("OSA_PUBLIC_URL", "http://127.0.0.1:8787").rstrip("/") + "/download/" + signed})
        elif args.command == "ledger":
            output(payments.ledger(store))
        elif args.command == "draft-mail":
            output({"id": mail.draft(store, args.recipient, args.subject, Path(args.body_file).read_text(encoding="utf-8-sig"), args.basis, time.time() + args.delay_hours * 3600)})
        elif args.command == "approve-mail":
            mail.approve(store, args.id)
            output({"id": args.id, "state": "approved"})
        elif args.command == "mail-queue":
            with store.connect() as db:
                output([dict(r) for r in db.execute("SELECT * FROM mail ORDER BY due LIMIT 100")])
        elif args.command == "record-reply":
            mail.suppress(store, args.email, args.status)
            output({"recipient": args.email, "followups": "stopped", "status": args.status})
        elif args.command == "serve":
            from .server import make_server
            server = make_server(store, args.host, args.port)
            print(f"Open Service Agents API on {args.host}:{args.port}", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return
    except (ValueError, FileExistsError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
