# Open Service Agents

Original, open-source agents for researching a digital product, creating a draft, preparing creator partnerships, and fulfilling paid orders. Python 3.11+, SQLite, optional local Ollama. No Whop account required.

**Status: v0.1 engineering preview.** Runs locally and has executable payment/delivery and job-recovery tests. It is not a turnkey income system. Live payment, email, and hosted deployment require your own approved accounts and configuration. Model-written drafts require editorial review. Test/demo transactions are always separated from actual receipts.

## What it does

| Workflow | Implemented behavior |
|---|---|
| Opportunity agent | Suggests three evidence-linked product directions and a validation experiment |
| Creator analyst | Analyzes supplied creator notes/content; produces sourcing criteria if none are supplied |
| Product planner | Before/after outcome, outline, reader exercises |
| Product writer | Three checkpointed sections; ebook/workbook or written course/coaching draft |
| Brand agent | Original name, voice and visual direction |
| Storefront copy agent | Offer copy, FAQs and pricing hypotheses |
| Partnership agent | Two email variants per supplied creator, proposed partnership discussion |
| Launch agent | Funnel brief, ten-story sequence, feedback and measurement plan |
| Independent adviser | Answers a question using a supplied evidence brief; does not impersonate anyone |
| Research discovery | Optional Brave search adapter; labels results as snippets, not full-page research |
| Exports | Markdown, readable HTML, product ZIP, funnel graph/brief ZIP; optional PDF |
| Automation | Persistent worker, bounded retries, per-stage checkpoints, authenticated local API |
| Outreach | Draft/approve/schedule SMTP messages; reply and opt-out suppression; daily limit |
| Payments | Razorpay Payment Links, raw-body HMAC verification, amount/currency matching, deduplication |
| Delivery/accounting | Signed expiring downloads; automatic live receipt email queue; refund/dispute revocation; gross partner-share ledger |

## Quick start: no account or API key needed

```sh
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e .
osa init
osa submit examples/brief.json --provider demo --key first-demo
osa worker --once
osa jobs
```

Copy the returned job ID:

```sh
osa show JOB_ID
osa export JOB_ID --out .local/exports/demo
osa serve
```

The API listens on `http://127.0.0.1:8787`. `/health` is public. Administrative requests need `Authorization: Bearer OSA_API_TOKEN`, generated privately in `.local/runtime.env`. Run `osa doctor` to check configuration without displaying secrets. `osa --help` lists all commands.

**Demo is a deterministic fixture, not AI output or a saleable product.** It performs no network requests. Its outputs are visibly labeled and cannot be sold through the provider checkout adapter.

## Run real AI

