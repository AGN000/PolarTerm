import os, re, select
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPlainTextEdit, QHBoxLayout, QPushButton, QLabel
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt6.QtGui import QFont, QTextCursor, QColor, QPalette
import paramiko

# ANSI color handling - simple
ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

class ShellReaderThread(QThread):
    data_received = pyqtSignal(str)
    disconnected = pyqtSignal(str)
    def __init__(self, channel):
        super().__init__()
        self.channel = channel
        self._run = True

    def run(self):
        while self._run:
            try:
                if self.channel.recv_ready():
                    data = self.channel.recv(4096).decode('utf-8', errors='ignore')
                    if data:
                        self.data_received.emit(data)
                elif self.channel.recv_stderr_ready():
                    data = self.channel.recv_stderr(4096).decode('utf-8', errors='ignore')
                    if data:
                        self.data_received.emit(data)
                elif self.channel.exit_status_ready():
                    # check closed?
                    if self.channel.closed:
                        self.disconnected.emit("Channel closed")
                        break
                self.msleep(20)
            except Exception as e:
                self.disconnected.emit(str(e))
                break

    def stop(self):
        self._run = False

class TerminalWidget(QWidget):
    """Embedded SSH terminal via paramiko shell channel"""
    def __init__(self, ssh_wrapper=None, parent=None):
        super().__init__(parent)
        self.ssh = ssh_wrapper
        self.channel = None
        self.reader = None
        self._setup_ui()
        self.local_shell_process = None

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        # toolbar
        tb = QHBoxLayout()
        self.status_label = QLabel("Not connected")
        self.status_label.setStyleSheet("color: #888; font-size: 11px;")
        tb.addWidget(self.status_label)
        tb.addStretch()
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setFixedWidth(60)
        self.btn_clear.clicked.connect(lambda: self.terminal.clear())
        tb.addWidget(self.btn_clear)
        layout.addLayout(tb)

        self.terminal = QPlainTextEdit()
        self.terminal.setReadOnly(False)
        # we will handle input separately via key events? Simpler: use plain edit as display + input line
        # Better: make terminal read-only display plus command input? But we do true interactive via shell.
        # We'll implement interactive by capturing key presses and sending to channel, and appending received data.
        # Use custom QPlainTextEdit
        font = QFont("Monospace", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.terminal.setFont(font)
        self.terminal.setStyleSheet("""
            QPlainTextEdit { background-color: #1e1e1e; color: #d4d4d4; border: 1px solid #333; }
        """)
        # Improve palette
        self.terminal.setOverwriteMode(False)
        self.terminal.setUndoRedoEnabled(False)
        layout.addWidget(self.terminal)

        # State for handling input
        self._cursor_pos = 0  # to prevent deleting prompt region - simplified: allow all
        self.terminal.installEventFilter(self)

    def connect_ssh(self, ssh_wrapper):
        self.ssh = ssh_wrapper
        try:
            self.channel = self.ssh.open_shell(cols=120, rows=30)
            self.status_label.setText(f"Connected to {self.ssh.host}  |  Shell ready")
            self.status_label.setStyleSheet("color: #4caf50; font-size: 11px;")
            # start reader
            self.reader = ShellReaderThread(self.channel)
            self.reader.data_received.connect(self.on_data)
            self.reader.disconnected.connect(self.on_disconnect)
            self.reader.start()
            # send initial resize
            QTimer.singleShot(200, lambda: self.channel.send("\n"))
        except Exception as e:
            self.status_label.setText(f"Shell error: {e}")
            self.status_label.setStyleSheet("color: #f44336; font-size: 11px;")

    def connect_local(self):
        """Fallback: local bash via QProcess embedded (simple)"""
        from PyQt6.QtCore import QProcess
        self.status_label.setText("Local shell (bash)")
        self.status_label.setStyleSheet("color: #2196f3; font-size: 11px;")
        self.local_shell_process = QProcess(self)
        self.local_shell_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.local_shell_process.readyReadStandardOutput.connect(self._on_local_data)
        self.local_shell_process.start("bash", ["-i"])
        self.terminal.appendPlainText("Local bash started (interactive). Type commands.\n")

    def _on_local_data(self):
        data = self.local_shell_process.readAllStandardOutput().data().decode(errors='ignore')
        self.on_data(data)

    def on_data(self, data: str):
        # strip or keep ANSI? Keep stripped for now, but preserve newlines
        # For color we could parse, but simplified: remove ANSI for clean display
        # We'll do basic translation: remove \r, keep \n
        # Use QTextCursor to append without clearing
        cursor = self.terminal.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        # Remove ANSI sequences to avoid garbage
        clean = ANSI_RE.sub('', data)
        # Handle backspace / carriage return artifacts
        clean = clean.replace('\r\n', '\n').replace('\r', '\n')
        cursor.insertText(clean)
        # Auto scroll
        self.terminal.setTextCursor(cursor)
        self.terminal.ensureCursorVisible()
        # Ensure visible
        sb = self.terminal.verticalScrollBar()
        sb.setValue(sb.maximum())

    def on_disconnect(self, msg):
        self.status_label.setText(f"Disconnected: {msg}")
        self.status_label.setStyleSheet("color: #f44336; font-size: 11px;")

    def keyPressEvent(self, event):
        # This is for widget itself, but we have terminal as child.
        # We'll intercept terminal key presses via eventFilter
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        if obj is self.terminal and event.type() == event.Type.KeyPress:
            key = event.key()
            mods = event.modifiers()
            text = event.text()

            # Handle copy/paste
            if mods & Qt.KeyboardModifier.ControlModifier:
                if key == Qt.Key.Key_C:
                    # copy if selection else send Ctrl-C
                    if self.terminal.textCursor().hasSelection():
                        self.terminal.copy()
                        return True
                    else:
                        self._send(b'\x03')
                        return True
                elif key == Qt.Key.Key_V:
                    self.terminal.paste()
                    # if remote, we need to send clipboard content
                    # paste() already inserts locally; we should also send?
                    # Simplified: just let paste insert, then on next enter send? Instead send clipboard directly if remote
                    if self.channel and not self.local_shell_process:
                        # get clipboard text that was pasted? We'll asynchronously send
                        # For now return false to let default paste then we will capture? Simpler to handle manually:
                        return False
                    return False
                elif key == Qt.Key.Key_L:
                    self.terminal.clear()
                    if self.channel:
                        self._send(b'\x0c')
                    return True
                elif key == Qt.Key.Key_D:
                    if self.channel:
                        self._send(b'\x04')
                        return True

            # Handle special keys
            if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
                self._send(b'\n')
                # also show newline locally echo will come from server
                # we optimistically add newline
                if self.local_shell_process:
                    self.local_shell_process.write(b'\n')
                else:
                    # let server echo, but we insert newline for responsiveness
                    pass
                return True
            elif key == Qt.Key.Key_Backspace:
                self._send(b'\x7f')
                # handle local backspace visually
                cursor = self.terminal.textCursor()
                if cursor.hasSelection():
                    cursor.removeSelectedText()
                else:
                    # move back one and delete
                    cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor, 1)
                    # don't delete if at start
                    if not cursor.atStart():
                        cursor.removeSelectedText()
                return True
            elif key == Qt.Key.Key_Tab:
                self._send(b'\t')
                return True
            elif key == Qt.Key.Key_Up:
                self._send(b'\x1b[A')
                return True
            elif key == Qt.Key.Key_Down:
                self._send(b'\x1b[B')
                return True
            elif key == Qt.Key.Key_Right:
                self._send(b'\x1b[C')
                return True
            elif key == Qt.Key.Key_Left:
                self._send(b'\x1b[D')
                return True
            elif key == Qt.Key.Key_Home:
                self._send(b'\x1b[H')
                return True
            elif key == Qt.Key.Key_End:
                self._send(b'\x1b[F')
                return True
            elif key == Qt.Key.Key_Delete:
                self._send(b'\x1b[3~')
                return True
            elif text:
                # regular character
                self._send(text.encode('utf-8', errors='ignore'))
                # echo locally? Server will echo, but for local shell we rely on process echo
                # For remote, server echo gives char. To avoid double, we don't insert here.
                # But for responsiveness on high latency, we could insert. We'll rely on server echo.
                return True
            return False
        return super().eventFilter(obj, event)

    def _send(self, data: bytes):
        try:
            if self.channel and not self.channel.closed:
                self.channel.send(data)
            elif self.local_shell_process:
                self.local_shell_process.write(data)
        except Exception as e:
            self.terminal.appendPlainText(f"\n[send error: {e}]\n")

    def close_shell(self):
        if self.reader:
            self.reader.stop()
            self.reader.wait(1000)
        if self.channel:
            try: self.channel.close()
            except: pass
        if self.local_shell_process:
            try: self.local_shell_process.terminate()
            except: pass
