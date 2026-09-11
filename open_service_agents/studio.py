"""Operator-only dashboard operations, sharing the CLI's durable state."""
import json
import os
import time
import uuid
from . import campaigns, discovery, mail, models, payments, storefront, transfers
from .providers import provider, search


def rows(store, sql, args=()):
    with store.connect() as db:
        return [dict(r) for r in db.execute(sql, args)]


def get(store, path):
    if path == '/v1/overview':
        return {'jobs': store.jobs(), 'ledger': payments.ledger(store), 'configuration': {
            'model': os.environ.get('OSA_MODEL','granite4:3b'), 'payment_mode': os.environ.get('OSA_PAYMENT_MODE','test'),
            'payments': bool(os.environ.get('RAZORPAY_KEY_ID')), 'mail': os.environ.get('OSA_MAIL_ENABLED') == 'true',
            'inbox': os.environ.get('OSA_IMAP_ENABLED') == 'true', 'search': bool(os.environ.get('BRAVE_API_KEY')),
            'youtube': bool(os.environ.get('OSA_YOUTUBE_API_KEY'))}}
    if path == '/v1/leads':
        return [{'id': r['id'], **json.loads(r['content'])} for r in rows(store, 'SELECT * FROM leads ORDER BY updated DESC LIMIT 300')]
    if path == '/v1/research':
        return [{'id': r['id'], **json.loads(r['content'])} for r in rows(store, 'SELECT * FROM research ORDER BY created DESC LIMIT 100')]
    if path == '/v1/campaigns':
        return campaigns.metrics(store)
    if path == '/v1/mail':
        return rows(store, 'SELECT m.*,cm.campaign_id,cm.variant FROM mail m LEFT JOIN campaign_mail cm ON cm.mail_id=m.id ORDER BY m.due DESC LIMIT 300')
    if path == '/v1/replies':
        return rows(store, 'SELECT * FROM replies ORDER BY created DESC LIMIT 200')
    if path == '/v1/products':
        return rows(store, 'SELECT p.*,s.published FROM products p LEFT JOIN storefronts s ON s.product_id=p.id')
    if path == '/v1/storefronts':
        return [{**r, 'content': json.loads(r['content'])} for r in rows(store, 'SELECT * FROM storefronts')]
    if path == '/v1/orders':
        return rows(store, 'SELECT id,product_id,email,amount,currency,state,mode,created FROM orders ORDER BY created DESC LIMIT 300')
    if path == '/v1/analytics':
        return {'page_requests': rows(store, 'SELECT product_id,page,SUM(count) requests FROM visits GROUP BY product_id,page'),
                'orders': rows(store, 'SELECT product_id,mode,state,COUNT(*) orders,SUM(amount) amount_minor,currency FROM orders GROUP BY product_id,mode,state,currency'),
                'note': 'Page requests include repeats and bots. Orders are not net settlements. No visitors are individually tracked.'}
    if path == '/v1/advisor':
        return [{**r, 'answer': json.loads(r['answer'])} for r in rows(store, 'SELECT * FROM advisor ORDER BY created DESC LIMIT 50')]
    if path == '/v1/transfers':
        return rows(store, 'SELECT * FROM transfers ORDER BY created DESC LIMIT 200')
    raise KeyError(path)


def post(store, path, data):
    if path == '/v1/transfers/plan':
        return transfers.plan(store, data['order_id'], data['account'])
    if path == '/v1/transfers/approve':
        return transfers.approve(store, data['id'], data['amount'], data['account'])
    if path == '/v1/leads':
        return discovery.save_lead(store, data)
    if path == '/v1/discover':
        return discovery.discover_creators(data.get('query'), data.get('source','brave'))
    if path == '/v1/research/search':
        return search(models.text(data.get('query'), 'query', 300))
    if path in ('/v1/research/fetch','/v1/research/youtube'):
        reader = discovery.read_youtube if path.endswith('/youtube') else discovery.read_source
        result = reader(data.get('url'), data.get('rights','public_reference'))
        rid = uuid.uuid4().hex
        with store.connect() as db:
            db.execute('INSERT INTO research VALUES(?,?,?)', (rid, json.dumps(result), time.time()))
        return {'id': rid, **result}
    if path == '/v1/research/save':
        clean = models.brief({'id':'source','topic':'source','audience':'research','problem':'reference','sources':[data]})['sources'][0]
        clean.pop('id', None)
        rid = uuid.uuid4().hex
        with store.connect() as db:
            db.execute('INSERT INTO research VALUES(?,?,?)', (rid, json.dumps(clean), time.time()))
        return {'id': rid, **clean}
    if path == '/v1/artifacts/edit':
        return store.edit_artifact(data['job_id'], data['stage'], data['artifact'])
    if path == '/v1/jobs/retry':
        return {'id': store.retry(data['id'])}
    if path == '/v1/campaigns':
        return campaigns.create(store, data)
    if path == '/v1/mail/approve':
        mail.approve(store, data['id'])
        return {'state':'approved'}
    if path == '/v1/mail/cancel':
        with store.connect() as db:
            changed = db.execute("UPDATE mail SET state='cancelled' WHERE id=? AND state IN ('draft','approved')", (data['id'],)).rowcount
            if changed != 1:
                raise ValueError('Only a draft or approved unsent message can be cancelled.')
        return {'state':'cancelled'}
    if path == '/v1/mail/edit':
        body = models.text(data.get('body'), 'message body', 15000)
        subject = models.text(data.get('subject'), 'subject', 200)
        if '\n' in subject or '\r' in subject:
            raise ValueError('Subject cannot contain line breaks.')
        with store.connect() as db:
            if db.execute("UPDATE mail SET subject=?,body=? WHERE id=? AND state='draft'", (subject, body, data['id'])).rowcount != 1:
                raise ValueError('Only unapproved drafts can be edited.')
        return {'state':'draft'}
    if path == '/v1/inbox/sync':
        return campaigns.sync_inbox(store)
    if path == '/v1/replies/label':
        if data.get('status') not in ('interested','not-interested','opt-out','automatic'):
            raise ValueError('Unknown reply label.')
        with store.connect() as db:
            if db.execute('UPDATE replies SET status=? WHERE id=?', (data['status'],data['id'])).rowcount != 1:
                raise ValueError('Unknown reply.')
        return {'status':data['status']}
    if path == '/v1/suppress':
        mail.suppress(store, data['email'], 'operator opt-out')
        return {'state':'suppressed'}
    if path == '/v1/storefronts':
        return storefront.configure(store, data)
    if path == '/v1/advisor':
        job = store.job(data['job_id'])
        question = models.text(data.get('question'), 'question', 2000)
        response = provider(data.get('provider','ollama')).generate('advice',
            'Answer the business question based on the supplied evidence and draft. Distinguish facts from hypotheses. Give a next experiment, not earnings promises. Never impersonate a real person.',
            {'brief':job['brief'], 'question':question, 'draft_titles':{k:v['title'] for k,v in job['artifacts'].items()}})
        answer = models.artifact(response, {s['id'] for s in job['brief']['sources']})
        rid = uuid.uuid4().hex
        with store.connect() as db:
            db.execute('INSERT INTO advisor VALUES(?,?,?,?,?)', (rid,job['id'],question,json.dumps(answer),time.time()))
        return {'id':rid,'answer':answer}
    raise KeyError(path)
