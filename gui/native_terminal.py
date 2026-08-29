"""Native embedded terminal for PolarTerm - embeds real Linux terminal directly.

On Linux X11 with xterm available: embeds a real xterm via `xterm -into <winId>` giving
100% native behavior (vim, htop, tmux, fonts, backspace, all work like gnome-terminal).

Fallback: uses the improved TerminalWidget (pyte/QPlainTextEdit) on any system.

Usage in MainWindow:
  from gui.native_terminal import EmbeddedTerminalWidget, is_native_available
  # then use EmbeddedTerminalWidget(ssh_wrapper=..., host=..., port=..., user=..., password=...)

Works on any system: auto-detects and falls back gracefully.
"""
import os, sys, shutil, shlex
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QApplication
from PyQt6.QtCore import QProcess, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont

def is_native_available():
    """Check if native xterm embedding can work on this system."""
    if sys.platform.startswith("win"):
        return False
    if os.environ.get("QT_QPA_PLATFORM") == "wayland":
        return False
    # Need X11 and xterm
    if not shutil.which("xterm"):
        return False
    # Need DISPLAY
    if not os.environ.get("DISPLAY"):
        return False
    return True

def _find_monospace_font():
    try:
        from PyQt6.QtGui import QFontDatabase
        db = QFontDatabase()
        avail = set(db.families())
        for fam in ["JetBrains Mono", "Fira Code", "DejaVu Sans Mono", "Liberation Mono", "Ubuntu Mono", "Monospace"]:
            if fam in avail:
                return fam
    except:
        pass
    return "Monospace"

class XTermEmbeddedWidget(QWidget):
    """Embeds a real xterm using X11 -into. True native Linux terminal inside PolarTerm."""
    failed = pyqtSignal(str)

    def __init__(self, parent=None, ssh_wrapper=None, host=None, port=22, user=None, password=None, key_path=None, is_local=False, local_path=None):
        super().__init__(parent)
        self.ssh_wrapper = ssh_wrapper
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.key_path = key_path
        self.is_local = is_local
        self.local_path = local_path
        self.proc = None
        self.container = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        # Status bar
        tb = QHBoxLayout()
        self.status = QLabel("Native terminal (xterm embedded) - 100% Linux behavior" if is_native_available() else "Fallback terminal")
        self.status.setStyleSheet("color: #4caf50; font-size: 11px; padding: 2px;")
        tb.addWidget(self.status)
        tb.addStretch()
        self.btn_restart = QPushButton("Restart")
        self.btn_restart.setFixedWidth(70)
        self.btn_restart.clicked.connect(self.restart)
        tb.addWidget(self.btn_restart)
        layout.addLayout(tb)

        # Container for xterm
        self.container = QWidget(self)
        self.container.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.container.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, False)
        self.container.setStyleSheet("background: #1e1e1e; border: 1px solid #333;")
        self.container.setMinimumSize(400, 250)
        layout.addWidget(self.container, 1)

        # Fallback label
        self.fallback_label = QLabel("If xterm fails, PolarTerm will auto-fallback to emulated terminal.\nInstall xterm: sudo apt install xterm")
        self.fallback_label.setStyleSheet("color: #888; font-size: 10px;")
        self.fallback_label.setWordWrap(True)
        layout.addWidget(self.fallback_label)
        self.fallback_label.hide()

    def showEvent(self, event):
        super().showEvent(event)
        if not self.proc:
            QTimer.singleShot(150, self._launch)

    def _launch(self):
        if not is_native_available():
            self.status.setText("Native xterm not available (Wayland/Windows or no xterm) - using fallback")
            self.status.setStyleSheet("color: #f59e0b; font-size: 11px;")
            self.fallback_label.show()
            self._launch_fallback()
            return

        wid = int(self.container.winId())
        if wid == 0:
            QTimer.singleShot(200, self._launch)
            return

        # Build command
        font = _find_monospace_font()
        # Use -fa for TrueType fonts if available
        args = ["-into", str(wid), "-bg", "#1e1e1e", "-fg", "#d4d4d4", "-fa", font, "-fs", "10",
                "-xrm", "XTerm*allowTitleOps: false", "-xrm", "*VT100.Translations: #override"]

        # Determine shell command to run inside xterm
        if self.is_local:
            # Local bash
            cmd = "bash"
            if self.local_path and os.path.isdir(self.local_path):
                cmd = f"bash -c 'cd {shlex.quote(self.local_path)}; exec bash -i'"
            args += ["-e", "bash", "-c", cmd]
            self.status.setText(f"Native local terminal: {cmd} (xterm {wid})")
        else:
            # Remote SSH via system ssh (native behavior)
            # Build ssh command; let xterm handle password prompt natively if no sshpass
            ssh_cmd = self._build_ssh_command()
            # Wrap with bash to keep open on exit
            # Use -hold or exec bash after
            args += ["-e", "bash", "-c", ssh_cmd]
            self.status.setText(f"Native SSH: {self.user}@{self.host}:{self.port} (xterm {wid})")

        self.proc = QProcess(self)
        self.proc.finished.connect(self._on_finished)
        self.proc.errorOccurred.connect(self._on_error)
        # xterm needs to run with DISPLAY set
        env = self.proc.processEnvironment()
        # Ensure env has DISPLAY
        self.proc.setProcessEnvironment(env)
        self.proc.start("xterm", args)
        if not self.proc.waitForStarted(3000):
            self.status.setText(f"xterm failed to start: {self.proc.errorString()}")
            self.status.setStyleSheet("color: #f44336; font-size: 11px;")
            self.fallback_label.show()
            self._launch_fallback()

    def _build_ssh_command(self):
        """Build native ssh command. Prefers sshpass if password provided and available."""
        parts = []
        if self.password and shutil.which("sshpass"):
            # Use sshpass for non-interactive password (like paramiko does)
            parts.append(f"sshpass -p {shlex.quote(self.password)}")
        # ssh options for HPC compatibility
        ssh_opts = "-o StrictHostKeyChecking=no -o ServerAliveInterval=20"
        if self.key_path and os.path.exists(os.path.expanduser(self.key_path)):
            ssh_opts += f" -i {shlex.quote(os.path.expanduser(self.key_path))}"
        ssh_cmd = f"ssh {ssh_opts} -p {self.port} {shlex.quote(self.user)}@{shlex.quote(self.host)}"
        # If we used sshpass, the full command is sshpass ... ssh ...
        if parts:
            full = " ".join(parts) + " " + ssh_cmd
        else:
            full = ssh_cmd
        # Keep terminal open after ssh exits
        full = f"{full}; echo \"\n[SSH exited code $?] Press Enter to close...\"; read"
        return full

    def _launch_fallback(self):
        # Create fallback TerminalWidget inside container
        try:
            from gui.terminal_widget import TerminalWidget
            fallback = TerminalWidget(ssh_wrapper=self.ssh_wrapper)
            # Replace container with fallback
            layout = self.layout()
            layout.removeWidget(self.container)
            self.container.hide()
            layout.addWidget(fallback, 1)
            self.fallback_widget = fallback
            if self.ssh_wrapper:
                fallback.connect_ssh(self.ssh_wrapper)
            elif self.is_local:
                fallback.connect_local()
            self.status.setText("Fallback emulated terminal (pyte) - install xterm for native: sudo apt install xterm")
            self.status.setStyleSheet("color: #f59e0b; font-size: 11px;")
        except Exception as e:
            self.status.setText(f"Fallback failed: {e}")
            self.failed.emit(str(e))

    def _on_finished(self, code, status):
        self.status.setText(f"xterm exited ({code}) - click Restart to reopen")
        self.status.setStyleSheet("color: #f59e0b; font-size: 11px;")

    def _on_error(self, err):
        self.status.setText(f"xterm error: {err} - fallback active")
        self.fallback_label.show()
        if not hasattr(self, 'fallback_widget'):
            self._launch_fallback()

    def restart(self):
        if self.proc:
            try:
                self.proc.terminate()
            except:
                pass
            self.proc = None
        self._launch()

    def close_shell(self):
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.waitForFinished(500)
                if self.proc.state() != QProcess.ProcessState.NotRunning:
                    self.proc.kill()
            except:
                pass
        if hasattr(self, 'fallback_widget'):
            try:
                self.fallback_widget.close_shell()
            except:
                pass