Install [Ollama](https://ollama.com/), pull a tool-independent instruction model, and start its service:

```sh
ollama pull granite4:3b
osa submit examples/brief.json --provider ollama --key first-real-draft
osa worker
```

The default adapter uses Ollama's native `/api/chat`, schema-constrained JSON output, an explicit 8k context and 1,600 output tokens per stage. The schema requires citations from supplied source IDs; this checks structure, not whether every claim is supported. There is no generated tool-call parser. Set `OSA_MODEL` and `OSA_OLLAMA_URL` in `.local/runtime.env` to choose another installed model. Small models may need shorter briefs or a stronger replacement. A failed real call is never silently converted to a demo success.

Create your own brief using `examples/brief.json`. Supply actual source excerpts/notes and URLs, a topic, audience and problem, and optional creator records. URLs are citation metadata, not silently scraped pages. Use owned/licensed/permissioned content when adapting a creator's material. Public references support original paraphrasing, not republishing their text.

`osa discover "your niche query"` uses your `BRAVE_API_KEY` and returns labeled search snippets to review and incorporate into a brief. It does not buy a lead list, scrape Instagram, or invent customer emails. `osa ask examples/brief.json "What evidence should I collect before pricing this?"` runs the independent adviser.

## Product and funnel exports

```sh
osa export JOB_ID --out .local/exports/my-product
python -m pip install -e .[pdf]
osa pdf JOB_ID --out .local/output/pdf/my-product.pdf
```

Operator exports include all generated drafts and `funnel-brief.zip`. The customer ZIP contains only the product's Markdown/HTML editions and references; it excludes the original brief, creator records and outreach drafts. Optional PDF export is an operator deliverable and is not automatically added to checkout downloads in v0.1. The funnel ZIP is a graph, copy and build prompt—not a deployed multi-page website. Three sections are the initial bounded format, not a claim to recreate a 45-page proprietary ebook generator.

## Checkout and automated delivery without Whop

Razorpay is the first adapter for an eligible Indian seller. The owner must complete provider verification privately and connect a bank account. Source-code distribution remains free on GitHub. See [alternatives and payout constraints](docs/research/distribution.md) and [live setup](docs/LIVE-SETUP.md).

```sh
# Editorial approval also sets an immutable price snapshot in minor units.
osa approve-product JOB_ID my-guide --amount 9900 --currency INR --partner-bps 3000
osa checkout my-guide buyer@example.com --demo
osa simulate-payment ORDER_ID
osa delivery-link ORDER_ID
osa ledger
```

The above is a local simulation. For actual provider **test mode**, use a real generated draft and set Razorpay test credentials; omit `--demo`. For **live mode**, use matching live credentials, `OSA_PAYMENT_MODE=live`, and `OSA_LIVE_PAYMENTS=true` after provider onboarding and end-to-end sandbox testing.

Configure Razorpay's webhook at `https://YOUR-HOST/webhooks/razorpay` with the same private `RAZORPAY_WEBHOOK_SECRET`. Subscribe to `payment_link.paid`, refund events, `payment.refunded`, and `payment.dispute.created`. Full captured payment must match the recorded link, amount, currency and provider order. Redirect/query parameters never unlock access.

After a verified live payment, a delivery email is queued automatically. Enable SMTP delivery to send it. Download URLs expire after seven days and stop working after refunds/disputes. Any refund currently suspends the whole entitlement pending manual reconciliation. An operator can issue a fresh link with `delivery-link` for an eligible order.

The ledger records gross receipts and accrued partner shares in minor currency units. **It is not a wallet, net profit, bank settlement or automatic partner payout.** Fees, taxes, partial refunds, disputes and payout reconciliation still need provider records. Automatic split payouts require a separately approved marketplace/payout integration, not just an internal percentage.

## Creator outreach

Review the generated `outreach.md`, personalize a message, and save its body in a private file:

```sh
osa draft-mail creator@example.com "A resource idea for your audience" .local/message.txt --basis "Creator requested a sample"
osa mail-queue
osa approve-mail MAIL_ID
osa worker
osa record-reply creator@example.com --status interested
```

`--delay-hours 48` schedules a follow-up draft. Set SMTP variables and `OSA_MAIL_ENABLED=true` to deliver approved messages. No existing email account is accessed automatically. Replies are recorded manually in v0.1; every recorded reply stops outstanding follow-ups. SMTP failures with uncertain delivery are not automatically retried. Confirm the actual sender identity, recipient suitability and any required contact details for your campaign. Reply-rate optimization and automatic inbox synchronization are not implemented.

## Automation and deployment

Windows: run `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start-local.ps1`. This starts a hidden supervisor for the API and worker. `scripts/install-autostart.ps1` registers the supervisor at your next sign-in. Use `scripts/stop-local.ps1` to stop these processes. Local runtime records/logs live under ignored `.local/`. The computer must remain awake.

Linux/container:

```sh
osa init
docker compose up --build -d
docker compose logs --tail=50
```

The container port binds to loopback. Add a TLS reverse proxy and rate limits before exposing webhook/download endpoints. Forward administrative API routes only to authorized operators. Do not expose Ollama publicly. The built-in HTTP server is an initial small single-operator deployment, not a hardened multi-tenant SaaS. Docker files are provided; consult [deployment notes](docs/LIVE-SETUP.md) for validation status and constraints.

## Privacy and open source

Maintainer identity: `arinborgamer`. Commits use GitHub's noreply address. Secrets, downloaded captions, logs, data, generated drafts and customer records are ignored. Payment KYC still uses the owner's real details privately, and a processor may expose verified business details on checkout/receipts. See [privacy boundaries](docs/PRIVACY.md).

This project is an independent implementation informed by publicly narrated workflows in four videos. It contains no proprietary code, private prompts, branding, paid lead lists, swipe files, coaching service or training data from Monetize/Synthesize/ListKit/Whop. It is not affiliated with those products or presenters. [Study of videos 1–2](docs/research/videos-1-2.md), [study of videos 3–4](docs/research/videos-3-4.md), [feature mapping](docs/FEATURES.md).

## Development

```sh
python -m unittest discover -s tests -v
python -m compileall -q open_service_agents
```

Core runtime/tests use the standard library. GitHub Actions runs Windows and Linux on Python 3.11/3.12. See [contributing](CONTRIBUTING.md), [security](SECURITY.md), and [MIT license](LICENSE).
