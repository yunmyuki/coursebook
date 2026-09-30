import sys,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from cryptography.fernet import Fernet
from course_compiler.mac_security import protect_key
from course_compiler.paths import data_root

class MacTests(unittest.TestCase):
    def test_keychain_roundtrip_and_tampering(self):
        backend=MagicMock();backend.get_password.return_value=Fernet.generate_key().decode()
        module=MagicMock();module.Keyring.return_value=backend
        with patch.dict(sys.modules,{'keyring.backends.macOS':module}):
            encrypted=protect_key('fixture-key')
            self.assertNotIn('fixture-key',encrypted)
            self.assertEqual(protect_key(encrypted,True),'fixture-key')
            with self.assertRaises(ValueError):protect_key(encrypted[:-5]+'wrong',True)
    def test_missing_key_never_regenerated_on_read(self):
        backend=MagicMock();backend.get_password.return_value=None
        module=MagicMock();module.Keyring.return_value=backend
        with patch.dict(sys.modules,{'keyring.backends.macOS':module}):
            with self.assertRaises(ValueError):protect_key('keychain-v1:missing',True)
            backend.set_password.assert_not_called()
    def test_frozen_mac_data_outside_app(self):
        with patch('sys.platform','darwin'),patch('sys.frozen',True,create=True),patch.dict('os.environ',{'COURSE_DATA_DIR':''}):
            self.assertEqual(data_root(),Path.home()/'Library/Application Support/Coursebook')

if __name__=='__main__':unittest.main()
