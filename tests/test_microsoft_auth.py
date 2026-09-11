import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace
from open_service_agents import microsoft_auth as auth, mail, campaigns
from open_service_agents.storage import Store


class MicrosoftTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        env = patch.dict(os.environ, {
            'OSA_FROM_EMAIL': 'fixture@outlook.com', 'OSA_SMTP_USER': 'fixture@outlook.com',
            'OSA_SMTP_HOST': 'smtp-mail.outlook.com', 'OSA_SMTP_PORT': '587',
            'OSA_SMTP_PASSWORD': '', 'OSA_MAIL_AUTH': 'microsoft', 'OSA_MAIL_ENABLED': 'false',
            'OSA_IMAP_AUTH': 'microsoft', 'OSA_IMAP_ENABLED': 'false',
            'OSA_IMAP_HOST': 'outlook.office365.com', 'OSA_IMAP_PORT': '993',
            'OSA_IMAP_USER': 'fixture@outlook.com', 'OSA_IMAP_PASSWORD': '',
            'OSA_MICROSOFT_CLIENT_ID': '11111111-1111-4111-8111-111111111111'})
        env.start(); self.addCleanup(env.stop)

    def approved(self):
        mid = mail.draft(self.store, 'recipient@example.com', 'Fixture', 'Private test body', 'Explicit test request')
        mail.approve(self.store, mid)
        return mid

    def test_status_does_not_read_cache_or_call_microsoft(self):
        with patch.object(auth, '_client') as client:
            result = auth.status()
        client.assert_not_called()
        self.assertFalse(result['authorization_verified'])
        self.assertNotIn('fixture@outlook.com', str(result))

    def test_scope_and_endpoint_are_restricted(self):
        with patch.object(auth, '_client') as client:
            with self.assertRaises(ValueError): auth.access_token('fixture@outlook.com', 'Mail.ReadWrite')
            client.assert_not_called()
        for host, port, user in [('evil.example',587,'fixture@outlook.com'),
                                 ('smtp-mail.outlook.com',25,'fixture@outlook.com'),
                                 ('smtp-mail.outlook.com',587,'other@outlook.com')]:
            with self.assertRaises(ValueError): auth.validate_endpoint('smtp',host,port,user)

    def test_silent_token_only_uses_expected_account(self):
        app = Mock()
        account = {'username': 'fixture@outlook.com'}
        app.get_accounts.return_value = [account]
        app.acquire_token_silent.return_value = {'access_token': 'fixture-token'}
        with patch.object(auth, '_client', return_value=app):
            self.assertEqual(auth.access_token('fixture@outlook.com', auth.SMTP_SCOPE), 'fixture-token')
        app.acquire_token_silent.assert_called_once_with([auth.SMTP_SCOPE], account=account)
        app.acquire_token_interactive.assert_not_called()
        app.get_accounts.return_value = [{'username': 'other@outlook.com'}]
        with patch.object(auth, '_client', return_value=app):
            with self.assertRaises(ValueError): auth.access_token('fixture@outlook.com', auth.SMTP_SCOPE)

    def test_revoked_auth_does_not_claim_mail_or_expose_provider_errors(self):
        mid = self.approved()
        app = Mock()
        app.get_accounts.return_value = [{'username':'fixture@outlook.com'}]
        app.acquire_token_silent.return_value = {'error_description':'sensitive-provider-response'}
        with patch.dict(os.environ, {'OSA_MAIL_ENABLED':'true'}), patch.object(auth, '_client', return_value=app), patch('smtplib.SMTP') as smtp:
            with self.assertRaises(ValueError) as err: mail.send_one(self.store)
            self.assertNotIn('sensitive-provider-response', str(err.exception)); smtp.assert_not_called()
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM mail WHERE id=?',(mid,)).fetchone()[0], 'approved')

    def test_smtp_uses_xoauth2_without_password_login(self):
        self.approved()
        with patch.dict(os.environ, {'OSA_MAIL_ENABLED':'true'}), patch.object(auth, 'access_token', return_value='fixture-token'), patch('smtplib.SMTP') as smtp:
            self.assertEqual(mail.send_one(self.store)['state'], 'sent')
            client = smtp.return_value.__enter__.return_value
            client.login.assert_not_called()
            mechanism, callback = client.auth.call_args.args
            self.assertEqual(mechanism, 'XOAUTH2')
            self.assertEqual(callback(), 'user=fixture@outlook.com\x01auth=Bearer fixture-token\x01\x01')
            self.assertEqual(callback(b'failure'), '')
            client.starttls.assert_called_once(); client.send_message.assert_called_once()

    def test_connect_does_not_enable_workers_or_request_inbox_by_default(self):
        app = Mock()
        app.acquire_token_interactive.return_value = {'access_token':'fixture-token','id_token_claims':{'preferred_username':'fixture@outlook.com'}}
        app.get_accounts.return_value = [{'username':'fixture@outlook.com'}]
        with patch.object(auth, '_client', return_value=app):
            result = auth.connect()
        self.assertFalse(result['sending_enabled'])
        self.assertEqual(app.acquire_token_interactive.call_args.kwargs['scopes'], [auth.SMTP_SCOPE])
        self.assertEqual(os.environ['OSA_MAIL_ENABLED'], 'false')
        app.acquire_token_interactive.return_value['id_token_claims']['preferred_username'] = 'wrong@outlook.com'
        with patch.object(auth, '_client', return_value=app):
            with self.assertRaises(ValueError): auth.connect()

    def test_connect_requires_paused_workers(self):
        with patch.dict(os.environ, {'OSA_MAIL_ENABLED':'true'}), patch.object(auth, '_client') as client:
            with self.assertRaises(ValueError): auth.connect()
            client.assert_not_called()

    def test_plaintext_persistence_is_rejected(self):
        fake_msal = Mock()
        persistence = Mock(is_encrypted=False)
        extensions = SimpleNamespace(PersistedTokenCache=Mock(), build_encrypted_persistence=Mock(return_value=persistence))
        with patch.dict('sys.modules', {'msal':fake_msal,'msal_extensions':extensions}), patch.object(auth, 'cache_path', return_value=Path(self.tmp.name)/'auth.bin'):
            with self.assertRaises(ValueError): auth._client()
        fake_msal.PublicClientApplication.assert_not_called()
        extensions.PersistedTokenCache.assert_not_called()

    def test_inbox_permission_is_explicit(self):
        app = Mock()
        app.acquire_token_interactive.return_value = {'access_token':'fixture-token','id_token_claims':{'preferred_username':'fixture@outlook.com'}}
        app.get_accounts.return_value = [{'username':'fixture@outlook.com'}]
        with patch.object(auth, '_client', return_value=app):
            self.assertTrue(auth.connect(with_inbox=True)['inbox_permission_requested'])
        self.assertEqual(app.acquire_token_interactive.call_args.kwargs['scopes'], [auth.SMTP_SCOPE, auth.IMAP_SCOPE])

    def test_verification_never_sends_mail(self):
        with patch.object(auth, 'access_token', return_value='fixture-token'), patch('smtplib.SMTP') as smtp:
            client = smtp.return_value.__enter__.return_value
            client.noop.return_value = (250, b'OK')
            self.assertFalse(auth.verify()['email_submitted'])
            client.send_message.assert_not_called(); client.sendmail.assert_not_called()

    def test_imap_oauth_remains_read_only(self):
        with patch.dict(os.environ, {'OSA_IMAP_ENABLED':'true'}), patch.object(auth, 'access_token', return_value='fixture-token'), patch('imaplib.IMAP4_SSL') as imap:
            client = imap.return_value.__enter__.return_value
            client.select.return_value = ('OK', [])
            client.response.return_value = ('UIDVALIDITY', [b'123'])
            client.uid.return_value = ('OK', [b''])
            self.assertEqual(campaigns.sync_inbox(self.store)['imported'], 0)
            client.login.assert_not_called()
            mechanism, callback = client.authenticate.call_args.args
            self.assertEqual(mechanism, 'XOAUTH2')
            self.assertIn(b'fixture-token', callback(b''))
            self.assertEqual(callback(b'failure'), b'')
            client.select.assert_called_once_with('"INBOX"', readonly=True)


if __name__ == '__main__':
    unittest.main()
