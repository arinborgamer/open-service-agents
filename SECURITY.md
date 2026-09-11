# Security

This is a single-operator engineering preview. Keep the administrative API on a trusted network; expose only necessary endpoints behind TLS, request limits and a reverse proxy. Model output is data and never executes shell commands. Source URLs are not fetched by the model.

Keep `.local/`, `.env*`, runtime databases and private exports out of version control. Back up the SQLite database and download-signing secret securely. Restrict filesystem access to the operator; on Windows, check NTFS permissions because POSIX mode bits do not establish a private Windows ACL.

Webhook signatures require the unmodified raw body. Payment redirects are not proof of payment. Protect webhook secrets, rotate deliberately, and reconcile provider events. Download links are bearer capabilities; do not put them into analytics or access logs. Refund/dispute events revoke access; previously downloaded files cannot be remotely recalled.

Report vulnerabilities through GitHub private vulnerability reporting when enabled. Otherwise open an issue asking for a private channel without including exploit details, secrets, personal data or customer records. No general-purpose security audit or production certification is claimed.
