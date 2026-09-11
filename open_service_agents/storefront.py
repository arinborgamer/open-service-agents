"""Editable, escaped product pages and replay-safe public checkout initiation."""
import hashlib
import hmac
import html
import json
import os
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit
from . import payments
from .models import identifier, text, email


def configure(store, data):
    pid = identifier(data.get('product_id'))
    with store.connect() as db:
        product = db.execute('SELECT * FROM products WHERE id=? AND approved=1', (pid,)).fetchone()
    if not product:
        raise ValueError('Approve a completed product before building its page.')
    blocks = data.get('blocks', [])
    if not isinstance(blocks, list) or not 1 <= len(blocks) <= 12:
        raise ValueError('Add 1-12 page sections.')
    config = {'headline': text(data.get('headline'), 'headline', 200),
              'description': text(data.get('description'), 'description', 2000),
              'sample': text(data.get('sample'), 'free sample', 10000),
              'support_email': email(data.get('support_email')),
              'seller_name': text(data.get('seller_name'), 'seller display name', 150),
              'refund_policy': text(data.get('refund_policy'), 'refund policy', 3000),
              'terms': text(data.get('terms'), 'sale terms', 4000),
              'blocks': [{'heading': text(b.get('heading'), 'section heading', 150),
                          'body': text(b.get('body'), 'section body', 5000)} for b in blocks]}
    published = data.get('published') is True
    if published and data.get('reviewed') is not True:
        raise ValueError('Confirm editorial, rights and merchant-detail review before publishing.')
    with store.connect() as db:
        db.execute('INSERT INTO storefronts VALUES(?,?,?,?) ON CONFLICT(product_id) DO UPDATE SET content=excluded.content,published=excluded.published,updated=excluded.updated',
                   (pid, json.dumps(config), int(published), time.time()))
    return {'product_id': pid, 'published': published, 'url': '/p/' + pid}


def get_page(store, pid, preview=False):
    identifier(pid)
    with store.connect() as db:
        row = db.execute('SELECT s.*,p.amount,p.currency,p.job_id FROM storefronts s JOIN products p ON p.id=s.product_id WHERE s.product_id=? AND p.approved=1', (pid,)).fetchone()
    if not row or (not preview and not row['published']):
        raise ValueError('Product page is unavailable.')
    return {**dict(row), 'content': json.loads(row['content']), 'demo': store.job(row['job_id'])['provider'] == 'demo'}


def checkout_nonce(pid):
    value = f'{pid}.{int(time.time()) + 1800}.{secrets.token_hex(16)}'
    signature = hmac.new(payments.secret('OSA_DOWNLOAD_SECRET').encode(), value.encode(), hashlib.sha256).hexdigest()
    return value + '.' + signature


def start_checkout(store, pid, customer, nonce):
    page = get_page(store, pid)
    if page['demo']:
        raise ValueError('Demonstration products cannot be purchased.')
    if os.environ.get('OSA_PAYMENT_MODE','test') == 'live':
        configured = all(os.environ.get(k) for k in ('OSA_SMTP_HOST','OSA_SMTP_USER','OSA_SMTP_PASSWORD','OSA_FROM_EMAIL'))
        if os.environ.get('OSA_MAIL_ENABLED') != 'true' or not configured or urlsplit(os.environ.get('OSA_PUBLIC_URL','')).scheme != 'https':
            raise ValueError('Live public checkout requires configured delivery email and a public HTTPS URL.')
    customer = email(customer)
    try:
        value, signature = nonce.rsplit('.', 1)
        actual_pid, expiry, unique = value.split('.')
        expected = hmac.new(payments.secret('OSA_DOWNLOAD_SECRET').encode(), value.encode(), hashlib.sha256).hexdigest()
        if actual_pid != pid or int(expiry) <= time.time() or not hmac.compare_digest(signature, expected):
            raise ValueError()
    except (ValueError, AttributeError):
        raise ValueError('Checkout form expired. Reload the product page.') from None
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        old = db.execute('SELECT * FROM checkout_requests WHERE nonce=?', (nonce,)).fetchone()
        if old:
            if old['email'] != customer or old['product_id'] != pid:
                raise ValueError('Checkout form already belongs to another request.')
            order = db.execute('SELECT url FROM orders WHERE id=?', (old['order_id'],)).fetchone()
            if order:
                return {'url': order['url']}
            raise ValueError('Checkout creation is pending or uncertain. Contact support before retrying.')
        db.execute('INSERT INTO checkout_requests VALUES(?,?,?,NULL,?)', (nonce, pid, customer, 'creating'))
    try:
        order = payments.checkout(store, pid, customer)
        with store.connect() as db:
            db.execute("UPDATE checkout_requests SET order_id=?,state='ready' WHERE nonce=?", (order['id'], nonce))
        return order
    except Exception:
        with store.connect() as db:
            db.execute("UPDATE checkout_requests SET state='uncertain' WHERE nonce=?", (nonce,))
        raise


