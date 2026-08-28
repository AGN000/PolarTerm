import json
import os
from dataclasses import dataclass, asdict
from typing import List, Optional

import platform as _plat
if _plat.system() == "Windows":
    _base = os.environ.get("APPDATA", os.path.expanduser("~"))
    CONFIG_DIR = os.path.join(_base, "polarterm")
else:
    CONFIG_DIR = os.path.expanduser("~/.config/polarterm")
CONFIG_FILE = os.path.join(CONFIG_DIR, "sessions.json")

# encryption helper - lazy import to avoid hard dep if cryptography missing
try:
    from utils.crypto import encrypt_str, decrypt_str
except ImportError:
    try:
        from PolarTerm.utils.crypto import encrypt_str, decrypt_str
    except:
        def encrypt_str(s): return s
        def decrypt_str(s): return s

@dataclass
class Session:
    name: str
    host: str
    port: int = 22
    username: str = ""
    auth_method: str = "password"  # password | key
    password: str = ""  # stored only if user opts (insecure)
    key_path: str = ""
    key_passphrase: str = ""
    remote_path: str = "~"
    local_path: str = ""
    save_password: bool = False
    jump_host: str = ""  # optional jump/bastion host e.g. "user@host:port"
    notes: str = ""

    def display(self):
        return f"{self.name} ({self.username}@{self.host}:{self.port})"

def _ensure_dir():
    # migrate from old mobaxtreme config if exists
    old_dir = os.path.expanduser("~/.config/mobaxtreme")
    if os.path.exists(old_dir) and not os.path.exists(CONFIG_DIR):
        try:
            import shutil
            shutil.copytree(old_dir, CONFIG_DIR)
        except: 
            os.makedirs(CONFIG_DIR, exist_ok=True)
    else:
        os.makedirs(CONFIG_DIR, exist_ok=True)

def load_sessions() -> List[Session]:
    _ensure_dir()
    if not os.path.exists(CONFIG_FILE):
        return []
    try:
        with open(CONFIG_FILE, 'r') as f:
            data = json.load(f)
        out = []
        for s in data:
            # decrypt stored values (backward compatible with plain)
            if s.get("password"):
                s["password"] = decrypt_str(s["password"])
            if s.get("key_passphrase"):
                s["key_passphrase"] = decrypt_str(s["key_passphrase"])
            out.append(Session(**s))
        return out
    except Exception as e:
        print(f"[config] load error: {e}")
        return []

def save_sessions(sessions: List[Session]):
    _ensure_dir()
    data = [asdict(s) for s in sessions]
    for d, s in zip(data, sessions):
        if not s.save_password:
            d["password"] = ""
            d["key_passphrase"] = ""
        else:
            # encrypt before storing - never store plain
            if d.get("password"):
                # avoid double-encrypt if already encrypted
                if not d["password"].startswith("enc:") and not d["password"].startswith("b64:"):
                    d["password"] = encrypt_str(d["password"])
            if d.get("key_passphrase"):
                if d["key_passphrase"] and not d["key_passphrase"].startswith("enc:") and not d["key_passphrase"].startswith("b64:"):
                    d["key_passphrase"] = encrypt_str(d["key_passphrase"])
    with open(CONFIG_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    # ensure private perms
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except: pass

def add_or_update_session(session: Session):
    sessions = load_sessions()
    for i, s in enumerate(sessions):
        if s.name == session.name:
            sessions[i] = session
            save_sessions(sessions)
            return
    sessions.append(session)
    save_sessions(sessions)

def delete_session(name: str):
    sessions = [s for s in load_sessions() if s.name != name]
    save_sessions(sessions)

# --- Bookmarks ---
BOOKMARK_FILE = os.path.join(CONFIG_DIR, "bookmarks.json")

@dataclass
class Bookmark:
    alias: str
    path: str
    session: str = ""  # optional session name, empty = global (works for any host)
    kind: str = "remote"  # remote or local

def load_bookmarks() -> List[Bookmark]:
    _ensure_dir()
    if not os.path.exists(BOOKMARK_FILE):
        return []
    try:
        with open(BOOKMARK_FILE, 'r') as f:
            data = json.load(f)
        return [Bookmark(**b) for b in data]
    except: return []

def save_bookmarks(bms: List[Bookmark]):
    _ensure_dir()
    with open(BOOKMARK_FILE, 'w') as f:
        json.dump([asdict(b) for b in bms], f, indent=2)
    try: os.chmod(BOOKMARK_FILE, 0o600)
    except: pass

def add_bookmark(bm: Bookmark):
    bms = load_bookmarks()
    # update if alias exists
    for i, b in enumerate(bms):
        if b.alias == bm.alias and b.session == bm.session:
            bms[i] = bm
            save_bookmarks(bms)
            return
    bms.append(bm)
    save_bookmarks(bms)

def delete_bookmark(alias: str, session: str = ""):
    bms = [b for b in load_bookmarks() if not (b.alias == alias and b.session == session)]
    save_bookmarks(bms)
