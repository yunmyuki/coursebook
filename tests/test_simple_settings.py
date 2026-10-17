"""OCR/text separation, encrypted-key retention and legacy settings migration."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from course_compiler.storage import Store, atomic_json


class SimpleSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.defaults = patch('course_compiler.storage.local_settings', return_value={})
        self.defaults.start()
        self.addCleanup(self.defaults.stop)
        self.store = Store(self.temp.name)

    def test_simple_keys_are_separate_and_assistant_follows_text(self):
        s = self.store.settings()
        s['profiles']['parse']['apiKey'] = 'ocr-test-secret'
        s['profiles']['translation']['apiKey'] = 'text-test-secret'
        s['profiles']['explanation']['apiKey'] = 'obsolete-assistant-secret'
        public = self.store.save_settings(s)
        profiles = self.store.profiles()
        self.assertEqual(profiles['parse']['apiKey'], 'ocr-test-secret')
        for role in ('translation', 'explanation'):
            self.assertEqual(profiles[role]['apiKey'], 'text-test-secret')
            self.assertNotIn('OCR', profiles[role]['model'])
        self.assertNotIn('test-secret', json.dumps(public))
        self.assertNotIn('test-secret', (Path(self.temp.name)/'settings.json').read_text())
        # A masked, blank-key save must retain the two independent keys.
        self.store.save_settings(public)
        self.assertEqual(self.store.profiles(), profiles)
        # Endpoint changes clear both shared text credentials, not the OCR key.
        public['profiles']['translation']['baseUrl'] = 'https://example.invalid/v1'
        self.store.save_settings(public)
        self.assertEqual(self.store.profiles()['explanation']['apiKey'], '')
        self.assertEqual(self.store.profiles()['parse']['apiKey'], 'ocr-test-secret')

    def test_legacy_simple_migrates_without_losing_key(self):
        s = self.store.settings()
        s['settingsMode'] = 'advanced'
        s['profiles']['parse'] = {**s['profiles']['translation'], 'apiKey':'legacy-test-secret'}
        s['profiles']['translation'] = {'inherit':True}
        s['profiles']['explanation'] = {'inherit':True}
        self.store.save_settings(s)
        path = Path(self.temp.name)/'settings.json'
        raw = json.loads(path.read_text()); raw['settingsMode'] = 'simple'
        atomic_json(path, raw)
        public = self.store.settings(public=True)
        self.assertFalse(public['profiles']['translation']['inherit'])
        self.assertTrue(public['profiles']['translation']['hasApiKey'])
        self.store.save_settings(public)
        self.assertEqual(self.store.profiles()['explanation']['apiKey'], 'legacy-test-secret')

    def test_simple_rejects_ocr_for_text_and_preserves_previous_settings(self):
        s = self.store.settings()
        self.store.save_settings(s)
        before = (Path(self.temp.name)/'settings.json').read_bytes()
        for invalid in ({'inherit':True}, s['profiles']['parse'],
                        {**s['profiles']['translation'], 'model':'zai-org/GLM-OCR'}):
            bad = copy.deepcopy(s); bad['profiles']['translation'] = invalid
            with self.assertRaises(ValueError): self.store.save_settings(bad)
            self.assertEqual((Path(self.temp.name)/'settings.json').read_bytes(), before)

    def test_advanced_keeps_independent_assistant(self):
        s = self.store.settings(); s['settingsMode'] = 'advanced'
        s['profiles']['explanation']['model'] = 'assistant-custom'
        s['profiles']['explanation']['apiKey'] = 'assistant-test-secret'
        self.store.save_settings(s)
        self.assertEqual(self.store.profiles()['explanation']['model'], 'assistant-custom')
        self.assertEqual(self.store.profiles()['explanation']['apiKey'], 'assistant-test-secret')

if __name__ == '__main__': unittest.main()
