"""Explicitly approved Route partner transfers; never a wallet or settlement guarantee."""
import base64
import json
import os
import re
import time
import uuid
from .providers import request_json


def plan(store, order_id, account):
    if not isinstance(account, str) or not re.fullmatch(r'acct_[A-Za-z0-9]{6,40}', account):
        raise ValueError('Supply the partner\'s verified Razorpay Linked Account ID.')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT o.*,l.partner_share FROM orders o JOIN ledger l ON l.order_id=o.id WHERE o.id=? AND o.state='paid'", (order_id,)).fetchone()
        if not row or row['mode'] not in ('test','live') or row['currency'] != 'INR' or row['partner_share'] < 100:
            raise ValueError('Transfers require an active test/live INR receipt with at least 100 paise accrued share.')
        if db.execute('SELECT 1 FROM transfers WHERE payment_id=?', (row['payment_id'],)).fetchone():
            raise ValueError('A transfer already exists for this payment. Inspect it before taking another action.')
        tid = uuid.uuid4().hex
        db.execute('INSERT INTO transfers VALUES(?,?,?,?,?,?,?,NULL,?,NULL)',
                   (tid,row['payment_id'],account,row['partner_share'],'INR',row['mode'],'draft',time.time()))
    return {'id':tid,'account':account,'amount':row['partner_share'],'currency':'INR','mode':row['mode'],'state':'draft'}


def approve(store, tid, amount, account):
    with store.connect() as db:
        changed = db.execute("UPDATE transfers SET state='approved' WHERE id=? AND state='draft' AND amount=? AND account=?", (tid,amount,account)).rowcount
        if changed != 1:
            raise ValueError('Transfer approval must match its exact draft amount and recipient.')
    return {'id':tid,'state':'approved'}


def send_one(store):
    if os.environ.get('OSA_ROUTE_ENABLED') != 'true':
        return None
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT * FROM transfers WHERE state='approved' ORDER BY created LIMIT 1").fetchone()
        if not row:
            return None
        receipt = db.execute("SELECT l.* FROM ledger l JOIN orders o ON o.id=l.order_id WHERE l.payment_id=? AND o.state='paid'", (row['payment_id'],)).fetchone()
        if not receipt or receipt['partner_share'] != row['amount']:
            db.execute("UPDATE transfers SET state='cancelled',error='Receipt revoked or accrued share changed' WHERE id=?", (row['id'],))
            return {'id':row['id'],'state':'cancelled'}
        key, secret = os.environ.get('RAZORPAY_KEY_ID',''),os.environ.get('RAZORPAY_KEY_SECRET','')
        if not key.startswith('rzp_'+row['mode']+'_') or not secret:
            raise ValueError('Transfer credentials do not match its payment mode.')
        if row['mode']=='live' and os.environ.get('OSA_LIVE_TRANSFERS')!='true':
            raise ValueError('Live transfers require a separate explicit enable flag.')
        db.execute("UPDATE transfers SET state='sending' WHERE id=?", (row['id'],))
    auth = base64.b64encode((key+':'+secret).encode()).decode()
    try:
        response = request_json('https://api.razorpay.com/v1/payments/'+row['payment_id']+'/transfers',
            {'transfers':[{'account':row['account'],'amount':row['amount'],'currency':'INR','on_hold':False,'notes':{'osa_transfer_id':row['id']}}]},
            {'Authorization':'Basic '+auth})
        items = response.get('items',[])
        if len(items)!=1 or items[0].get('source')!=row['payment_id'] or items[0].get('recipient')!=row['account'] or items[0].get('amount')!=row['amount'] or items[0].get('currency')!='INR' or not re.fullmatch(r'trf_[A-Za-z0-9]+',items[0].get('id','')):
            raise ValueError('Transfer response mismatch.')
        with store.connect() as db:
            active = db.execute('SELECT 1 FROM ledger WHERE payment_id=?',(row['payment_id'],)).fetchone()
            state = 'submitted' if active else 'needs-reconciliation'
            db.execute('UPDATE transfers SET state=?,provider_id=? WHERE id=?',(state,items[0]['id'],row['id']))
        return {'id':row['id'],'state':state}
    except Exception:
        with store.connect() as db:
            db.execute("UPDATE transfers SET state='uncertain',error='Inspect provider by notes.osa_transfer_id before any retry' WHERE id=?",(row['id'],))
        return {'id':row['id'],'state':'uncertain'}
