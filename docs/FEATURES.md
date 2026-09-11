# Evidence-to-implementation map

Read the full caption-study notes before treating narrated marketing as a technical specification. Complete captions for all four videos were studied; visual-only interfaces were not independently verified.

| Publicly narrated module | Original implementation | Present limitation |
|---|---|---|
| Synthesize niche ideas | `opportunity` stage plus optional live search discovery | Model suggestions use supplied evidence; no proprietary scores or guaranteed demand |
| Synthesize creator mode | Validated creator notes and `creator` analysis | No automatic Instagram scraping; permissioned exports/notes are inputs |
| Transformation map | `transformation` stage | Three-section initial outline; no interactive outline picker |
| Manuscript and branding | Three chapter stages and `brand` | Editorial drafts; no guarantee of subject expertise |
| Ebook download | Markdown/HTML/ZIP and optional ReportLab PDF | PDF not included in buyer ZIP by default; not a 45-page reproduction |
| Store copy and publication | `storefront` plus approved product record and Razorpay Payment Links | No public multi-tenant storefront UI |
| ListKit outreach | `outreach`, mail queue, approval, SMTP, scheduled drafts, suppressions | Requires own recipients/sender; no private creator list, inbox sync, or response optimization |
| Whop checkout and delivery | Razorpay adapter, signed webhooks, revocable download, transactional email queue | Provider onboarding/public TLS hosting required; no automatic partner payouts |
| Salesfunnels export | `launch`, funnel graph and portable ZIP/build prompt | Planning export, not deployed funnel pages |
| Ask Iman AI bonus | Independent `ask` command using evidence brief | No likeness, private corpus or claim of equivalent training |
| Staff handpicked list/coaching/guarantees | Not reproduced | These are human/private services, not available software agents |

Core runtime is tested with offline fixtures and a mocked Ollama contract. Record any real-model or live-provider results separately in the release notes. No revenue is claimed by an installation or successful test.
