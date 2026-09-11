# From local automation to real sales

## Already automated by the code

Job intake -> saved sequential AI stages -> draft exports. Approved outgoing messages -> scheduled SMTP delivery. Matching signed paid event -> entitlement -> queued delivery email -> signed download. Refund/dispute event -> revoked entitlement. Local worker and API can restart through the Windows launcher or Docker Compose.

## Owner setup

The v0.2 dashboard and deployment/IMAP/Route instructions are in [V0.2.md](V0.2.md). Generation and mail now run as separate workers; `osa mail-worker` handles approved mail, configured inbox polling and explicitly approved Route transfers.

1. Set a public alias/brand and a support mailbox you control. Keep required financial details private except where the provider or applicable transaction rules require disclosure. Do not reuse personal credentials in the repo.
2. Create/verify a Razorpay account directly in its dashboard. India residency alone does not establish approval; payment product and international enablement depend on the account. Confirm the supported digital product, receiving bank and actual fees. [Payment Links](https://razorpay.com/docs/payments/payment-links/).
3. Use test API keys first. Put `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` in `.local/runtime.env`. Use a dedicated webhook secret. Never send secrets into a GitHub issue or commit them.
4. Operate the service on an always-on host. Point a TLS reverse proxy at port 8787. Route `/webhooks/razorpay` and `/download/*`; keep `/v1/*` protected. Configure request/body/rate limits and encrypted backups. `OSA_PUBLIC_URL` must match the final HTTPS hostname.
5. Configure the webhook in Razorpay for paid Payment Links and refund/dispute events. Test full payment, duplicate delivery, delayed events, wrong amounts, refunds and download expiry. [Webhook sample contract](https://razorpay.com/docs/webhooks/payment-links/), [signature validation](https://razorpay.com/docs/webhooks/validate-test/).
6. Configure a STARTTLS SMTP service. Set `OSA_FROM_EMAIL`, `OSA_SMTP_HOST`, port, user and password, and enable `OSA_MAIL_ENABLED=true`. Verify sender-domain authentication with that provider. The mail worker sends approved marketing messages and verified live fulfillment messages. Configure the opt-in IMAP adapter in [V0.2.md](V0.2.md) to correlate incoming replies and stop follow-ups, or record replies manually using `record-reply`.
7. Submit real research and run the pipeline. Review the artifact contents and sources. Approve a product with its actual price/refund/support terms handled by your customer-facing offer. The software does not manufacture traffic or consent.
8. Once sandbox checks pass, set matching live keys, `OSA_PAYMENT_MODE=live` and `OSA_LIVE_PAYMENTS=true`. Restart the API/worker. A live order is earned only after a real captured payment. Confirm payouts in the provider dashboard/bank.

## Partner shares

Agree whether shares are based on gross or net receipts and who bears fees/refunds/taxes before selling. The ledger computes gross accruals and removes revoked receipts. The v0.2 Route adapter submits explicitly approved INR shares to verified Linked Accounts only when separate flags and matching credentials are configured. Keep provider exports for settlement/reversal reconciliation. No transfers are activated by installation.

## Operational recovery

Jobs checkpoint each successful stage, reclaim expired leases, and stop after three attempts. Inspect `osa jobs` for failures. After fixing model configuration, use `osa retry JOB_ID` to explicitly grant a failed job three new attempts while retaining completed stages. Restart workers after changing code/configuration. Changed briefs need a new job. Live checkout creation is not automatically retried if its outcome is uncertain; inspect the provider using the recorded order `reference_id` first. SMTP rows left `sending` or `uncertain` require provider review before manual retry to avoid duplicate messages.

The API uses Python's built-in HTTP server and SQLite and is intended for a small trusted operator setup. Before multi-tenant public use, add a production HTTP stack, tenant authorization, request-rate limits, billing reconciliation, encryption/retention controls and independently reviewed security. Docker and provider integrations require deployment-specific verification; local fixture tests alone do not establish live compatibility.
