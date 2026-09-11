# Validation record

Engineering-preview checks performed on 2026-09-11:

## v0.2.1 Outlook checks

- All 52 automated tests passed on Windows/Python 3.11, and installation of the optional Outlook dependencies succeeded.
- Mocked regression coverage checks exact-account selection, separate inbox consent, restricted Microsoft endpoints, XOAUTH2 instead of password login, silent refresh failure before claiming mail, no-send SMTP verification, read-only IMAP and rejection of plaintext persistence.
- On Windows, the installed Microsoft persistence library successfully encrypted and recovered a non-secret fixture; the raw cache did not contain the fixture text. This exercised DPAPI, not a real token or login.
- No Microsoft client ID or token cache is configured locally. No actual mailbox authorization, message send or inbox access has been tested; owner app registration and sign-in remain required.

## v0.2 checks

- Windows, Python 3.11: 41 automated tests passed, including repeated refunds and refunded-payment events cancelling or flagging partner transfers. JavaScript syntax and Python compilation checks passed.
- The 0.2.0 wheel built successfully and includes all three dashboard assets, with no test tools or private runtime files. The isolated local installation reports version 0.2.0.
- The API, generation worker and mail worker were restarted under the hidden Windows supervisor, and the existing sign-in task was updated to use the project virtual environment. The dashboard rendered after restart. Mail, merchant checkout and transfers remain unconfigured/disabled.
- The original real Ollama job finished all ten stages successfully after the citation-schema fix.
- A real authenticated dashboard adviser request completed against local Ollama after restarting its service, saving a 1,953-character answer with a supplied-source citation. This verifies generation and persistence, not factual accuracy or commercial performance. Ollama must remain running separately.
- New regression coverage includes 12-chapter exports, revision/approval locks, public-network guards, robots exclusions, explicit redirect handling, source extraction, mocked YouTube discovery, qualified A/B drafts, IMAP reply correlation and UID resumption, follow-up prerequisites, escaped storefronts, private previews, checkout replay protection and transfer approval/uncertain outcomes.
- Browser checks used an isolated fictional-data server with outbound mail and payment credentials disabled. Verified unlock, page-section reordering and preview, campaign creation as drafts, and the agent-facing read-only job tool (valid and invalid input). Mobile testing at 390px showed no document-width overflow. No live customer records were used.
- A live permitted import of Python.org's documentation page returned a 1,709-character excerpt, with no truncation.
- No Brave/YouTube key, real mailbox, merchant or Linked Account was configured. Their adapters have contract/fixture coverage only. Docker/Caddy configuration is provided but not deployment-tested; Docker is unavailable on this workstation.

## v0.1 baseline

- Windows, Python 3.11: 21 automated tests passed, including durable jobs, explicit failed-job recovery, stale-worker protection, authentication, payment event validation, duplicate handling, refund revocation, signed downloads and outreach suppression.
- Python compilation and a wheel build/install succeeded. Core runtime has no third-party dependencies.
- The ten-stage offline fixture completed. Operator and customer ZIP exports were checked separately.
- Optional ReportLab PDF export produced four pages; all four rendered pages were visually inspected for clipping and overlap.
- The local HTTP API responded to its health check. An actual HTTP download returned a ZIP after a simulated signed payment.
- Hidden Windows API/worker supervision was started, and a current-user sign-in task was registered. This is local operation, not an always-on public host. Ollama must also be running for real AI jobs.
- A real Ollama job checkpointed its first three stages, then exposed a missing-citations defect in plain JSON mode. A captured local replay reproduced the rejection. After adding schema-constrained output, the same chapter call returned a validated 3,228-character draft with supplied-source citations. The regression test passed and the main job resumed from its saved stages. Full-pipeline completion and editorial saleability remain separate checks.

The initial revision passed the Windows/Linux Python 3.11/3.12 CI matrix. Check the latest run for subsequent commits rather than assuming earlier results apply unchanged.

Not validated against live accounts: Razorpay test/live API and actual webhook delivery, merchant approval, SMTP delivery, bank settlement, partner payouts, customer acquisition, Docker deployment or a public HTTPS host. Payment unit tests use explicit fixtures, not real transactions. No revenue is claimed.

Video research used the complete available English automatic captions for all four linked videos. Visual-only details, private product code, performance and promotional earnings claims were not independently verified. The implementation is original and bounded; see FEATURES.md for omissions.

The Ollama response fix follows the provider's [structured-output schema contract](https://docs.ollama.com/capabilities/structured-outputs). It enforces fields and allowed citation IDs, not factual entailment or product quality.
