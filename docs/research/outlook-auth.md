# Outlook delegated OAuth for a local Python agent

Checked 2026-09-11 against Microsoft primary sources. Research only: no accounts connected, credentials read, or authentication code changed.

## Recommendation

Use Microsoft Graph with delegated OAuth for a new Outlook connector. Both personal Outlook.com and Microsoft 365 accounts support delegated `Mail.Send` and `Mail.Read`. Request `Mail.Send` for sending, `Mail.Read` only if reply bodies must be read, and offline access for continued operation. `Mail.ReadBasic` omits bodies and attachments; `Mail.ReadWrite` is unnecessary for send-plus-read. Mail.Send alone can save Sent Items. These read permissions cover the mailbox, not just agent-created conversations: restricting ingestion to correlated replies must also be enforced in application logic. [Graph permissions](https://learn.microsoft.com/en-us/graph/permissions-reference)

## Setup and consent

1. Register an app in Microsoft Entra. Choose personal accounts only for an Outlook.com-only connector, or organizational directories plus personal accounts to support both. A single-tenant registration is appropriate for one organization's mailbox. Registration access is separate from having a mailbox: Microsoft's guide lists an Azure account/subscription, tenant and suitable developer role as prerequisites. [App registration](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app)
2. For a user-run local Python process, use MSAL `PublicClientApplication`, without a client secret. Register a Mobile and desktop application redirect URI of `http://localhost`; `acquire_token_interactive` uses the browser and provides PKCE protection. Device-code flow is an alternative for a browserless process and still requires the user to sign in. Do not collect the mailbox password. [MSAL Python acquisition](https://learn.microsoft.com/en-us/entra/msal/python/getting-started/acquiring-tokens)
3. The mailbox owner signs into Microsoft's page and reviews delegated consent. The Graph mail scopes above do not intrinsically require administrator consent, but an organization's consent policies can restrict or block user consent and require administrator review. Personal-account support does not remove this organizational policy boundary. [Graph permissions](https://learn.microsoft.com/en-us/graph/permissions-reference), [Tenant consent policies](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/configure-user-consent)

## Graph versus SMTP/IMAP OAuth

| Route | Required connection/authentication work | Practical implications |
| --- | --- | --- |
| Graph | MSAL token acquisition, HTTPS send/read calls, Graph mail permissions | One API family for sending and reply metadata; folder delta polling supports personal and work accounts. |
| SMTP + IMAP | MSAL token acquisition plus SASL XOAUTH2 in both protocol adapters; Outlook resource scopes `https://outlook.office.com/SMTP.Send` and `https://outlook.office.com/IMAP.AccessAsUser.All`, plus offline access | Microsoft explicitly supports OAuth for both Outlook.com and Microsoft 365. It is not password login with a token pasted into the password field; adapters must perform XOAUTH2. |

Sources: [Graph sendMail](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0), [Graph delta](https://learn.microsoft.com/en-us/graph/api/message-delta?view=graph-rest-1.0), [SMTP/IMAP OAuth](https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth).

Exchange Online SMTP AUTH can also be disabled at organization/mailbox level; Microsoft's guidance states security defaults disable it. Recommendation: do not weaken tenant-wide security settings just to accommodate this agent; use Graph where permitted. The recommendation is an engineering judgment, not a Microsoft mandate. [SMTP AUTH controls](https://learn.microsoft.com/en-us/exchange/clients-and-mobile-in-exchange-online/authenticated-client-smtp-submission)

## Local token safety and unattended limits

- MSAL's default cache is in memory; `SerializableTokenCache` alone does not persist it. MSAL Extensions supplies encrypted persistence and locking; Windows uses DPAPI. Keep the cache outside the repository, restrict access to the runtime user, and never put tokens in logs, prompts or `.env` files. Those placement rules are project recommendations based on the cache containing credentials. [MSAL cache](https://learn.microsoft.com/en-us/python/api/msal/msal.token_cache?view=msal-py-latest), [Microsoft's persistence library](https://github.com/AzureAD/microsoft-authentication-extensions-for-python)
- Use silent token acquisition from the cache, then ask the owner to reconnect when interaction is required. Refresh tokens are not permanent authorization: Microsoft documents a default 90-day lifetime for non-SPA scenarios and possible earlier revocation. They must be protected like credentials. Never promise indefinitely unattended operation. [Token acquisition](https://learn.microsoft.com/en-us/entra/msal/python/getting-started/acquiring-tokens), [Refresh tokens](https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens)

## Reply correlation and delivery limits

- Graph exposes `internetMessageId`, `conversationId` and `internetMessageHeaders` (headers require `$select`). Suggested design: retain the sent Internet Message-ID, match incoming In-Reply-To/References against known outbound IDs and verify the expected correspondent before importing a reply body. Conversation ID alone should not authorize actions. The matching policy is an application recommendation based on the available fields. [Message properties](https://learn.microsoft.com/en-us/graph/api/resources/message?view=graph-rest-1.0)
- `sendMail` returns `202 Accepted` with no body, not a sent message ID or proof of delivery. Correlation needs a deliberate sent-message reconciliation strategy; do not assume the API returns the outgoing Internet Message-ID. Delivery remains subject to Exchange limits and throttling. [sendMail response](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0)
- A local process can poll folder delta queries and persist the returned continuation/delta links; no public webhook endpoint is needed for that polling design. Delta is per folder, so Inbox-only monitoring misses replies moved elsewhere. Fetch only necessary fields and consider rules/moves when choosing watched folders. [Message delta](https://learn.microsoft.com/en-us/graph/api/message-delta?view=graph-rest-1.0)

An authenticated connection is not permission to send autonomous outreach: preserve the project's separate draft review, recipient approval and explicit send controls.