# Convenience wrapper that auto-chooses native or emulated
class EmbeddedTerminalWidget(QWidget):
    """Auto-chooses native xterm if available, else emulated. API compatible with TerminalWidget."""
    def __init__(self, ssh_wrapper=None, parent=None, host=None, port=22, user=None, password=None, key_path=None, is_local=False):
        super().__init__(parent)
        self.ssh_wrapper = ssh_wrapper
        self._inner = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)

        # Check if we should use native
        use_native = is_native_available() and os.environ.get("POLARTERM_NATIVE", "1").lower() not in ("0", "false", "off")
        # Also allow user to force via env POLARTERM_EMULATED=1
        if os.environ.get("POLARTERM_EMULATED", "").lower() in ("1", "true"):
            use_native = False

        if use_native:
            # Try native
            try:
                self._inner = XTermEmbeddedWidget(parent=self, ssh_wrapper=ssh_wrapper,
                    host=host, port=port, user=user, password=password, key_path=key_path,
                    is_local=is_local)
                layout.addWidget(self._inner)
                self.is_native = True
            except Exception as e:
                # Fallback
                from gui.terminal_widget import TerminalWidget
                self._inner = TerminalWidget(ssh_wrapper=ssh_wrapper, parent=self)
                layout.addWidget(self._inner)
                self.is_native = False
        else:
            from gui.terminal_widget import TerminalWidget
            self._inner = TerminalWidget(ssh_wrapper=ssh_wrapper, parent=self)
            layout.addWidget(self._inner)
            self.is_native = False

        self.terminal = getattr(self._inner, 'terminal', None) or getattr(self._inner, 'container', None)
        self.status_label = getattr(self._inner, 'status', None) or getattr(self._inner, 'status_label', QLabel())
        self.channel = getattr(self._inner, 'channel', None)
        self.reader = getattr(self._inner, 'reader', None)

    def connect_ssh(self, ssh_wrapper):
        # For native, the ssh is already handled via xterm ssh command; for fallback, delegate
        if hasattr(self._inner, 'connect_ssh') and not self.is_native:
            self._inner.connect_ssh(ssh_wrapper)
        # For native case, we already launched xterm with ssh; but if ssh_wrapper provided later,
        # we could show status
        self.ssh_wrapper = ssh_wrapper

    def connect_local(self):
        if hasattr(self._inner, 'connect_local') and not self.is_native:
            self._inner.connect_local()

    def _send(self, data: bytes):
        if hasattr(self._inner, '_send'):
            self._inner._send(data)

    def on_data(self, data: str):
        if hasattr(self._inner, 'on_data'):
            self._inner.on_data(data)

    def close_shell(self):
        if hasattr(self._inner, 'close_shell'):
            self._inner.close_shell()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self._inner, 'resizeEvent'):
            try:
                self._inner.resizeEvent(event)
            except:
                pass
