"""Explicit mail approval, suppression, scheduling, and conservative SMTP delivery."""
import os
import smtplib
import ssl
import time
import uuid
from email.message import EmailMessage
from .models import email, text


def draft(store, recipient, subject, body, evidence, due=None):
    recipient = email(recipient)
    subject = text(subject, "subject", 200)
    if "\r" in subject or "\n" in subject:
        raise ValueError("Mail subject cannot contain line breaks.")
    body = text(body, "body", 15000)
    evidence = text(evidence, "contact basis", 1000)
    mid = uuid.uuid4().hex
    with store.connect() as db:
        db.execute("INSERT INTO mail(id,recipient,subject,body,state,evidence,due) VALUES(?,?,?,?,?,?,?)",
                   (mid, recipient, subject, body, "draft", evidence, due or time.time()))
    return mid


def approve(store, mid):
    with store.connect() as db:
        row = db.execute("SELECT * FROM mail WHERE id=?", (mid,)).fetchone()
        if not row or row["state"] != "draft":
            raise ValueError("Only an existing draft can be approved.")
        if "[creator]" in row["body"].lower() or "[name]" in row["body"].lower():
            raise ValueError("Replace recipient placeholders before approving.")
        if db.execute("SELECT 1 FROM suppressions WHERE email=?", (row["recipient"],)).fetchone():
            raise ValueError("Recipient has opted out or already replied.")
        db.execute("UPDATE mail SET state='approved' WHERE id=?", (mid,))


def suppress(store, recipient, reason="opt-out"):
    recipient = email(recipient)
    with store.connect() as db:
        db.execute("INSERT OR REPLACE INTO suppressions VALUES(?,?)", (recipient, reason))
        db.execute("UPDATE mail SET state='cancelled' WHERE recipient=? AND state IN ('draft','approved') AND id NOT LIKE 'delivery_%'", (recipient,))


def send_one(store):
    if os.environ.get("OSA_MAIL_ENABLED") != "true":
        return None
    auth = os.environ.get('OSA_MAIL_AUTH', 'password')
    if auth not in ('password', 'microsoft'):
        raise ValueError('Unknown mail authentication method.')
    required = ("OSA_SMTP_HOST", "OSA_SMTP_USER", "OSA_FROM_EMAIL") + (() if auth == 'microsoft' else ('OSA_SMTP_PASSWORD',))
    if any(not os.environ.get(k) for k in required):
        raise ValueError("SMTP configuration is incomplete.")
    sender = email(os.environ["OSA_FROM_EMAIL"])
    oauth = None
    if auth == 'microsoft':
        from . import microsoft_auth
        microsoft_auth.validate_endpoint('smtp', os.environ['OSA_SMTP_HOST'], os.environ.get('OSA_SMTP_PORT', '587'), os.environ['OSA_SMTP_USER'])
        # Missing/revoked authorization fails before claiming a message.
        oauth = microsoft_auth.xoauth2(sender, microsoft_auth.access_token(sender, microsoft_auth.SMTP_SCOPE))
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        count = db.execute("SELECT COUNT(*) FROM mail WHERE state IN ('sending','sent','uncertain') AND sent>?", (time.time() - 86400,)).fetchone()[0]
        if count >= int(os.environ.get("OSA_MAIL_DAILY_LIMIT", "10")):
            return None
        row = db.execute("""SELECT m.* FROM mail m WHERE state='approved' AND due<=?
            AND (id LIKE 'delivery_%' OR recipient NOT IN (SELECT email FROM suppressions))
            AND NOT EXISTS (SELECT 1 FROM campaign_mail follow WHERE follow.mail_id=m.id AND follow.variant LIKE '%-followup'
                AND NOT EXISTS (SELECT 1 FROM campaign_mail first JOIN mail initial ON initial.id=first.mail_id
                    WHERE first.campaign_id=follow.campaign_id AND first.lead_id=follow.lead_id
                    AND first.variant IN ('A','B') AND initial.state='sent'))
            ORDER BY due LIMIT 1""", (time.time(),)).fetchone()
        if not row:
            return None
        # A process death after this point is 'sending', never automatically retried.
        db.execute("UPDATE mail SET state='sending',sent=? WHERE id=?", (time.time(), row["id"]))
    message = EmailMessage()
    message["From"] = sender
    message["To"] = row["recipient"]
    message["Subject"] = row["subject"]
    message["Message-ID"] = f"<{row['id']}@{sender.split('@')[1]}>"
    with store.connect() as db:
        db.execute('INSERT OR REPLACE INTO mail_headers VALUES(?,?)', (row['id'], message['Message-ID']))
    message.set_content(row["body"] + "\n\nReply to this email if you do not want further messages.")
    try:
        with smtplib.SMTP(os.environ["OSA_SMTP_HOST"], int(os.environ.get("OSA_SMTP_PORT", "587")), timeout=30) as client:
            client.starttls(context=ssl.create_default_context())
            if oauth is not None:
                client.auth('XOAUTH2', lambda challenge=None: oauth if challenge is None else '')
            else:
                client.login(os.environ["OSA_SMTP_USER"], os.environ["OSA_SMTP_PASSWORD"])
            client.send_message(message)
        state, error = "sent", None
    except Exception:
        state, error = "uncertain", "SMTP outcome uncertain; inspect provider before retrying manually."
    with store.connect() as db:
        db.execute("UPDATE mail SET state=?,error=? WHERE id=?", (state, error, row["id"]))
    return {"id": row["id"], "state": state}
