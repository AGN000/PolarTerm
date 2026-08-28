import os
import time
import hashlib
import subprocess
import tempfile
from PyQt6.QtCore import QObject, QTimer, QFileSystemWatcher, pyqtSignal

import platform as _plat
if _plat.system() == "Windows":
    CACHE_DIR = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")), "polarterm", "edit")
else:
    CACHE_DIR = os.path.expanduser("~/.cache/polarterm/edit")

def _sanitize_remote(remote_path: str) -> str:
    return remote_path.replace("/", "_").replace("\\", "_").replace(":", "_")

class RemoteEditWatcher(QObject):
    uploaded = pyqtSignal(str, bool, str)  # remote_path, success, msg
    def __init__(self, ssh_wrapper, remote_path, local_tmp, parent=None):
        super().__init__(parent)
        self.ssh = ssh_wrapper
        self.remote_path = remote_path
        self.local_tmp = local_tmp
        self.last_mtime = os.path.getmtime(local_tmp) if os.path.exists(local_tmp) else 0
        self.last_hash = self._hash()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check)
        self.timer.start(1500)  # poll every 1.5s
        self.watcher = QFileSystemWatcher([local_tmp], self)
        self.watcher.fileChanged.connect(lambda _: QTimer.singleShot(500, self.check))

    def _hash(self):
        try:
            with open(self.local_tmp, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()
        except:
            return ""

    def check(self):
        if not os.path.exists(self.local_tmp):
            return
        try:
            cur_hash = self._hash()
            if cur_hash != self.last_hash:
                self.last_hash = cur_hash
                # file changed - upload
                self.upload()
        except Exception as e:
            print(f"[remote_edit] check error: {e}")

    def upload(self):
        try:
            # ensure ssh still connected
            if not self.ssh or not self.ssh.connected or not self.ssh.sftp:
                self.uploaded.emit(self.remote_path, False, "SSH disconnected")
                return
            self.ssh.sftp_put(self.local_tmp, self.remote_path)
            self.uploaded.emit(self.remote_path, True, "Auto-uploaded")
        except Exception as e:
            self.uploaded.emit(self.remote_path, False, str(e))

    def stop(self):
        self.timer.stop()
        try:
            self.watcher.removePaths(self.watcher.files())
        except: pass

def get_tmp_for_remote(host, remote_path):
    os.makedirs(CACHE_DIR, exist_ok=True)
    base = os.path.basename(remote_path)
    # create host-specific subdir to avoid collisions
    safe_host = host.replace(":", "_").replace("/", "_")
    host_dir = os.path.join(CACHE_DIR, safe_host)
    os.makedirs(host_dir, exist_ok=True)
    tmp = os.path.join(host_dir, base)
    # if same basename exists for different remote dir, add hash prefix
    if os.path.exists(tmp):
        # check if existing tmp is for same remote_path? we track via .meta
        meta = tmp + ".meta"
        if os.path.exists(meta):
            with open(meta) as f:
                old = f.read().strip()
            if old != remote_path:
                # collision - add hash
                h = hashlib.md5(remote_path.encode()).hexdigest()[:6]
                tmp = os.path.join(host_dir, f"{h}_{base}")
    # write meta
    try:
        with open(tmp + ".meta", "w") as f:
            f.write(remote_path)
    except: pass
    return tmp

def open_with_local_app(local_path):
    # Try xdg-open, then fallback to editor
    try:
        subprocess.Popen(["xdg-open", local_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"[remote_edit] xdg-open failed: {e}")
        try:
            # try sensible-editor / gedit
            for cmd in ["gedit", "kate", "mousepad", "xed"]:
                try:
                    subprocess.Popen([cmd, local_path])
                    return True
                except FileNotFoundError:
                    continue
        except Exception as e2:
            print(e2)
    return False
