"""Isolated UI fixture, bound only to loopback. Never uses merchant/mail credentials."""
import json
import os
from pathlib import Path
import tempfile
from open_service_agents import models, payments, storefront, discovery
from open_service_agents.storage import Store
from open_service_agents.pipeline import run_one
from open_service_agents.server import make_server

os.environ.update({'OSA_API_TOKEN':'ui-test-only-token-not-a-secret-0000000000',
    'OSA_DOWNLOAD_SECRET':'ui-test-only-download-secret-00000000000',
    'RAZORPAY_WEBHOOK_SECRET':'ui-test-only-webhook-secret-000000000000',
    'OSA_MAIL_ENABLED':'false','OSA_IMAP_ENABLED':'false','OSA_LIVE_PAYMENTS':'false',
    'OSA_ROUTE_ENABLED':'false','OSA_PAYMENT_MODE':'test','OSA_PUBLIC_URL':'http://127.0.0.1:8788'})
for key in ('RAZORPAY_KEY_ID','RAZORPAY_KEY_SECRET','BRAVE_API_KEY','OSA_YOUTUBE_API_KEY'):
    os.environ.pop(key, None)
with tempfile.TemporaryDirectory(prefix='osa-ui-qa-') as folder:
    store = Store(folder)
    brief = models.brief(json.loads((Path(__file__).resolve().parents[1] / 'examples/brief.json').read_text()))
    brief['chapter_count'] = 6
    jid = store.enqueue(brief, 'demo')
    run_one(store)
    payments.approve_product(store,jid,'publishing-checklist',9900,'INR',3000)
    storefront.configure(store, {'product_id':'publishing-checklist', 'headline':'Make your next publishing day repeatable',
        'description':'An offline demonstration of a practical checklist and review workflow. Not a product for sale.',
        'sample':'Choose one upcoming post. Write its audience, useful takeaway and source before drafting.',
        'support_email':'support@example.com','seller_name':'Example Studio',
        'refund_policy':'Demonstration only. No payments are accepted.',
        'terms':'Fixture content for interface testing. Not for sale or distribution as a finished product.',
        'blocks':[{'heading':'A process you can repeat','body':'Prepare the evidence. Create one draft. Review its usefulness and sources.'},
                  {'heading':'Your review worksheet','body':'Check the audience, source, permissions and next action before publication.'}],
        'published':True,'reviewed':True})
    discovery.save_lead(store, {'name':'Example Educational Creator','profile_url':'https://example.com/creator',
        'niche':'Publishing workflows','audience_notes':'Fictional UI fixture. No actual creator or audience.',
        'email':'creator@example.com','contact_basis':'Synthetic test recipient; never send.','status':'qualified'})
    print('Isolated UI QA: http://127.0.0.1:8788/studio',flush=True)
    make_server(store,port=8788).serve_forever()
