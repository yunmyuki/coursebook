"""Encrypt settings with a master key held exclusively in macOS Keychain."""
import threading

_lock=threading.Lock()
SERVICE='com.coursebook.desktop'
ACCOUNT='settings-encryption-v1'

def protect_key(text,decode=False):
    from cryptography.fernet import Fernet,InvalidToken
    from keyring.backends.macOS import Keyring
    try:
        with _lock:
            backend=Keyring()
            key=backend.get_password(SERVICE,ACCOUNT)
            if not key:
                if decode:raise ValueError('macOS 钥匙串中的密钥不存在，请重新填写 API Key。')
                key=Fernet.generate_key().decode('ascii')
                backend.set_password(SERVICE,ACCOUNT,key)
            cipher=Fernet(key.encode('ascii'))
        if decode:
            if not text.startswith('keychain-v1:'):raise ValueError('此密钥来自其他系统，请重新填写 API Key。')
            return cipher.decrypt(text.removeprefix('keychain-v1:').encode('ascii')).decode('utf-8')
        return 'keychain-v1:'+cipher.encrypt(text.encode('utf-8')).decode('ascii')
    except Exception as exc:
        raise ValueError('无法访问 macOS 钥匙串或解密 API Key，请解锁钥匙串后重试。') from exc
