import tempfile,unittest,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from audit_release_privacy import private_member,audit_archive
from sign_windows import thumbprint,preflight,verify_unsigned
from course_compiler.storage import Store,atomic_json
import zipfile

class WorkspacePrivacyTests(unittest.TestCase):
    def test_workspace_identity_and_notes_are_scoped(self):
        with tempfile.TemporaryDirectory(dir='tmp') as folder:
            a=Store(Path(folder)/'a');b=Store(Path(folder)/'b');cid='course-'+'1'*16
            a.save_learning(cid,{'courseId':cid,'notes':[{'text':'Fixture note'}]})
            self.assertNotEqual(a.workspace_id,b.workspace_id)
            self.assertEqual(a.workspace_id,Store(a.root).workspace_id)
            self.assertIsNone(b.learning(cid));self.assertEqual(b.courses(),[])
            self.assertEqual(a.learning(cid)['notes'][0]['text'],'Fixture note')

    def test_browser_dependency_is_not_mistaken_for_private_profile(self):
        self.assertFalse(private_member('Coursebook/_internal/webview/js/api.js'))
        for name in ('Coursebook/webview/EBWebView/Default/Cookies','Coursebook/notes/id.json','Coursebook/_internal/library.json','Coursebook/.env.local'):
            self.assertTrue(private_member(name),name)

    def test_private_archive_member_blocks_release(self):
        with tempfile.TemporaryDirectory(dir='tmp') as folder:
            archive=Path(folder)/'release.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('Coursebook/notes/id.json','{}')
            with self.assertRaises(ValueError):audit_archive(archive)

    def test_signing_refuses_missing_or_injectable_identity(self):
        self.assertEqual(thumbprint('ab '*20),'AB'*20)
        for value in ('',"'; Write-Host wrong; '",'12'):
            with self.assertRaises(ValueError):thumbprint(value)
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaises((ValueError,RuntimeError)):preflight()

    def test_unsigned_release_cannot_accept_invalid_or_self_signed_exe(self):
        with tempfile.TemporaryDirectory(dir='tmp') as folder:
            exe=Path(folder)/'fixture.exe';exe.write_bytes(b'fixture-only')
            for status,has_signer in (('UnknownError',False),('HashMismatch',True),('NotTrusted',True),('Valid',True),('NotSigned',True)):
                with patch('sign_windows.powershell',return_value={'status':status,'hasSigner':has_signer}):
                    with self.assertRaises(RuntimeError):verify_unsigned(exe)
            with patch('sign_windows.powershell',return_value={'status':'NotSigned','hasSigner':False}):
                report=verify_unsigned(exe)
                self.assertTrue(report['unsigned']);self.assertEqual(len(report['executableSha256']),64)
