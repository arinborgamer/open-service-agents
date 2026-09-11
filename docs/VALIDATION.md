# Validation record

Engineering-preview checks performed on 2026-09-11:

- Windows, Python 3.11: 19 automated tests passed, including durable jobs, stale-worker protection, authentication, payment event validation, duplicate handling, refund revocation, signed downloads and outreach suppression.
- Python compilation and a wheel build/install succeeded. Core runtime has no third-party dependencies.
- The ten-stage offline fixture completed. Operator and customer ZIP exports were checked separately.
- Optional ReportLab PDF export produced four pages; all four rendered pages were visually inspected for clipping and overlap.
- The local HTTP API responded to its health check. An actual HTTP download returned a ZIP after a simulated signed payment.
- Hidden Windows API/worker supervision was started, and a current-user sign-in task was registered. This is local operation, not an always-on public host. Ollama must also be running for real AI jobs.
- A real Ollama job was started and checkpointed its first three stages. This establishes real model connectivity, not completion or saleability of the generated product.

The repository includes a Windows/Linux Python 3.11/3.12 CI matrix. Check its current run rather than assuming it passed from the existence of the workflow file.

Not validated against live accounts: Razorpay test/live API and actual webhook delivery, merchant approval, SMTP delivery, bank settlement, partner payouts, customer acquisition, Docker deployment or a public HTTPS host. Payment unit tests use explicit fixtures, not real transactions. No revenue is claimed.

Video research used the complete available English automatic captions for all four linked videos. Visual-only details, private product code, performance and promotional earnings claims were not independently verified. The implementation is original and bounded; see FEATURES.md for omissions.
