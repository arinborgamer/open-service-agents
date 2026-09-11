"""Local operator API plus public signed-webhook/download endpoints. Use TLS proxy online."""
import hmac
import json
import os
import time
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from . import models, payments, studio, storefront
from .exports import bundle
from . import __version__


def make_server(store, host="127.0.0.1", port=8787):
    api_token = payments.secret("OSA_API_TOKEN")
    checkout_times = []
    checkout_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "OpenServiceAgents/" + __version__

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, *_):
            # URLs contain private download capabilities. Never log them.
            pass

        def reply(self, status, value, content_type="application/json"):
            raw = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
            if content_type == "application/zip":
                self.send_header("Content-Disposition", 'attachment; filename="product.zip"')
            self.end_headers()
            self.wfile.write(raw)

        def authorized(self):
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + api_token):
                raise PermissionError("Operator authentication required.")

        def read_body(self):
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("Chunked requests not supported.")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 250000:
                raise ValueError("Request body must contain 1-250000 bytes.")
            return self.rfile.read(length)

        def redirect(self, url):
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or '\r' in url or '\n' in url:
                raise ValueError('Checkout provider returned an invalid URL.')
            self.send_response(303)
            self.send_header('Location', url)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Length', '0')
            self.end_headers()

        def do_GET(self):
            try:
                path = urlsplit(self.path).path
                assets = {"/": ("index.html", "text/html; charset=utf-8"), "/studio": ("index.html", "text/html; charset=utf-8"),
                          "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}
                if path in assets:
                    name, mime = assets[path]
                    return self.reply(200, (Path(__file__).parent / "web" / name).read_bytes(), mime)
                if path == "/health":
                    return self.reply(200, {"status": "ok", "service": "open-service-agents", "version": __version__})
                if path.startswith("/download/"):
                    return self.reply(200, payments.download(store, path[10:]), "application/zip")
                if path.startswith('/p/'):
                    parts = path.strip('/').split('/')
                    if len(parts) > 3 or (len(parts) == 3 and parts[2] not in ('sample','thanks')):
                        return self.reply(404, {'error':'Page not found'})
                    return self.reply(200, storefront.render(store, parts[1], parts[2] if len(parts) == 3 else 'offer'), 'text/html; charset=utf-8')
                self.authorized()
                if path.startswith('/v1/export/'):
                    return self.reply(200, bundle(store.job(path[11:])), 'application/zip')
                if path.startswith('/v1/funnel-export/'):
                    return self.reply(200, storefront.funnel_bundle(store, path[18:]), 'application/zip')
                if path == "/v1/jobs":
                    return self.reply(200, store.jobs())
                if path.startswith("/v1/jobs/"):
                    return self.reply(200, store.job(path[9:]))
                if path == "/v1/ledger":
                    return self.reply(200, payments.ledger(store))
                return self.reply(200, studio.get(store, path))
            except PermissionError:
                self.reply(401, {"error": "Unauthorized"})
            except (ValueError, KeyError):
                self.reply(400, {"error": "Invalid request or unavailable resource"})
            except Exception:
                self.reply(500, {"error": "Internal error"})

        def do_POST(self):
            try:
                path = urlsplit(self.path).path
                if path == '/shop/checkout':
                    public = os.environ.get('OSA_PUBLIC_URL','http://127.0.0.1:8787').rstrip('/')
                    if self.headers.get('Origin') != public:
                        raise PermissionError('Checkout must start on the product page.')
                    with checkout_lock:
                        now = time.time()
                        checkout_times[:] = [t for t in checkout_times if t > now - 3600]
                        if len(checkout_times) >= 120:
                            return self.reply(429, {'error':'Checkout request limit reached. Try again later.'})
                        checkout_times.append(now)
                    fields = parse_qs(self.read_body().decode('utf-8'), max_num_fields=6)
                    if any(len(v) != 1 for v in fields.values()) or fields.get('terms') != ['accepted']:
                        raise ValueError('Accept the sale terms before checkout.')
                    order = storefront.start_checkout(store, fields['product_id'][0], fields['email'][0], fields['nonce'][0])
                    return self.redirect(order['url'])
                if path == "/webhooks/razorpay":
                    raw = self.read_body()
                    mode = os.environ.get("OSA_PAYMENT_MODE", "test")
                    if mode not in ("test", "live"):
                        raise ValueError("HTTP webhooks require test or live mode.")
                    result = payments.webhook(store, raw, self.headers.get("X-Razorpay-Signature"), self.headers.get("x-razorpay-event-id"), mode)
                    return self.reply(200, result)
                self.authorized()
                data = json.loads(self.read_body())
                if path == "/v1/jobs":
                    provider = data.get("provider", "ollama")
                    if provider not in ("ollama", "demo"):
                        raise ValueError("Unknown provider.")
                    key = self.headers.get("Idempotency-Key")
                    return self.reply(202, {"id": store.enqueue(models.brief(data["brief"]), provider, key)})
                if path == "/v1/products":
                    pid = payments.approve_product(store, data["job_id"], data["id"], data["amount"], data.get("currency", "INR"), data.get("partner_bps", 0))
                    return self.reply(201, {"id": pid})
                if path == "/v1/checkout":
                    return self.reply(201, payments.checkout(store, data["product_id"], data["email"]))
                return self.reply(200, studio.post(store, path, data))
            except PermissionError:
                self.reply(401, {"error": "Unauthorized or invalid signature"})
            except ValueError as exc:
                self.reply(400, {"error": str(exc)[:240]})
            except (KeyError, TypeError):
                self.reply(400, {"error": "Invalid request or missing field"})
            except Exception:
                self.reply(500, {"error": "Internal error; check configuration"})

    return ThreadingHTTPServer((host, port), Handler)
