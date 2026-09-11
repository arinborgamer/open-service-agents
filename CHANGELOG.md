# Changelog

## 0.2.1

Adds opt-in personal Outlook.com OAuth for SMTP and read-only IMAP, Microsoft browser/PKCE sign-in, encrypted out-of-repository token persistence, silent refresh, restricted Microsoft endpoints, and a no-send SMTP verification command. Adds setup documentation and mocked regression coverage. No Microsoft app or mailbox is connected automatically; live provider verification still requires owner registration and consent.

## 0.2.0

Adds an authenticated browser dashboard; 3-12 chapter plans; editable drafts with revision history and approval locks; bounded robots-aware website and public-caption imports; Brave/YouTube creator discovery; a reviewed shortlist; A/B campaign drafts and metrics; a separate mailbox worker; read-only IMAP reply correlation and follow-up suppression; an editable/reorderable product-page builder; sample and confirmation pages; replay-safe public checkout; aggregate page/order counts; explicit approval of Route partner transfers; and Docker/Caddy deployment configuration. No external merchant, mailbox, search or hosting account is activated by installing this release. See docs/V0.2.md for boundaries.

Model smoke testing exposed omitted citations in plain JSON mode. The preview now uses a required-field/allowed-source schema, with a regression test and explicit failed-job recovery that preserves completed stages.

## 0.1.0

Initial independent implementation: ten checkpointed generation stages, evidence validation, demo/Ollama providers, source discovery, adviser, portable product and funnel exports, optional PDF, authenticated API, durable worker, approved SMTP queue, Razorpay checkout/webhook adapter, expiring download capabilities, refund revocation and gross-share accounting. Includes four-video study notes, Whop alternatives, pseudonymous publication guidance and cross-platform CI.

Live merchant payments, payouts, external email delivery, and a hosted storefront are not activated by this release. See the README feature limits and setup instructions.
