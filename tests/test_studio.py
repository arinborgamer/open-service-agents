import io
import hashlib
import hmac
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
import zipfile
from unittest.mock import patch
from open_service_agents import campaigns, discovery, models, payments, storefront, studio, transfers, mail
from open_service_agents.storage import Store
from open_service_agents.pipeline import run_one
from open_service_agents.exports import manuscript
from open_service_agents.server import make_server


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name)
        env=patch.dict(os.environ,{'OSA_API_TOKEN':'a'*48,'OSA_DOWNLOAD_SECRET':'d'*48,
            'RAZORPAY_WEBHOOK_SECRET':'w'*48,'OSA_PAYMENT_MODE':'test','OSA_MAIL_ENABLED':'false',
            'OSA_IMAP_ENABLED':'false','OSA_ROUTE_ENABLED':'false','OSA_LIVE_TRANSFERS':'false'})
        env.start();self.addCleanup(env.stop)
        self.brief=models.brief(json.loads((Path(__file__).resolve().parents[1]/'examples/brief.json').read_text()))

    def ready(self,count=6):
        b={**self.brief,'chapter_count':count}
        jid=self.store.enqueue(b,'demo');run_one(self.store)
        return jid

    def lead(self,n=1,qualified=True):
        return discovery.save_lead(self.store,{'name':f'Creator {n}','profile_url':f'https://example.com/{n}',
            'niche':'Publishing','audience_notes':'Supplied original notes.','email':f'creator{n}@example.com',
            'status':'qualified' if qualified else 'review','contact_basis':'Requested a sample' if qualified else ''})

    def campaign(self):
        leads=[self.lead(1),self.lead(2)]
        return campaigns.create(self.store,{'name':'Test','lead_ids':[l['id'] for l in leads],
            'subject':'A resource for {name}','body_a':'Hello {name}, an idea about {niche}.',
            'body_b':'Hello {name}, may I share a sample?','followup':'A brief follow-up.','delay_hours':72})

    def page(self,publish=True):
        jid=self.ready();payments.approve_product(self.store,jid,'guide',9900,'INR',3000)
        data={'product_id':'guide','headline':'<script>alert(1)</script>','description':'An original example',
            'sample':'A safe sample','support_email':'support@example.com','seller_name':'Example',
            'refund_policy':'Test only','terms':'Not for sale','blocks':[{'heading':'First','body':'<img onerror=alert(1)>'}],
            'published':publish,'reviewed':True}
        storefront.configure(self.store,data)
        return jid,data

    def paid(self):
        jid,_=self.page()
        with self.store.connect() as db:
            db.execute("UPDATE jobs SET provider='ollama' WHERE id=?",(jid,))
            db.execute("INSERT INTO orders(id,product_id,email,amount,currency,state,mode,payment_id,created) VALUES('order1','guide','buyer@example.com',9900,'INR','paid','test','pay_fixture',?)",(time.time(),))
            db.execute("INSERT INTO ledger VALUES('pay_fixture','order1',9900,2970,'INR','test')")

    def test_long_draft_exports_all_chapters_and_schema_survives_reopen(self):
        jid=self.ready(12)
        job=Store(self.tmp.name).job(jid)
        self.assertEqual(len(job['artifacts']),19)
        self.assertIn('Chapter 12',manuscript(job))
        with self.assertRaises(ValueError):models.brief({**self.brief,'chapter_count':13})

    def test_draft_edits_keep_history_and_approval_freezes_contents(self):
        jid=self.ready()
        changed={'title':'Revised title','body':'Original revised body','citations':['S1']}
        self.store.edit_artifact(jid,'chapter_1',changed)
        self.assertEqual(len(studio.rows(self.store,'SELECT * FROM edits')),1)
        payments.approve_product(self.store,jid,'guide',100)
        with self.assertRaises(ValueError):self.store.edit_artifact(jid,'chapter_1',changed)

    def test_private_networks_and_mixed_dns_answers_rejected(self):
        for address in ('127.0.0.1','10.0.0.1','169.254.169.254','::1','fc00::1','192.168.1.5'):
            with patch('socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',(address,443))]):
                with self.assertRaises(ValueError):discovery.public_addresses('source.example',443)
        with self.assertRaises(ValueError):discovery.public_url('http://user:password@example.com')
        with self.assertRaises(ValueError):discovery.public_url('http://example.com:8787')

    def test_robots_disallow_and_page_redirect_do_not_import(self):
        with patch('open_service_agents.discovery.fetch',return_value=(200,'text/plain',b'User-agent: *\nDisallow: /','https://example.com/robots.txt')) as request:
            with self.assertRaises(ValueError):discovery.read_source('https://example.com/article')
            self.assertEqual(request.call_count,1)
        with patch('open_service_agents.discovery.fetch',side_effect=[(404,'text/plain',b'',''),(302,'text/html',b'','https://other.example/article')]) as request:
            with self.assertRaises(ValueError):discovery.read_source('https://example.com/article')
            self.assertEqual(request.call_args.kwargs,{'follow_redirects':False})

    def test_source_extraction_excludes_scripts_and_labels_truncation(self):
        body=b'<title>Evidence</title><script>unsafe()</script><article>'+b'word '*1500+b'</article>'
        with patch('open_service_agents.discovery.fetch',side_effect=[(404,'text/plain',b'',''),(200,'text/html',body,'https://example.com/article')]):
            result=discovery.read_source('https://example.com/article')
        self.assertEqual(result['title'],'Evidence');self.assertTrue(result['truncated'])
        self.assertNotIn('unsafe',result['text']);self.assertEqual(len(result['text']),5000)

    def test_youtube_adapter_never_invents_emails(self):
        with patch.dict(os.environ,{'OSA_YOUTUBE_API_KEY':'fixture'}),patch('open_service_agents.discovery.request_json',side_effect=[
                {'items':[{'id':{'channelId':'UC_test'}}]}, {'items':[{'id':'UC_test','snippet':{'title':'Creator','description':'Original description'},'statistics':{'subscriberCount':'12000'}}]}]):
            result=discovery.discover_creators('publishing','youtube')
        self.assertIsNone(result[0]['email']);self.assertEqual(result[0]['statistics']['subscriberCount'],'12000')

    def test_campaign_requires_qualified_contacts_and_creates_only_drafts(self):
        c=self.campaign();rows=studio.get(self.store,'/v1/mail')
        self.assertEqual(len(rows),4);self.assertEqual({r['state'] for r in rows},{'draft'})
        self.assertNotIn('{name}',rows[0]['body'])
        self.assertEqual({r['variant'] for r in rows},{'A','B','A-followup','B-followup'})
        lead=self.lead(3,False)
        with self.assertRaises(ValueError):campaigns.create(self.store,{'name':'x','lead_ids':[lead['id']],'subject':'Hello','body_a':'A','body_b':'B'})

    def test_correlated_reply_suppresses_followups_but_not_paid_delivery(self):
        self.campaign();rows=studio.get(self.store,'/v1/mail');sent=next(r for r in rows if r['variant']=='A')
        with self.store.connect() as db:
            db.execute("UPDATE mail SET state='sent' WHERE id=?",(sent['id'],))
            db.execute('INSERT INTO mail_headers VALUES(?,?)',(sent['id'],'<sent@example.com>'))
            db.execute("INSERT INTO mail(id,recipient,subject,body,state,evidence,due) VALUES('delivery_order','creator1@example.com','Product','Download','approved','paid order',?)",(time.time(),))
        raw=b'From: creator1@example.com\r\nIn-Reply-To: <sent@example.com>\r\nSubject: Re: Resource\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nPlease stop sending follow-ups.'
        self.assertTrue(campaigns.record_reply(self.store,raw,'account','1','1'))
        self.assertFalse(campaigns.record_reply(self.store,raw,'account','1','1'))
        self.assertFalse(campaigns.record_reply(self.store,raw.replace(b'creator1@',b'intruder@'),'account','1','2'))
        rows=studio.get(self.store,'/v1/mail')
        self.assertEqual(next(r for r in rows if r['id']=='delivery_order')['state'],'approved')
        self.assertEqual(next(r for r in rows if r['variant']=='A-followup')['state'],'cancelled')

    def test_imap_disabled_never_opens_mailbox(self):
        with patch('imaplib.IMAP4_SSL') as imap:
            self.assertFalse(campaigns.sync_inbox(self.store)['enabled']);imap.assert_not_called()

    def test_imap_uidvalidity_cursor_and_peek_do_not_mark_mail_read(self):
        self.campaign();sent=next(r for r in studio.get(self.store,'/v1/mail') if r['variant']=='A')
        with self.store.connect() as db:
            db.execute("UPDATE mail SET state='sent' WHERE id=?",(sent['id'],))
            db.execute('INSERT INTO mail_headers VALUES(?,?)',(sent['id'],'<message@example.com>'))
        raw=b'From: creator1@example.com\r\nIn-Reply-To: <message@example.com>\r\nSubject: Reply\r\nContent-Type: text/plain\r\n\r\nPlease send the outline.'
        class FakeIMAP:
            calls=[]
            def __init__(self,*args,**kwargs):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def login(self,*args):pass
            def select(self,mailbox,readonly=False):
                self.calls.append(('select',readonly));return 'OK',[b'1']
            def response(self,key):return key,[b'42']
            def uid(self,command,*args):
                self.calls.append((command,*args))
                if command=='search':return 'OK',[b'7']
                return 'OK',[(b'7 FETCH',raw)]
        with patch.dict(os.environ,{'OSA_IMAP_ENABLED':'true','OSA_IMAP_HOST':'imap.example.com','OSA_IMAP_USER':'fixture','OSA_IMAP_PASSWORD':'fixture'}),patch('imaplib.IMAP4_SSL',FakeIMAP):
            self.assertEqual(campaigns.sync_inbox(self.store)['imported'],1)
            self.assertEqual(campaigns.sync_inbox(self.store)['imported'],0)
        self.assertIn(('select',True),FakeIMAP.calls)
        self.assertTrue(all('BODY.PEEK' in c[2] for c in FakeIMAP.calls if c[0]=='fetch'))
        self.assertEqual(studio.rows(self.store,'SELECT * FROM imap_cursor')[0]['uid'],7)

    def test_followup_cannot_send_before_initial_message(self):
        self.campaign()
        with self.store.connect() as db:
            db.execute("UPDATE mail SET state='approved',due=0 WHERE id IN (SELECT mail_id FROM campaign_mail WHERE variant LIKE '%-followup')")
        with patch.dict(os.environ,{'OSA_MAIL_ENABLED':'true','OSA_SMTP_HOST':'smtp.example.com','OSA_SMTP_USER':'fixture','OSA_SMTP_PASSWORD':'fixture','OSA_FROM_EMAIL':'sender@example.com'}),patch('smtplib.SMTP') as smtp:
            self.assertIsNone(mail.send_one(self.store));smtp.assert_not_called()

    def test_store_pages_escape_content_and_demo_checkout_is_disabled(self):
        self.page();page=storefront.render(self.store,'guide').decode()
        self.assertNotIn('<script>',page);self.assertIn('&lt;script&gt;',page)
        self.assertIn('DEMONSTRATION',page);self.assertNotIn('action="/shop/checkout"',page)
        with self.assertRaises(ValueError):storefront.start_checkout(self.store,'guide','buyer@example.com',storefront.checkout_nonce('guide'))
        archive=zipfile.ZipFile(io.BytesIO(storefront.funnel_bundle(self.store,'guide')))
        self.assertIn('sample.html',archive.namelist());self.assertIn(b'href="style.css"',archive.read('index.html'))

    def test_private_store_not_accessible_or_counted(self):
        self.page(False)
        with self.assertRaises(ValueError):storefront.render(self.store,'guide')
        self.assertIn(b'Private editor preview',storefront.render(self.store,'guide',preview=True))
        self.assertEqual(studio.rows(self.store,'SELECT * FROM visits'),[])

    def test_checkout_replay_does_not_create_another_payment_link(self):
        jid,_=self.page()
        with self.store.connect() as db:db.execute("UPDATE jobs SET provider='ollama' WHERE id=?",(jid,))
        nonce=storefront.checkout_nonce('guide')
        def create(*args):
            with self.store.connect() as db:db.execute("INSERT INTO orders(id,product_id,email,amount,currency,state,mode,url,created) VALUES('one','guide','buyer@example.com',9900,'INR','pending','test','https://rzp.io/test',?)",(time.time(),))
            return {'id':'one','url':'https://rzp.io/test'}
        with patch('open_service_agents.storefront.payments.checkout',side_effect=create) as adapter:
            first=storefront.start_checkout(self.store,'guide','buyer@example.com',nonce)
            second=storefront.start_checkout(self.store,'guide','buyer@example.com',nonce)
            self.assertEqual(first['url'],second['url']);self.assertEqual(adapter.call_count,1)
            with self.assertRaises(ValueError):storefront.start_checkout(self.store,'guide','other@example.com',nonce)

    def test_transfers_require_exact_approval_and_explicit_enable(self):
        self.paid();t=transfers.plan(self.store,'order1','acct_example123')
        with self.assertRaises(ValueError):transfers.approve(self.store,t['id'],1,t['account'])
        transfers.approve(self.store,t['id'],2970,t['account'])
        with patch('open_service_agents.transfers.request_json') as request:
            self.assertIsNone(transfers.send_one(self.store));request.assert_not_called()
        with self.assertRaises(ValueError):transfers.plan(self.store,'order1','acct_second123')

    def test_transfer_unknown_outcome_is_not_retried(self):
        self.paid();t=transfers.plan(self.store,'order1','acct_example123');transfers.approve(self.store,t['id'],2970,t['account'])
        with patch.dict(os.environ,{'OSA_ROUTE_ENABLED':'true','RAZORPAY_KEY_ID':'rzp_test_fixture','RAZORPAY_KEY_SECRET':'fixture'}),patch('open_service_agents.transfers.request_json',side_effect=TimeoutError) as request:
            self.assertEqual(transfers.send_one(self.store)['state'],'uncertain')
            self.assertIsNone(transfers.send_one(self.store));self.assertEqual(request.call_count,1)

    def test_refund_cancels_pending_transfer_and_flags_submitted_transfer(self):
        self.paid();t=transfers.plan(self.store,'order1','acct_example123')
        raw=json.dumps({'event':'refund.processed','payload':{'refund':{'entity':{'payment_id':'pay_fixture'}}}}).encode()
        signature=hmac.new(b'w'*48,raw,hashlib.sha256).hexdigest()
        for event_id in ('refund_one','refund_two'):
            payments.webhook(self.store,raw,signature,event_id,'test')
            self.assertEqual(studio.rows(self.store,'SELECT state FROM transfers')[0]['state'],'cancelled')
        with self.store.connect() as db:db.execute("UPDATE transfers SET state='submitted' WHERE id=?",(t['id'],))
        payments.webhook(self.store,raw,signature,'refund_three','test')
        self.assertEqual(studio.rows(self.store,'SELECT state FROM transfers')[0]['state'],'needs-reconciliation')

    def test_paid_event_with_refunded_amount_cancels_transfer(self):
        self.paid();transfers.plan(self.store,'order1','acct_example123')
        with self.store.connect() as db:db.execute("UPDATE orders SET link_id='plink_fixture' WHERE id='order1'")
        raw=json.dumps({'event':'payment_link.paid','payload':{
            'payment_link':{'entity':{'id':'plink_fixture','order_id':'provider_order','status':'paid','amount':9900,'amount_paid':9900,'currency':'INR'}},
            'payment':{'entity':{'id':'pay_fixture','order_id':'provider_order','status':'captured','captured':True,'amount':9900,'currency':'INR','amount_refunded':100}}}}).encode()
        signature=hmac.new(b'w'*48,raw,hashlib.sha256).hexdigest()
        payments.webhook(self.store,raw,signature,'late_paid','test')
        self.assertEqual(studio.rows(self.store,'SELECT state FROM transfers')[0]['state'],'cancelled')
        self.assertEqual(payments.ledger(self.store)['totals'],[])

    def test_transfer_valid_response_records_submitted_not_settled(self):
        self.paid();t=transfers.plan(self.store,'order1','acct_example123');transfers.approve(self.store,t['id'],2970,t['account'])
        response={'items':[{'id':'trf_fixture','source':'pay_fixture','recipient':t['account'],'amount':2970,'currency':'INR'}]}
        with patch.dict(os.environ,{'OSA_ROUTE_ENABLED':'true','RAZORPAY_KEY_ID':'rzp_test_fixture','RAZORPAY_KEY_SECRET':'fixture'}),patch('open_service_agents.transfers.request_json',return_value=response):
            self.assertEqual(transfers.send_one(self.store)['state'],'submitted')

    def test_dashboard_http_auth_and_public_checkout_origin_guard(self):
        server=make_server(self.store,port=0)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base='http://127.0.0.1:'+str(server.server_port)
        with urllib.request.urlopen(base+'/studio') as response:
            self.assertIn(b'Product studio',response.read())
            self.assertIn("script-src 'self'",response.headers['Content-Security-Policy'])
        for path in ('/v1/overview','/v1/replies','/v1/orders','/v1/export/private','/v1/transfers'):
            with self.assertRaises(urllib.error.HTTPError) as err:urllib.request.urlopen(base+path)
            self.assertEqual(err.exception.code,401)
        req=urllib.request.Request(base+'/shop/checkout',data=b'product_id=guide',headers={'Origin':'https://evil.example'})
        with self.assertRaises(urllib.error.HTTPError) as err:urllib.request.urlopen(req)
        self.assertEqual(err.exception.code,401)


if __name__=='__main__':unittest.main()
