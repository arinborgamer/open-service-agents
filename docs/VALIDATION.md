# Validation record

Engineering-preview checks performed on 2026-09-11:

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
