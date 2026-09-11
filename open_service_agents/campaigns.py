"""Reviewable A/B campaigns and a bounded, read-only mailbox synchronizer."""
import hashlib
import imaplib
import json
import os
import re
import ssl
import time
import uuid
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from . import mail
from .models import text, email


def create(store, data):
    name = text(data.get('name'), 'campaign name', 150)
    ids = data.get('lead_ids')
    if not isinstance(ids, list) or not 1 <= len(ids) <= 30 or len(set(ids)) != len(ids):
        raise ValueError('Select 1-30 different qualified leads.')
    subject = text(data.get('subject'), 'subject', 200)
    if '\r' in subject or '\n' in subject:
        raise ValueError('Subject cannot contain line breaks.')
    variants = {k: text(data.get('body_' + k.lower()), 'variant ' + k, 10000) for k in ('A', 'B')}
    followup = str(data.get('followup', '')).strip()
    if len(followup) > 10000:
        raise ValueError('Follow-up is too long.')
    delay = data.get('delay_hours', 72)
    if type(delay) not in (int, float) or not 24 <= delay <= 720:
        raise ValueError('Follow-up delay must be 24-720 hours.')
    cid = uuid.uuid4().hex
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        leads = []
        for lid in ids:
            row = db.execute('SELECT content FROM leads WHERE id=?', (lid,)).fetchone()
            if not row:
                raise ValueError('Unknown lead.')
            lead = json.loads(row['content'])
            if lead['status'] != 'qualified' or not lead['email'] or not lead['contact_basis']:
                raise ValueError('Each lead needs qualification, a verified address and a contact basis.')
            if db.execute('SELECT 1 FROM suppressions WHERE email=?', (lead['email'],)).fetchone():
                raise ValueError('A selected lead has replied or opted out.')
            leads.append((lid, lead))
        if len({lead['email'] for _, lead in leads}) != len(leads):
            raise ValueError('Selected leads contain duplicate recipient addresses.')
        db.execute('INSERT INTO campaigns VALUES(?,?,?)', (cid, name, time.time()))
        for index, (lid, lead) in enumerate(leads):
            variant = 'A' if index % 2 == 0 else 'B'
            def personalize(value):
                for key in ('name', 'niche'):
                    value = value.replace('{' + key + '}', lead[key])
                return value
            for number, body in enumerate([variants[variant]] + ([followup] if followup else [])):
                mid = uuid.uuid4().hex
                rendered_subject = personalize(subject)
                if '\n' in rendered_subject or '\r' in rendered_subject:
                    raise ValueError('Personalized subject contains line breaks.')
                db.execute('INSERT INTO mail(id,recipient,subject,body,state,evidence,due) VALUES(?,?,?,?,?,?,?)',
                    (mid, lead['email'], rendered_subject, personalize(body), 'draft', lead['contact_basis'], time.time() + number * delay * 3600))
                db.execute('INSERT INTO campaign_mail VALUES(?,?,?,?)', (mid, cid, variant + ('-followup' if number else ''), lid))
    return {'id': cid, 'drafts': len(ids) * (2 if followup else 1), 'state': 'requires individual review'}


def metrics(store):
    with store.connect() as db:
        campaigns = [dict(r) for r in db.execute('SELECT * FROM campaigns ORDER BY created DESC')]
        for c in campaigns:
            rows = [dict(r) for r in db.execute('''SELECT cm.variant,COUNT(*) drafted,
                SUM(CASE WHEN m.state='sent' THEN 1 ELSE 0 END) sent,
                SUM(CASE WHEN EXISTS(SELECT 1 FROM replies r WHERE r.mail_id=m.id) THEN 1 ELSE 0 END) replied,
                SUM(CASE WHEN EXISTS(SELECT 1 FROM replies r WHERE r.mail_id=m.id AND r.status='interested') THEN 1 ELSE 0 END) interested
                FROM campaign_mail cm JOIN mail m ON cm.mail_id=m.id WHERE cm.campaign_id=? GROUP BY cm.variant''', (c['id'],))]
            c['variants'] = rows
            first = [r for r in rows if r['variant'] in ('A', 'B')]
            c['recommendation'] = 'Collect at least 10 delivered initial emails per variant and review reply labels before comparing. No automatic winner.'
            if len(first) == 2 and all(r['sent'] >= 10 for r in first):
                ranked = sorted(first, key=lambda r:r['interested']/r['sent'], reverse=True)
                c['recommendation'] = 'Observed interested-reply rates: ' + ', '.join(f"{r['variant']} {r['interested']}/{r['sent']}" for r in ranked) + '. Directional only; review audience mix and increase the sample before changing a campaign.'
    return campaigns


