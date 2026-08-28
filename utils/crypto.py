import os
import base64
import hashlib
from pathlib import Path

import platform as _plat
if _plat.system() == "Windows":
    _base = os.environ.get("APPDATA", os.path.expanduser("~"))
    CONFIG_DIR = os.path.join(_base, "polarterm")
else:
    CONFIG_DIR = os.path.expanduser("~/.config/polarterm")
KEY_FILE = os.path.join(CONFIG_DIR, ".key")

def _get_key() -> bytes:
    """Get or create a Fernet key stored in ~/.config/mobaxtreme/.key
    Key is derived from machine-specific data + random, 0600 perms.
    """
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if os.path.exists(KEY_FILE):
        try:
            with open(KEY_FILE, "rb") as f:
                key = f.read().strip()
            # validate
            if len(key) == 44:  # base64 encoded 32 bytes
                return key
        except:
            pass
    # generate new key
    from cryptography.fernet import Fernet
    key = Fernet.generate_key()
    try:
        with open(KEY_FILE, "wb") as f:
            f.write(key)
        os.chmod(KEY_FILE, 0o600)
    except Exception as e:
        print(f"[crypto] failed to save key: {e}")
    return key

def encrypt_str(plain: str) -> str:
    if not plain:
        return ""
    try:
        from cryptography.fernet import Fernet
        key = _get_key()
        f = Fernet(key)
        token = f.encrypt(plain.encode("utf-8"))
        return "enc:" + token.decode("utf-8")
    except Exception as e:
        print(f"[crypto] encrypt failed: {e}")
        # fallback: base64 obfuscation (not secure but hides plain)
        return "b64:" + base64.b64encode(plain.encode()).decode()

def decrypt_str(token: str) -> str:
    if not token:
        return ""
    if token.startswith("enc:"):
        try:
            from cryptography.fernet import Fernet
            key = _get_key()
            f = Fernet(key)
            return f.decrypt(token[4:].encode("utf-8")).decode("utf-8")
        except Exception as e:
            print(f"[crypto] decrypt failed: {e}")
            return ""
    if token.startswith("b64:"):
        try:
            return base64.b64decode(token[4:].encode()).decode()
        except:
            return ""
    # legacy plain text (from old sessions.json)
    return token

def is_encrypted(s: str) -> bool:
    return s.startswith("enc:") or s.startswith("b64:")
