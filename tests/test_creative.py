import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import zipfile
from unittest.mock import patch

from open_service_agents import creative, exports, models, payments, quality, storefront, studio
from open_service_agents.pipeline import run_one
from open_service_agents.providers import Demo
from open_service_agents.storage import Store


class CreativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.brief = models.brief(json.loads((Path(__file__).resolve().parents[1] / 'examples/brief.json').read_text()))

    def ready(self):
        jid = self.store.enqueue(self.brief, 'demo')
        run_one(self.store)
        return jid

    def outlines(self):
        return creative.enqueue(self.store, 'outlines', {'brief': self.brief, 'provider': 'demo'})

    def revision(self, jid):
        return creative.enqueue(self.store, 'revision', {'job_id': jid, 'stage': 'chapter_1', 'provider': 'demo', 'instruction': 'Add a clearer exercise.'})

    def test_selected_outline_is_preserved_through_full_generation_and_repeat_clicks(self):
        task = self.outlines()
        self.assertEqual(self.store.jobs(), [])
        with self.assertRaises(ValueError):
            creative.select_outline(self.store, task['id'], 'field-guide')
        creative.run_one(self.store)
        saved = creative.get(self.store, task['id'])
        self.assertEqual(len(saved['result']), 3)
        selected = creative.select_outline(self.store, task['id'], 'workshop')
        self.assertEqual(selected, creative.select_outline(self.store, task['id'], 'workshop'))
        with self.assertRaises(ValueError):
            creative.select_outline(self.store, task['id'], 'missing')
        run_one(self.store)
        job = self.store.job(selected['id'])
        self.assertEqual(job['artifacts']['transformation']['body'], saved['result']['workshop']['body'])
        self.assertEqual(job['state'], 'ready')
        self.assertEqual(job['provider'], 'demo')

    def test_outline_checkpoint_survives_failure_without_regenerating_saved_choice(self):
        task = self.outlines()
        calls = []
        class FailingDemo(Demo):
            def generate(model, stage, instruction, context):
                calls.append(stage)
                if stage == 'outline_workshop':
                    raise RuntimeError('secret response must not persist')
                return super().generate(stage, instruction, context)
        with patch('open_service_agents.creative.provider', return_value=FailingDemo()):
            with self.assertRaises(RuntimeError):
                creative.run_one(self.store)
        saved = creative.get(self.store, task['id'])
        self.assertEqual(set(saved['result']), {'field-guide'})
        self.assertNotIn('secret response', saved['error'])
        with self.store.connect() as db:
            db.execute('UPDATE creative_tasks SET available=0')
        with patch.object(Demo, 'generate', autospec=True, side_effect=Demo.generate) as generate:
            creative.run_one(self.store)
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(creative.get(self.store, task['id'])['state'], 'ready')
        self.assertEqual(creative.get(self.store, task['id'])['result']['field-guide'], saved['result']['field-guide'])

    def test_creative_lease_has_one_owner_and_rejects_stale_writes(self):
        self.outlines()
        claims = []
        threads = [threading.Thread(target=lambda: claims.append(creative.claim(self.store))) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(c is not None for c in claims), 1)
        old = next(c for c in claims if c)
        with self.store.connect() as db:
            db.execute('UPDATE creative_tasks SET lease_until=0')
        creative.claim(self.store)
        with self.assertRaises(RuntimeError):
            creative.checkpoint(self.store, old, {})

    def test_retry_budget_stops_and_explicit_retry_preserves_completed_alternatives(self):
        task = self.outlines()
        with patch('open_service_agents.creative.provider', side_effect=ValueError('failure')):
            for _ in range(3):
                with self.store.connect() as db:
                    db.execute('UPDATE creative_tasks SET available=0')
                with self.assertRaises(ValueError):
                    creative.run_one(self.store)
        self.assertEqual(creative.get(self.store, task['id'])['state'], 'failed')
        self.assertIsNone(creative.run_one(self.store))
        creative.retry(self.store, task['id'])
        creative.run_one(self.store)
        self.assertEqual(creative.get(self.store, task['id'])['state'], 'ready')

    def test_revision_is_only_a_suggestion_until_applied_and_preserves_history(self):
        jid = self.ready()
        before = self.store.job(jid)['artifacts']['chapter_1']
        task = self.revision(jid)
        creative.run_one(self.store)
        self.assertEqual(self.store.job(jid)['artifacts']['chapter_1'], before)
        creative.apply_revision(self.store, task['id'])
        self.assertNotEqual(self.store.job(jid)['artifacts']['chapter_1'], before)
        self.assertEqual(creative.get(self.store, task['id'])['state'], 'applied')
        with self.store.connect() as db:
            self.assertEqual(json.loads(db.execute('SELECT previous FROM edits').fetchone()[0]), before)

    def test_stale_revision_cannot_overwrite_manual_edit(self):
        jid = self.ready()
        task = self.revision(jid)
        creative.run_one(self.store)
        manual = self.store.edit_artifact(jid, 'chapter_1', {'title': 'Manual', 'body': 'A later operator edit.', 'citations': ['S1']})
        with self.assertRaisesRegex(ValueError, 'changed'):
            creative.apply_revision(self.store, task['id'])
        self.assertEqual(self.store.job(jid)['artifacts']['chapter_1'], manual)

    def test_revision_cannot_change_an_edition_approved_while_model_was_running(self):
        jid = self.ready()
        task = self.revision(jid)
        creative.run_one(self.store)
        payments.approve_product(self.store, jid, 'original', 100)
        with self.assertRaisesRegex(ValueError, 'immutable'):
            creative.apply_revision(self.store, task['id'])
        with self.assertRaises(ValueError):
            self.revision(jid)

    def test_fork_is_editable_but_existing_approved_edition_stays_unchanged(self):
        jid = self.ready()
        payments.approve_product(self.store, jid, 'original', 100)
        original = self.store.job(jid)
        new_id = self.store.fork_draft(jid)
        self.assertNotEqual(new_id, jid)
        self.assertEqual(self.store.job(new_id)['provider'], 'demo')
        self.store.edit_artifact(new_id, 'chapter_1', {'title': 'New edition', 'body': 'Revised content', 'citations': ['S1']})
        self.assertEqual(self.store.job(jid), original)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT job_id FROM products WHERE id=?', ('original',)).fetchone()[0], jid)

    def test_model_output_cannot_cite_new_sources_or_mix_fixture_into_real_product(self):
        task = self.outlines()
        with patch.object(Demo, 'generate', return_value={'title': 'Bad', 'body': 'Invalid', 'citations': ['S999']}):
            with self.assertRaises(ValueError):
                creative.run_one(self.store)
        self.assertEqual(creative.get(self.store, task['id'])['result'], {})
        jid = self.ready()
        with self.store.connect() as db:
            db.execute("UPDATE jobs SET provider='ollama' WHERE id=?", (jid,))
        with self.assertRaisesRegex(ValueError, 'match'):
            self.revision(jid)

    def test_quality_report_flags_duplicate_chapters_placeholders_and_missing_sections(self):
        job = self.store.job(self.ready())
        report = quality.report(job)
        self.assertEqual(report['expected_chapters'], 3)
        self.assertEqual(report['sources'][0]['chapters'], ['chapter_1', 'chapter_2', 'chapter_3'])
        self.assertTrue(any('repeats' in f['message'] for f in report['findings']))
        job['artifacts']['chapter_1']['body'] = '[insert example here]'
        del job['artifacts']['chapter_3']
        findings = quality.report(job)['findings']
        self.assertTrue(any('placeholder' in f['message'] for f in findings))
        self.assertTrue(any('missing' in f['message'] for f in findings))

    def test_templates_use_actual_product_without_saving_publishing_or_contact_details(self):
        jid = self.ready()
        payments.approve_product(self.store, jid, 'original', 100)
        for option in storefront.TEMPLATES:
            result = storefront.template(self.store, 'original', option['id'])
            self.assertEqual(result['headline'], self.brief['topic'])
            self.assertIn('Chapter 1', str(result['blocks']))
            self.assertFalse(result['published'])
            self.assertNotIn('support_email', result)
        self.assertEqual(studio.get(self.store, '/v1/storefronts'), [])
        with self.assertRaises(ValueError):
            storefront.template(self.store, 'original', 'invented')

    def test_pdf_disabled_is_explicit_in_archive_manifest(self):
        job = self.store.job(self.ready())
        with patch('open_service_agents.exports.pdf_available', return_value=False):
            archive = zipfile.ZipFile(io.BytesIO(exports.bundle(job)))
        manifest = json.loads(archive.read('CONTENTS.json'))
        self.assertEqual(manifest['edition_id'], job['id'])
        self.assertNotIn('PDF', manifest['formats'])
        self.assertIn(b'not included', archive.read('README.txt'))

    @unittest.skipUnless(exports.pdf_available(), 'Optional PDF dependency is not installed')
    def test_pdf_in_customer_archive_uses_current_edition_without_private_notes(self):
        jid = self.ready()
        self.store.edit_artifact(jid, 'chapter_1', {'title': 'Updated chapter', 'body': 'Updated edition example.', 'citations': ['S1']})
        archive = zipfile.ZipFile(io.BytesIO(exports.bundle(self.store.job(jid))))
        self.assertTrue(archive.read('product.pdf').startswith(b'%PDF-'))
        self.assertIn('PDF', json.loads(archive.read('CONTENTS.json'))['formats'])
        self.assertIn(b'Updated edition example', archive.read('product.md'))
        self.assertNotIn('brief.json', archive.namelist())


if __name__ == '__main__':
    unittest.main()
