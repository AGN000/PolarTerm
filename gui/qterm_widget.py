"""Real VTE terminal via QTermWidget (Qt) with fallback to TerminalWidget.

- If system provides QTermWidget (libqtermwidget + Python bindings), we use it for 100% real
  VT100/256, bracketed-paste, alt-screen (vim/htop), true pty, job control.
- Otherwise falls back to improved TerminalWidget (pyte + real pty forkpty).

Install for real VTE:
  # Ubuntu/Debian Qt5 (PyQt5)
  sudo apt install libqtermwidget5-1 qtermwidget5-data python3-pyqt5.qtermwidget
  # For PyQt6 build from source: https://github.com/lxqt/qtermwidget (Qt6 branch)
  # Then: POLARTERM_QTERM=1 python main.py

Usage:
  from gui.qterm_widget import RealTerminalWidget, is_qterm_available
"""
import os, sys, shlex, shutil

def is_qterm_available():
    if os.environ.get("POLARTERM_QTERM", "").lower() in ("0", "false", "off"):
        return False
    # try various import paths for QTermWidget bindings
    for mod, attr in [
        ("QTermWidget", "QTermWidget"),
        ("qtermwidget", "QTermWidget"),
        ("PyQt5.QTermWidget", "QTermWidget"),
        ("PyQt6.QTermWidget", "QTermWidget"),
    ]:
        try:
            __import__(mod)
            m = sys.modules[mod]
            if hasattr(m, attr):
                return True
        except: pass
    # also try importlib spec
    try:
        import importlib.util
        for name in ["QTermWidget", "qtermwidget"]:
            if importlib.util.find_spec(name):
                return True
    except: pass
    return False

def _load_qterm_class():
    for mod, attr in [
        ("QTermWidget", "QTermWidget"),
        ("qtermwidget", "QTermWidget"),
        ("PyQt5.QTermWidget", "QTermWidget"),
        ("PyQt6.QTermWidget", "QTermWidget"),
    ]:
        try:
            m = __import__(mod, fromlist=[attr])
            cls = getattr(m, attr, None)
            if cls:
                return cls
        except Exception as e:
            continue
    return None

# Try to import real class
_QTermWidgetCls = _load_qterm_class() if is_qterm_available() else None

if _QTermWidgetCls:
    from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
    from PyQt6.QtCore import QProcess

    class QTermRealWidget(QWidget):
        """Real VTE using QTermWidget + system ssh/bash via pty."""
        def __init__(self, ssh_wrapper=None, parent=None, host=None, port=22, user=None, password=None, key_path=None, is_local=False):
            super().__init__(parent)
            self.ssh_wrapper = ssh_wrapper
            self.host = host; self.port = port; self.user = user
            self.password = password; self.key_path = key_path
            self.is_local = is_local
            self._setup_ui()
            # For API compat with TerminalWidget
            self.channel = None
            self.reader = None
            self.local_shell_process = None
            self.local_pty_master = None

        def _setup_ui(self):
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0,0,0,0)
            self.status = QLabel("QTermWidget real VTE - 100% VT, bracketed-paste, vim/htop")
            self.status.setStyleSheet("color: #4caf50; font-size: 11px; padding: 2px;")
            layout.addWidget(self.status)
            try:
                self.term = _QTermWidgetCls(0)
                # QTermWidget API differences: try common methods
                for meth in ["setColorScheme", "setScrollBarPosition"]:
                    try:
                        if meth == "setColorScheme":
                            self.term.setColorScheme("DarkPastels")
                        elif meth == "setScrollBarPosition":
                            # 2 = NoScrollBar, 0 = Left, 1 = Right
                            self.term.setScrollBarPosition(1)
                    except: pass
                layout.addWidget(self.term, 1)
            except Exception as e:
                from PyQt6.QtWidgets import QPlainTextEdit
                self.term = QPlainTextEdit()
                self.term.setPlainText(f"QTermWidget init failed: {e}\nFallback to emulated.")
                layout.addWidget(self.term, 1)

        def connect_ssh(self, ssh_wrapper):
            self.ssh_wrapper = ssh_wrapper
            # QTermWidget expects system ssh, not paramiko channel.
            # We will spawn ssh via QTermWidget's shell program.
            # Build ssh command like native_terminal does.
            try:
                sess_host = ssh_wrapper.host if hasattr(ssh_wrapper,'host') else self.host
                sess_user = ssh_wrapper.username if hasattr(ssh_wrapper,'username') else self.user
                # need session details from main_window? fallback to wrapper
                cmd = self._build_ssh_cmd(sess_host, sess_user)
                # QTermWidget API: setShellProgram / setArgs / startShellProgram
                if hasattr(self.term, "setShellProgram"):
                    # QTermWidget takes program + args
                    self.term.setShellProgram("/usr/bin/bash")
                    self.term.setArgs(["-c", cmd])
                    self.term.startShellProgram()
                    self.status.setText(f"QTermWidget SSH: {sess_user}@{sess_host}")
                elif hasattr(self.term, "execute"):
                    self.term.execute(cmd)
                else:
                    self.status.setText("QTermWidget API unknown - fallback")
            except Exception as e:
                self.status.setText(f"QTerm SSH failed: {e}")

        def _build_ssh_cmd(self, host, user):
            port = self.port or 22
            ssh_opts = "-o StrictHostKeyChecking=no -o ServerAliveInterval=20"
            if self.key_path and os.path.exists(os.path.expanduser(self.key_path or "")):
                ssh_opts += f" -i {shlex.quote(os.path.expanduser(self.key_path))}"
            base = f"ssh {ssh_opts} -p {port} {shlex.quote(user)}@{shlex.quote(host)}"
            if self.password and shutil.which("sshpass"):
                base = f"sshpass -p {shlex.quote(self.password)} {base}"
            # keep open after exit
            return f"{base}; echo \"[SSH exited $?]\"; exec bash"

        def connect_local(self):
            try:
                if hasattr(self.term, "setShellProgram"):
                    self.term.setShellProgram("/bin/bash")
                    self.term.setArgs(["-i"])
                    self.term.startShellProgram()
                    self.status.setText("QTermWidget local bash (real pty)")
                elif hasattr(self.term, "execute"):
                    self.term.execute("bash -i")
            except Exception as e:
                self.status.setText(f"local failed: {e}")

        def close_shell(self):
            try:
                if hasattr(self.term, "close"):
                    self.term.close()
            except: pass

        # compat
        @property
        def terminal(self):
            return self.term
        @property
        def status_label(self):
            return self.status

    RealTerminalWidget = QTermRealWidget
else:
    # Fallback: improved TerminalWidget (real pty forkpty + pyte)
    from gui.terminal_widget import TerminalWidget as RealTerminalWidget
    # expose same helper
    QTermRealWidget = None