def render(store, pid, step='offer', preview=False):
    page = get_page(store, pid, preview)
    config = page['content']
    esc = html.escape
    root = '/p/' + pid
    if not preview:
        with store.connect() as db:
            day = datetime.now(timezone.utc).date().isoformat()
            db.execute('INSERT INTO visits VALUES(?,?,?,1) ON CONFLICT(product_id,day,page) DO UPDATE SET count=count+1', (pid, day, step))
    banner = '<p class="sale-note">DEMONSTRATION · Not for sale. This fixture is not an AI-generated product.</p>' if page['demo'] else ''
    if preview:
        banner += '<p class="sale-note">Private editor preview. Publishing is a separate action.</p>'
    if step == 'sample':
        content = '<h1>Try a sample</h1><div class="prose">' + esc(config['sample']) + '</div><p><a class="button" href="' + root + '">View the full product</a></p>'
    elif step == 'thanks':
        content = '<h1>Payment confirmation</h1><p>Access is issued only after the payment provider verifies a captured payment. A browser redirect does not grant access. Check your email after payment, or contact support if delivery is delayed.</p>'
    else:
        content = '<section class="store-hero"><span class="eyebrow">' + esc(config['seller_name']) + '</span><h1>' + esc(config['headline']) + '</h1><p>' + esc(config['description']) + '</p><a href="' + root + '/sample">Read a free sample</a></section>'
        for block in config['blocks']:
            content += '<section class="store-section"><h2>' + esc(block['heading']) + '</h2><div class="prose">' + esc(block['body']) + '</div></section>'
        content += '<section class="panel"><h2>Get the digital product</h2><p class="store-price">' + esc(page['currency']) + ' ' + f"{page['amount']/100:.2f}" + '</p><p>Delivered as a downloadable ZIP with HTML and Markdown editions.</p>'
        mode = os.environ.get('OSA_PAYMENT_MODE', 'test')
        enabled = mode in ('test', 'live') and bool(os.environ.get('RAZORPAY_KEY_ID') and os.environ.get('RAZORPAY_KEY_SECRET'))
        if page['demo'] or preview or not enabled:
            content += '<p>Checkout is disabled for this preview or has not been configured.</p>'
        else:
            if mode != 'live':
                content += '<p class="sale-note">Payment-provider test mode. No real purchase.</p>'
            content += '<form action="/shop/checkout" method="post"><input type="hidden" name="product_id" value="' + pid + '"><input type="hidden" name="nonce" value="' + checkout_nonce(pid) + '"><label>Delivery email<input name="email" type="email" required maxlength="254" autocomplete="email"></label><label class="check"><input type="checkbox" name="terms" value="accepted" required>I accept the sale terms and refund policy below.</label><button>Continue to secure checkout</button></form>'
        content += '</section>'
    content += '<section class="store-section"><h2>Refund policy</h2><div class="prose">' + esc(config['refund_policy']) + '</div><h2>Sale terms</h2><div class="prose">' + esc(config['terms']) + '</div><p>Support: <a href="mailto:' + esc(config['support_email']) + '">' + esc(config['support_email']) + '</a></p></section>'
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>' + esc(config['headline']) + '</title><link rel="stylesheet" href="/style.css"></head><body class="store-shell"><main>' + banner + content + '</main></body></html>').encode()


def funnel_bundle(store, pid):
    import io
    import zipfile
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as archive:
        for step, filename in (('offer','index.html'),('sample','sample.html'),('thanks','thanks.html')):
            # Portable export disables payment submission; hosted Python routes use real checkout.
            archive.writestr(filename, render(store, pid, step, preview=True).replace(('/p/'+pid+'/sample').encode(), b'sample.html').replace(('/p/'+pid).encode(), b'index.html').replace(b'href="/style.css"', b'href="style.css"'))
        from pathlib import Path
        archive.writestr('style.css', (Path(__file__).parent / 'web/style.css').read_bytes())
        archive.writestr('README.txt', 'Portable page preview. Checkout is deliberately disabled in this static export. Use the Python storefront routes with approved merchant credentials for sales.\n')
    return result.getvalue()
