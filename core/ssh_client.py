import paramiko
import socket
import os
import threading
from typing import Optional, Callable

class SSHClientWrapper:
    """Paramiko wrapper with SFTP support and shell channel"""
    def __init__(self):
        self.client: Optional[paramiko.SSHClient] = None
        self.sftp: Optional[paramiko.SFTPClient] = None
        self.transport: Optional[paramiko.Transport] = None
        self.shell: Optional[paramiko.Channel] = None
        self.connected = False
        self.host = ""
        self.username = ""

    def connect(self, host: str, port: int, username: str,
                password: str = "", key_path: str = "", key_passphrase: str = "",
                timeout: int = 10, jump_host_str: str = ""):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.host = host
        self.username = username

        pkey = None
        if key_path and os.path.exists(os.path.expanduser(key_path)):
            key_path = os.path.expanduser(key_path)
            # try all key types
            for key_cls in [paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.DSSKey]:
                try:
                    pkey = key_cls.from_private_key_file(key_path, password=key_passphrase if key_passphrase else None)
                    break
                except Exception:
                    continue
            if pkey is None:
                raise Exception(f"Could not load private key {key_path}")

        # Handle jump host if provided (e.g. "user@jump:22" or "jump.example.com")
        sock = None
        if jump_host_str:
            # parse jump_host_str
            j_user, j_host, j_port = self._parse_jump(jump_host_str, username)
            # we need to create a jump client
            jump_client = paramiko.SSHClient()
            jump_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            jump_client.connect(j_host, port=j_port, username=j_user,
                                password=password if not pkey else None,
                                pkey=pkey, timeout=timeout)
            jump_transport = jump_client.get_transport()
            dest_addr = (host, port)
            local_addr = (j_host, j_port)
            sock = jump_transport.open_channel("direct-tcpip", dest_addr, local_addr)

        connect_kwargs = dict(hostname=host, port=port, username=username, timeout=timeout, sock=sock, allow_agent=True, look_for_keys=True)
        if pkey:
            connect_kwargs["pkey"] = pkey
        else:
            connect_kwargs["password"] = password

        self.client.connect(**connect_kwargs)
        self.transport = self.client.get_transport()
        # keepalive to avoid GNOME force-quit on idle TCP
        try:
            self.transport.set_keepalive(20)
        except: pass
        self.sftp = self.client.open_sftp()
        self.connected = True

    def _parse_jump(self, jump_str: str, default_user: str):
        # formats: host, user@host, host:port, user@host:port
        user = default_user
        host = jump_str
        port = 22
        if "@" in jump_str:
            user, host = jump_str.split("@", 1)
        if ":" in host:
            host, port_s = host.rsplit(":", 1)
            try:
                port = int(port_s)
            except:
                pass
        return user, host, port

    def open_shell(self, term="xterm-256color", cols=120, rows=30):
        if not self.client:
            raise Exception("Not connected")
        self.shell = self.client.invoke_shell(term=term, width=cols, height=rows)
        self.shell.settimeout(0.0)
        return self.shell

    def exec_command(self, cmd: str, timeout=10):
        if not self.client:
            raise Exception("Not connected")
        stdin, stdout, stderr = self.client.exec_command(cmd, timeout=timeout)
        return stdin, stdout, stderr

    def resize_shell(self, cols, rows):
        if self.shell:
            self.shell.resize_pty(width=cols, height=rows)

    def close(self):
        try:
            if self.shell:
                self.shell.close()
        except: pass
        try:
            if self.sftp:
                self.sftp.close()
        except: pass
        try:
            if self.client:
                self.client.close()
        except: pass
        self.connected = False

    # SFTP helpers
    def get_home(self):
        # cache home
        if hasattr(self, "_home") and self._home:
            return self._home
        # try pwd via exec, fallback to normalize('.')
        home = None
        try:
            if self.client:
                stdin, stdout, stderr = self.client.exec_command("echo $HOME; pwd", timeout=5)
                out = stdout.read().decode().strip().splitlines()
                if out and out[0].startswith("/"):
                    home = out[0].strip()
                elif len(out) > 1 and out[1].startswith("/"):
                    home = out[1].strip()
        except: pass
        if not home:
            try:
                if self.sftp:
                    home = self.sftp.normalize(".")
            except: pass
        if not home:
            home = "."
        self._home = home
        return home

    def _expand_tilde(self, path):
        if path == "~" or path == "~/":
            return self.get_home()
        if path.startswith("~/"):
            return self.get_home().rstrip("/") + "/" + path[2:]
        if path == "~":
            return self.get_home()
        return path

    def sftp_listdir(self, path="."):
        if not self.sftp:
            raise Exception("SFTP not connected")
        path = self._expand_tilde(path)
        # normalize to absolute, handling "." -> home
        if path == ".":
            path = self.get_home()
        else:
            try:
                # use normalize for relative paths, but keep absolute
                if not path.startswith("/"):
                    path = self.get_home().rstrip("/") + "/" + path
            except: pass
        return self.sftp.listdir_attr(path)

    def sftp_normalize(self, path):
        # handle tilde expansion first even if not connected (use cached or raw)
        expanded = self._expand_tilde(path) if path and "~" in path else path
        if not self.sftp:
            return expanded
        path = expanded
        if path == "." or path == "":
            return self.get_home()
        try:
            return self.sftp.normalize(path)
        except:
            return path

    def sftp_get(self, remote, local, callback=None):
        remote = self._expand_tilde(remote)
        return self.sftp.get(remote, local, callback=callback)

    def sftp_put(self, local, remote, callback=None):
        remote = self._expand_tilde(remote)
        return self.sftp.put(local, remote, callback=callback)

    def sftp_mkdir(self, path):
        path = self._expand_tilde(path)
        return self.sftp.mkdir(path)

    def sftp_remove(self, path):
        path = self._expand_tilde(path)
        return self.sftp.remove(path)

    def sftp_rmdir(self, path):
        path = self._expand_tilde(path)
        return self.sftp.rmdir(path)

    def sftp_rename(self, old, new):
        old = self._expand_tilde(old)
        new = self._expand_tilde(new)
        return self.sftp.rename(old, new)

    def sftp_stat(self, path):
        path = self._expand_tilde(path)
        return self.sftp.stat(path)

    def sftp_lstat(self, path):
        path = self._expand_tilde(path)
        return self.sftp.lstat(path)
