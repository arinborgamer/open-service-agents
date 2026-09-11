"""Personal Outlook OAuth. No passwords, client secrets or plaintext token cache."""
import os
import sys
import uuid
from pathlib import Path
from .models import email

SMTP_SCOPE = 'https://outlook.office.com/SMTP.Send'
IMAP_SCOPE = 'https://outlook.office.com/IMAP.AccessAsUser.All'
AUTHORITY = 'https://login.microsoftonline.com/consumers'


def client_id():
    try:
        return str(uuid.UUID(os.environ.get('OSA_MICROSOFT_CLIENT_ID', '')))
    except (ValueError, AttributeError):
        raise ValueError('Set OSA_MICROSOFT_CLIENT_ID to your Microsoft public-client app ID. See docs/OUTLOOK.md.') from None


def cache_path():
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local')))
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library/Application Support'
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    location = (base / 'OpenServiceAgents/MicrosoftAuth' / (client_id() + '.bin')).resolve()
    # Never let an environment override move credentials into this source checkout.
    if location.is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError('The encrypted Microsoft cache must be outside the repository.')
    return location


def status():
    try:
        present = cache_path().is_file()
        configured = True
    except ValueError:
        present, configured = False, False
    return {'client_configured': configured, 'cache_present': present,
            'authorization_verified': False, 'note': 'A cache file is not proof of valid authorization. Workers never open a login prompt.'}


def _client():
    try:
        import msal
        from msal_extensions import PersistedTokenCache, build_encrypted_persistence
    except ImportError:
        raise ValueError('Install Outlook support: pip install -e ".[outlook]"') from None
    location = cache_path()
    location.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        persistence = build_encrypted_persistence(str(location))
        if not persistence.is_encrypted:
            raise RuntimeError('Encryption required')
        return msal.PublicClientApplication(client_id(), authority=AUTHORITY,
                                           token_cache=PersistedTokenCache(persistence))
    except Exception:
        raise ValueError('Microsoft authentication initialization failed. OS-encrypted storage and access to Microsoft are required; plaintext fallback is disabled.') from None


def access_token(user, scope):
    if scope not in (SMTP_SCOPE, IMAP_SCOPE):
        raise ValueError('Unsupported Microsoft permission.')
    user = email(user)
    app = _client()
    try:
        accounts = [a for a in app.get_accounts(username=user)
                    if str(a.get('username', '')).lower() == user]
        if len(accounts) != 1:
            raise ValueError()
        result = app.acquire_token_silent([scope], account=accounts[0])
        token = (result or {}).get('access_token')
        if not isinstance(token, str) or not token or any(c.isspace() or ord(c) < 32 for c in token):
            raise ValueError()
        return token
    except Exception:
        raise ValueError('Microsoft sign-in is required for this mailbox/permission. Run osa outlook-connect locally; no message was submitted.') from None


def connect(with_inbox=False):
    if os.environ.get('OSA_MAIL_ENABLED') == 'true' or os.environ.get('OSA_IMAP_ENABLED') == 'true':
        raise ValueError('Disable mail and inbox workers before connecting, then restart them after verification.')
    user = email(os.environ.get('OSA_FROM_EMAIL', ''))
    scopes = [SMTP_SCOPE] + ([IMAP_SCOPE] if with_inbox else [])
    app = _client()
    try:
        # Public client, browser login with PKCE. MSAL adds standard OIDC/offline scopes.
        result = app.acquire_token_interactive(scopes=scopes, login_hint=user,
                                               prompt='select_account', timeout=180)
        accounts = [a for a in app.get_accounts(username=user)
                    if str(a.get('username', '')).lower() == user]
        actual_user = str((result or {}).get('id_token_claims', {}).get('preferred_username', '')).lower()
        if not isinstance(result, dict) or not result.get('access_token') or len(accounts) != 1 or actual_user != user:
            raise ValueError()
    except Exception:
        raise ValueError('Microsoft sign-in did not complete for the configured mailbox. Check app registration and the selected account. No sending was enabled.') from None
    return {'authenticated': True, 'inbox_permission_requested': with_inbox,
            'sending_enabled': False, 'note': 'No email sent. Authorization may later expire or be revoked.'}


def validate_endpoint(protocol, host, port, user):
    endpoints = {'smtp': ('smtp-mail.outlook.com', 587), 'imap': ('outlook.office365.com', 993)}
    if protocol not in endpoints or (host.lower(), int(port)) != endpoints[protocol]:
        raise ValueError('Microsoft OAuth tokens may only be sent to the documented personal Outlook endpoint and TLS port.')
    if email(user) != email(os.environ.get('OSA_FROM_EMAIL', '')):
        raise ValueError('Outlook login and sender must match the same primary mailbox; arbitrary From aliases are not supported.')


def xoauth2(user, token):
    if not isinstance(token, str) or not token or any(c.isspace() or ord(c) < 32 for c in token):
        raise ValueError('Invalid Microsoft token.')
    return f'user={email(user)}\x01auth=Bearer {token}\x01\x01'


def verify():
    """Check SMTP authentication without MAIL/RCPT/DATA or reading the inbox."""
    import smtplib
    import ssl
    user = email(os.environ.get('OSA_FROM_EMAIL', ''))
    auth = xoauth2(user, access_token(user, SMTP_SCOPE))
    try:
        with smtplib.SMTP('smtp-mail.outlook.com', 587, timeout=30) as client:
            client.starttls(context=ssl.create_default_context())
            client.auth('XOAUTH2', lambda challenge=None: auth if challenge is None else '')
            if client.noop()[0] != 250:
                raise ValueError()
    except Exception:
        raise ValueError('Outlook SMTP verification failed. No email was submitted. Check Microsoft account/protocol settings.') from None
    return {'smtp_authenticated': True, 'email_submitted': False,
            'note': 'Authentication succeeded; recipient delivery has not been tested.'}
