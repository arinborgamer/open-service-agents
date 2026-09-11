"""Local operator API plus public signed-webhook/download endpoints. Use TLS proxy online."""
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from . import models, payments


def make_server(store, host="127.0.0.1", port=8787):
    api_token = payments.secret("OSA_API_TOKEN")

    class Handler(BaseHTTPRequestHandler):
        server_version = "OpenServiceAgents/0.1"

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
            self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
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

        def do_GET(self):
            try:
                path = urlsplit(self.path).path
                if path == "/health":
                    return self.reply(200, {"status": "ok", "service": "open-service-agents", "version": "0.1.0"})
                if path.startswith("/download/"):
                    return self.reply(200, payments.download(store, path[10:]), "application/zip")
                self.authorized()
                if path == "/v1/jobs":
                    return self.reply(200, store.jobs())
                if path.startswith("/v1/jobs/"):
                    return self.reply(200, store.job(path[9:]))
                if path == "/v1/ledger":
                    return self.reply(200, payments.ledger(store))
                self.reply(404, {"error": "Not found"})
            except PermissionError:
                self.reply(401, {"error": "Unauthorized"})
            except (ValueError, KeyError):
                self.reply(400, {"error": "Invalid request or unavailable resource"})
            except Exception:
                self.reply(500, {"error": "Internal error"})

        def do_POST(self):
            try:
                path = urlsplit(self.path).path
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
                self.reply(404, {"error": "Not found"})
            except PermissionError:
                self.reply(401, {"error": "Unauthorized or invalid signature"})
            except (ValueError, KeyError, TypeError):
                self.reply(400, {"error": "Invalid request or configuration"})
            except Exception:
                self.reply(500, {"error": "Internal error; check configuration"})

    return ThreadingHTTPServer((host, port), Handler)