def record_reply(store, raw, account, validity, uid):
    """Correlate both exact sender and a Message-ID actually assigned by our sender."""
    message = BytesParser(policy=policy.default).parsebytes(raw)
    sender = parseaddr(str(message.get('From', '')))[1].lower()
    references = re.findall(r'<[^<>\s]+>', str(message.get('In-Reply-To', '')) + ' ' + str(message.get('References', '')))
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM imap_seen WHERE account=? AND validity=? AND uid=?', (account, validity, uid)).fetchone():
            return False
        matches = []
        for ref in references[-30:]:
            row = db.execute('SELECT m.* FROM mail m JOIN mail_headers h ON h.mail_id=m.id WHERE h.message_id=? AND m.recipient=? AND m.state IN (\'sent\',\'sending\',\'uncertain\')', (ref, sender)).fetchone()
            if row:
                matches.append(row)
        if not matches:
            return False
        row = matches[-1]
        part = message.get_body(preferencelist=('plain',))
        try:
            body = part.get_content() if part else '[No plain-text body. Review in your mailbox.]'
        except Exception:
            body = '[Body could not be decoded. Review in your mailbox.]'
        automatic = str(message.get('Auto-Submitted', 'no')).lower() != 'no'
        rid = hashlib.sha256((account + '\0' + validity + '\0' + uid).encode()).hexdigest()
        db.execute('INSERT INTO replies VALUES(?,?,?,?,?,?,?)', (rid, row['id'], sender, str(message.get('Subject',''))[:500], str(body)[:20000], 'automatic' if automatic else 'needs-review', time.time()))
        db.execute('INSERT INTO imap_seen VALUES(?,?,?)', (account, validity, uid))
        # Stop follow-ups for any correlated reply, including automated responses.
        db.execute('INSERT OR REPLACE INTO suppressions VALUES(?,?)', (sender, 'inbox reply; human review required'))
        db.execute("UPDATE mail SET state='cancelled' WHERE recipient=? AND state IN ('draft','approved') AND id NOT LIKE 'delivery_%'", (sender,))
    return True


def sync_inbox(store):
    if os.environ.get('OSA_IMAP_ENABLED') != 'true':
        return {'enabled': False, 'imported': 0}
    host, user, password = (os.environ.get(k) for k in ('OSA_IMAP_HOST', 'OSA_IMAP_USER', 'OSA_IMAP_PASSWORD'))
    if not all((host, user, password)):
        raise ValueError('IMAP configuration is incomplete.')
    mailbox = os.environ.get('OSA_IMAP_FOLDER', 'INBOX')
    if not re.fullmatch(r'[A-Za-z0-9_ ./-]{1,100}', mailbox):
        raise ValueError('Unsupported mailbox name.')
    account = hashlib.sha256((host + '\0' + user + '\0' + mailbox).encode()).hexdigest()
    imported = 0
    with imaplib.IMAP4_SSL(host, int(os.environ.get('OSA_IMAP_PORT', '993')), ssl_context=ssl.create_default_context(), timeout=30) as client:
        client.login(user, password)
        status, _ = client.select('"' + mailbox + '"', readonly=True)
        if status != 'OK':
            raise ValueError('Cannot select mailbox read-only.')
        validity_data = client.response('UIDVALIDITY')[1]
        if not validity_data or not validity_data[0] or not validity_data[0].isdigit():
            raise ValueError('Mailbox UIDVALIDITY is unavailable.')
        validity = validity_data[0].decode()
        with store.connect() as db:
            cursor = db.execute('SELECT * FROM imap_cursor WHERE account=?', (account,)).fetchone()
        previous = cursor['uid'] if cursor and cursor['validity'] == validity else 0
        status, ids = client.uid('search', None, 'UID', f'{previous + 1}:*')
        if status != 'OK':
            raise ValueError('Mailbox search failed.')
        found = sorted({int(x) for x in (ids[0] or b'').split() if x.isdigit() and int(x) > previous})
        if not previous:
            found = found[-200:]  # Explicit bounded initial backfill.
        for uid in found[:50]:
            status, parts = client.uid('fetch', str(uid), '(BODY.PEEK[HEADER.FIELDS (FROM IN-REPLY-TO REFERENCES)])')
            if status != 'OK':
                break
            headers = b''.join(p[1] for p in parts if isinstance(p, tuple) and isinstance(p[1], bytes))
            header = BytesParser(policy=policy.default).parsebytes(headers)
            sender = parseaddr(str(header.get('From','')))[1].lower()
            refs = re.findall(r'<[^<>\s]+>', str(header.get('In-Reply-To','')) + ' ' + str(header.get('References','')))
            with store.connect() as db:
                match = any(db.execute('SELECT 1 FROM mail m JOIN mail_headers h ON m.id=h.mail_id WHERE h.message_id=? AND m.recipient=?', (r, sender)).fetchone() for r in refs[-30:])
            if match:
                status, parts = client.uid('fetch', str(uid), '(BODY.PEEK[]<0.65536>)')
                if status != 'OK':
                    break
                raw = b''.join(p[1] for p in parts if isinstance(p, tuple) and isinstance(p[1], bytes))
                imported += int(record_reply(store, raw, account, validity, str(uid)))
            with store.connect() as db:
                db.execute('INSERT INTO imap_cursor VALUES(?,?,?) ON CONFLICT(account) DO UPDATE SET validity=excluded.validity,uid=excluded.uid', (account, validity, uid))
    return {'enabled': True, 'imported': imported}
