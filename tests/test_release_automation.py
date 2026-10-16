import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from automate_release import scan_source,isolated_source_copy
from assemble_release import create,assemble
import zipfile

class ReleaseAutomationTests(unittest.TestCase):
    def test_public_source_is_not_modified_by_fixture_side_effects(self):
        with tempfile.TemporaryDirectory(dir='tmp') as folder:
            root=Path(folder);source=root/'source';source.mkdir();(source/'README.md').write_text('Public')
            test=isolated_source_copy(source,root/'test');(test/'.course-cache').mkdir();(test/'.course-cache/data.json').write_text('{}')
            self.assertFalse((source/'.course-cache').exists());self.assertTrue(scan_source(source)['ok'])

    def test_secret_pattern_scan_reports_paths_not_values(self):
        with tempfile.TemporaryDirectory(dir='tmp') as folder:
            root=Path(folder);(root/'safe.py').write_text('x = 1')
            self.assertTrue(scan_source(root)['ok'])
            (root/'bad.txt').write_text('sk-'+('A'*32))
            with self.assertRaises(RuntimeError) as error:scan_source(root)
            self.assertIn('bad.txt',str(error.exception));self.assertNotIn('A'*32,str(error.exception))

    def test_private_settings_never_staged(self):
        with tempfile.TemporaryDirectory(dir='tmp') as folder:
            root=Path(folder);(root/'settings.json').write_text('{}')
            with self.assertRaises(ValueError):scan_source(root)

    def test_archive_reuse_produces_exact_new_bytes(self):
        with tempfile.TemporaryDirectory(dir='tmp') as folder:
            root=Path(folder);base=root/'base.zip';target=root/'target.zip';recipe=root/'recipe'
            for file,value in ((base,'old'),(target,'new')):
                with zipfile.ZipFile(file,'w',zipfile.ZIP_DEFLATED) as z:
                    z.writestr('Coursebook/runtime.bin',b'unchanged'*1000);z.writestr('Coursebook/version.txt',value)
            create([base],[target],recipe)
            import shutil
            shutil.copy2(base,recipe/base.name)
            assemble(recipe/'assembly-manifest.json',recipe,root/'rebuilt')
            self.assertEqual((root/'rebuilt/target.zip').read_bytes(),target.read_bytes())
            (recipe/base.name).write_bytes(b'corrupt')
            with self.assertRaises(ValueError):assemble(recipe/'assembly-manifest.json',recipe,root/'bad-output')
