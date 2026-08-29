import os, re, select
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPlainTextEdit, QHBoxLayout, QPushButton, QLabel, QApplication
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt6.QtGui import QFont, QTextCursor, QColor, QPalette, QFontDatabase
import paramiko

try:
    import pyte
    import wcwidth
    HAS_PYTE = True
except ImportError:
    HAS_PYTE = False
    pyte = None

# --- Font helper: robust monospace selection for any system ---
def _get_terminal_font(size=10):
    """Return a monospace font that exists on this system. Fallback chain covers Linux/Win/macOS."""
    preferred = [
        "JetBrains Mono", "Fira Code", "Cascadia Code", "Cascadia Mono",
        "DejaVu Sans Mono", "Liberation Mono", "Ubuntu Mono", "Consolas",
        "Courier New", "Monospace", "Noto Sans Mono", "Source Code Pro"
    ]
    try:
        db = QFontDatabase()
        available = set(db.families())
    except:
        available = set()
    for fam in preferred:
        if fam in available:
            f = QFont(fam, size)
            f.setStyleHint(QFont.StyleHint.Monospace)
            f.setFixedPitch(True)
            f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
            return f
    # Last resort: let Qt find monospace
    f = QFont("Monospace", size)
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setFixedPitch(True)
    return f

# --- ANSI handling: strip or parse ---
# We handle CSI sequences properly instead of just stripping m
ANSI_CSI_RE = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')  # for quick strip fallback

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
                got = False
                if self.channel.recv_ready():
                    data = self.channel.recv(8192).decode('utf-8', errors='ignore')
                    if data:
                        self.data_received.emit(data)
                        got = True
                if self.channel.recv_stderr_ready():
                    data = self.channel.recv_stderr(8192).decode('utf-8', errors='ignore')
                    if data:
                        self.data_received.emit(data)
                        got = True
                if not got:
                    if self.channel.exit_status_ready():
                        if self.channel.closed:
                            self.disconnected.emit("Channel closed")
                            break
                    self.msleep(15)
            except Exception as e:
                self.disconnected.emit(str(e))
                break

    def stop(self):
        self._run = False

class TerminalWidget(QWidget):
    """Embedded SSH terminal via paramiko shell channel - behaves like Linux terminal"""
    def __init__(self, ssh_wrapper=None, parent=None):
        super().__init__(parent)
        self.ssh = ssh_wrapper
        self.channel = None
        self.reader = None
        self._setup_ui()
        self.local_shell_process = None
        # For handling escape sequences statefully
        self._esc_buf = ""
        # pyte screen for true VT emulation (vim/htop) - fallback to hand-rolled if not available
        self.use_pyte = HAS_PYTE and os.environ.get("POLARTERM_PYTE", "1").lower() not in ("0", "false")
        if self.use_pyte:
            try:
                cols, rows = 120, 30
                self.pyte_screen = pyte.HistoryScreen(cols, rows, history=500, ratio=0.5)
                self.pyte_stream = pyte.Stream(self.pyte_screen)
            except Exception as e:
                print(f"[terminal] pyte init failed {e}, fallback to manual")
                self.use_pyte = False
                self.pyte_screen = None
                self.pyte_stream = None
        else:
            self.pyte_screen = None
            self.pyte_stream = None

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        # toolbar
        tb = QHBoxLayout()
        self.status_label = QLabel("Not connected")
        self.status_label.setStyleSheet("color: #888; font-size: 11px;")
        tb.addWidget(self.status_label)
        tb.addStretch()
        self.font_size = 10
        self.btn_zoom_out = QPushButton("A-")
        self.btn_zoom_out.setFixedWidth(36)
        self.btn_zoom_out.setToolTip("Smaller font (Ctrl+-)")
        self.btn_zoom_out.clicked.connect(lambda: self._change_font(-1))
        tb.addWidget(self.btn_zoom_out)
        self.btn_zoom_in = QPushButton("A+")
        self.btn_zoom_in.setFixedWidth(36)
        self.btn_zoom_in.setToolTip("Larger font (Ctrl++)")
        self.btn_zoom_in.clicked.connect(lambda: self._change_font(1))
        tb.addWidget(self.btn_zoom_in)
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setFixedWidth(60)
        self.btn_clear.clicked.connect(lambda: self.terminal.clear())
        tb.addWidget(self.btn_clear)
        layout.addLayout(tb)

        self.terminal = QPlainTextEdit()
        self.terminal.setReadOnly(False)
        # True terminal emulation: we handle all key presses and render via remote echo
        font = _get_terminal_font(self.font_size)
        self.terminal.setFont(font)
        # Verify font actually applied - fallback log
        # print(f"[terminal] using font: {font.family()} {font.pointSize()}")

        self.terminal.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #333;
                selection-background-color: #264f78;
                selection-color: #ffffff;
            }
        """)
        # Improve palette for selection visibility
        pal = self.terminal.palette()
        pal.setColor(QPalette.ColorRole.Highlight, QColor("#264f78"))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        self.terminal.setPalette(pal)

        self.terminal.setOverwriteMode(False)
        self.terminal.setUndoRedoEnabled(False)
        self.terminal.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        # Make cursor block like linux terminal
        self.terminal.setCursorWidth(2)
        layout.addWidget(self.terminal)

        # State
        self._cursor_pos = 0
        self.terminal.installEventFilter(self)
        # Support resizing -> notify pty
        self.terminal.viewport().installEventFilter(self)

    def _change_font(self, delta):
        self.font_size = max(6, min(20, self.font_size + delta))
        self.terminal.setFont(_get_terminal_font(self.font_size))

    def _current_cols_rows(self):
        # Estimate cols/rows from viewport size and font metrics
        try:
            fm = self.terminal.fontMetrics()
            w = self.terminal.viewport().width()
            h = self.terminal.viewport().height()
            # avg char width
            cw = fm.horizontalAdvance('W')
            ch = fm.lineSpacing()
            cols = max(20, w // max(1, cw))
            rows = max(10, h // max(1, ch))
            return cols, rows
        except:
            return 120, 30

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Notify remote pty of new size on resize (like linux terminal)
        try:
            if self.channel and not self.channel.closed:
                cols, rows = self._current_cols_rows()
                self.channel.resize_pty(width=cols, height=rows)
                if self.ssh and hasattr(self.ssh, 'resize_shell'):
                    self.ssh.resize_shell(cols, rows)
                # Also resize pyte screen
                if self.use_pyte and self.pyte_screen:
                    try:
                        self.pyte_screen.resize(rows, cols)
                    except:
                        # recreate
                        self.pyte_screen = pyte.HistoryScreen(cols, rows, history=500, ratio=0.5)
                        self.pyte_stream = pyte.Stream(self.pyte_screen)
        except:
            pass

    def connect_ssh(self, ssh_wrapper):
        self.ssh = ssh_wrapper
        try:
            cols, rows = self._current_cols_rows()
            # (re-)init pyte screen with correct size
            if self.use_pyte:
                try:
                    self.pyte_screen = pyte.HistoryScreen(cols, rows, history=500, ratio=0.5)
                    self.pyte_stream = pyte.Stream(self.pyte_screen)
                except:
                    pass
            self.channel = self.ssh.open_shell(cols=cols, rows=rows)
            mode = "pyte" if self.use_pyte else "native parser"
            self.status_label.setText(f"Connected to {self.ssh.host}  |  Shell ready ({cols}x{rows}, {mode})")
            self.status_label.setStyleSheet("color: #4caf50; font-size: 11px;")
            # start reader
            self.reader = ShellReaderThread(self.channel)
            self.reader.data_received.connect(self.on_data)
            self.reader.disconnected.connect(self.on_disconnect)
            self.reader.start()
            # send initial resize
            QTimer.singleShot(200, lambda: self._send(b"\n") if self.channel else None)
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
        # Use -i for interactive like linux terminal
        self.local_shell_process.start("bash", ["-i"])
        self.terminal.appendPlainText("Local bash started (interactive). Type commands.\n")

    def _on_local_data(self):
        data = self.local_shell_process.readAllStandardOutput().data().decode(errors='ignore')
        self.on_data(data)

    def on_data(self, data: str):
        """Linux-like terminal emulation: handle BS, CR, LF, TAB, ESC sequences properly."""
        # If pyte available, use it for 100% VT100 (vim/htop) then render
        if self.use_pyte and self.pyte_screen and self.pyte_stream:
            try:
                self.pyte_stream.feed(data)
                # Render pyte screen to QPlainTextEdit
                # Preserve scrollback: join display + history tail
                lines = []
                # Add history if any
                if hasattr(self.pyte_screen, 'history'):
                    # history is deque of lines
                    try:
                        hist = list(self.pyte_screen.history.top)
                        # Deduplicate? just show current screen for now
                        pass
                    except:
                        pass
                # Build full text including scrollback history + current display
                try:
                    # HistoryScreen has history.top deque
                    hist_lines = []
                    if hasattr(self.pyte_screen, 'history') and hasattr(self.pyte_screen.history, 'top'):
                        hist_lines = [line.rstrip() for line in list(self.pyte_screen.history.top)]
                    display = [line.rstrip() for line in self.pyte_screen.display]
                    if self.pyte_screen.alt_screen:
                        # Alternate screen (vim/htop) - show only display, no history
                        text = "\n".join(display).rstrip()
                        self.terminal.setPlainText(text)
                    else:
                        # Normal: history + display, trim leading/trailing empties
                        all_lines = hist_lines + display
                        # Remove leading empty from history that are just blank buffer
                        # Keep last 1000 lines for performance
                        if len(all_lines) > 1000:
                            all_lines = all_lines[-1000:]
                        text = "\n".join(all_lines).rstrip()
                        # Avoid flicker: only update if changed
                        if text != self.terminal.toPlainText().rstrip():
                            self.terminal.setPlainText(text)
                except Exception as _e:
                    display = self.pyte_screen.display
                    text = "\n".join(display).rstrip()
                    self.terminal.setPlainText(text)
                # Move cursor to pyte cursor
                cursor = self.terminal.textCursor()
                # pyte cursor is 0-indexed
                try:
                    cur_y = self.pyte_screen.cursor.y
                    cur_x = self.pyte_screen.cursor.x
                    # Move to y line, x column
                    cursor.movePosition(QTextCursor.MoveOperation.Start)
                    for _ in range(cur_y):
                        cursor.movePosition(QTextCursor.MoveOperation.Down)
                    cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                    for _ in range(cur_x):
                        cursor.movePosition(QTextCursor.MoveOperation.Right)
                    self.terminal.setTextCursor(cursor)
                except:
                    cursor.movePosition(QTextCursor.MoveOperation.End)
                    self.terminal.setTextCursor(cursor)
                self.terminal.ensureCursorVisible()
                self.terminal.verticalScrollBar().setValue(self.terminal.verticalScrollBar().maximum())
                return
            except Exception as e:
                print(f"[terminal] pyte feed failed {e}, fallback to manual")
                # fall through to manual

        # Manual fallback: Use QTextCursor to apply terminal semantics
        cursor = self.terminal.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.terminal.setTextCursor(cursor)

        # We process char by char to handle control codes correctly
        i = 0
        n = len(data)
        while i < n:
            ch = data[i]

            # ESC sequence handling
            if ch == '\x1b':
                # Look ahead for CSI or other sequences
                if i + 1 < n and data[i+1] == '[':
                    # CSI sequence \x1b[...<letter>
                    j = i + 2
                    while j < n and (data[j].isdigit() or data[j] in ';:?'):
                        j += 1
                    if j < n:
                        # j is command char
                        cmd = data[j]
                        params = data[i+2:j]
                        self._handle_csi(cmd, params, cursor)
                        i = j + 1
                        continue
                    else:
                        # incomplete, consume rest
                        i = n
                        continue
                elif i + 1 < n and data[i+1] in ('(', ')', '#', '%'):
                    # charset designate, skip 2 chars
                    i += 2
                    continue
                else:
                    # Single ESC or ESC + char (like ESC c), skip
                    # Common: \x1b] ... BEL or ST, or \x1bM, etc.
                    # For OSC \x1b] ... \x07 or \x1b\\
                    if i + 1 < n and data[i+1] == ']':
                        # OSC, skip till BEL or ST
                        j = i + 2
                        while j < n and data[j] not in ('\x07', '\x1b'):
                            j += 1
                        if j < n and data[j] == '\x1b' and j+1 < n and data[j+1] == '\\':
                            j += 2
                        elif j < n and data[j] == '\x07':
                            j += 1
                        i = j
                        continue
                    # Unknown ESC, just skip 2
                    i += 2 if i+1 < n else 1
                    continue

            # Control characters
            if ch == '\r':
                # Carriage return -> move to start of line (like linux terminal)
                # Do not add newline, just move cursor to start of block
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                self.terminal.setTextCursor(cursor)
                i += 1
                # If next is \n, it will be handled as newline; we already handled \r
                # But \r\n should become one newline, so if next is \n, let it handle
                continue
            elif ch == '\n':
                # Line feed -> new block
                cursor.insertText('\n')
                self.terminal.setTextCursor(cursor)
                i += 1
                continue
            elif ch == '\b' or ch == '\x7f':
                # Backspace / DEL -> move cursor back one (like linux terminal)
                # The server typically sends \b to move, and \b \b to erase.
                # We emulate by moving cursor left and deleting if needed.
                # For \b alone, move left
                if ch == '\b':
                    # Move cursor left one char within line
                    cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, 1)
                    self.terminal.setTextCursor(cursor)
                else:
                    # DEL (0x7f) is also backspace for many terms
                    cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, 1)
                    # Delete the char under cursor if any
                    # We achieve erase by selecting one char right and removing
                    # But easier: move left then delete char to right
                    pos = cursor.position()
                    # peek next char
                    # Instead, select one char to the right and remove
                    cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
                    if cursor.hasSelection():
                        cursor.removeSelectedText()
                    else:
                        # At end, just move
                        cursor.clearSelection()
                    self.terminal.setTextCursor(cursor)
                i += 1
                continue
            elif ch == '\t':
                cursor.insertText('    ')  # expand tab to 4 spaces like linux terminal setting
                i += 1
                continue
            elif ch == '\x07':
                # BEL - flash or ignore
                QApplication.beep()
                i += 1
                continue
            elif ch == '\x00':
                i += 1
                continue
            elif ch == '\x0c':
                # Form feed -> clear screen
                self.terminal.clear()
                cursor = self.terminal.textCursor()
                i += 1
                continue
            else:
                # Regular printable char (including UTF-8 already decoded)
                # Handle overwriting if cursor is not at end (due to prior BS/CR)
                if cursor.atEnd():
                    cursor.insertText(ch)
                else:
                    # Overwrite mode: select one char right and replace
                    cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
                    cursor.insertText(ch)
                    # After insert, cursor is after inserted char; if we want to stay in overwrite,
                    # we don't move further
                self.terminal.setTextCursor(cursor)
                i += 1
                continue

        # Auto scroll to end if we were at end (keep terminal following like linux)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.terminal.setTextCursor(cursor)
        self.terminal.ensureCursorVisible()
        sb = self.terminal.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _handle_csi(self, cmd, params, cursor):
        """Handle common CSI sequences for linux-like behavior."""
        try:
            # Parse params
            if params:
                # handle ? prefix for private modes
                if params.startswith('?'):
                    params = params[1:]
                parts = [p for p in params.split(';') if p != '']
                nums = []
                for p in parts:
                    try:
                        nums.append(int(p))
                    except:
                        nums.append(0)
            else:
                nums = []

            def n(idx, default):
                return nums[idx] if idx < len(nums) and nums[idx] != 0 else default

            if cmd == 'm':
                # SGR color - ignore for now (we stripped), could implement via format
                return
            elif cmd in ('K', 'k'):
                # Erase in line
                # 0: to end, 1: to start, 2: whole line
                mode = n(0, 0)
                if mode == 2:
                    cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                    cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                    cursor.removeSelectedText()
                elif mode == 0:
                    cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                    cursor.removeSelectedText()
                elif mode == 1:
                    cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)
                    cursor.removeSelectedText()
                self.terminal.setTextCursor(cursor)
            elif cmd in ('J', 'j'):
                mode = n(0, 0)
                if mode == 2:
                    # Clear screen
                    self.terminal.clear()
                    cursor = self.terminal.textCursor()
                elif mode == 0:
                    # Clear from cursor to end
                    cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
                    cursor.removeSelectedText()
                elif mode == 1:
                    cursor.movePosition(QTextCursor.MoveOperation.Start, QTextCursor.MoveMode.KeepAnchor)
                    cursor.removeSelectedText()
                self.terminal.setTextCursor(cursor)
            elif cmd == 'H' or cmd == 'f':
                # Cursor position
                row = n(0, 1)
                col = n(1, 1)
                # Simplified: if 1,1 -> home, else move to start then approximate
                if row == 1 and col == 1:
                    cursor.movePosition(QTextCursor.MoveOperation.Start)
                else:
                    # Move to row/col approx: count lines
                    cursor.movePosition(QTextCursor.MoveOperation.Start)
                    for _ in range(row-1):
                        cursor.movePosition(QTextCursor.MoveOperation.Down)
                    cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                    for _ in range(col-1):
                        cursor.movePosition(QTextCursor.MoveOperation.Right)
                self.terminal.setTextCursor(cursor)
            elif cmd == 'A':
                # Cursor up
                cnt = n(0, 1)
                for _ in range(cnt):
                    cursor.movePosition(QTextCursor.MoveOperation.Up)
                self.terminal.setTextCursor(cursor)
            elif cmd == 'B':
                cnt = n(0, 1)
                for _ in range(cnt):
                    cursor.movePosition(QTextCursor.MoveOperation.Down)
                self.terminal.setTextCursor(cursor)
            elif cmd == 'C':
                cnt = n(0, 1)
                for _ in range(cnt):
                    cursor.movePosition(QTextCursor.MoveOperation.Right)
                self.terminal.setTextCursor(cursor)
            elif cmd == 'D':
                cnt = n(0, 1)
                for _ in range(cnt):
                    cursor.movePosition(QTextCursor.MoveOperation.Left)
                self.terminal.setTextCursor(cursor)
            elif cmd == 'G':
                col = n(0, 1)
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                for _ in range(col-1):
                    cursor.movePosition(QTextCursor.MoveOperation.Right)
                self.terminal.setTextCursor(cursor)
            elif cmd == 'd':
                row = n(0, 1)
                # Vertical position absolute
                cursor.movePosition(QTextCursor.MoveOperation.Start)
                for _ in range(row-1):
                    cursor.movePosition(QTextCursor.MoveOperation.Down)
                self.terminal.setTextCursor(cursor)
            elif cmd in ('l', 'h'):
                # Mode set/reset, ignore
                pass
            elif cmd == 'c':
                # Device attributes, ignore
                pass
            else:
                # Unknown CSI, ignore
                pass
        except Exception as e:
            # Don't crash on CSI parse
            pass

    def on_disconnect(self, msg):
        self.status_label.setText(f"Disconnected: {msg}")
        self.status_label.setStyleSheet("color: #f44336; font-size: 11px;")

    def keyPressEvent(self, event):
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        # Handle viewport resize
        if obj is self.terminal.viewport() and event.type() == event.Type.Resize:
            QTimer.singleShot(100, self.resizeEvent)
            return False

        if obj is self.terminal and event.type() == event.Type.KeyPress:
            key = event.key()
            mods = event.modifiers()
            text = event.text()

            # Handle font zoom (like linux terminal Ctrl+/-)
            if mods & Qt.KeyboardModifier.ControlModifier:
                if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
                    self._change_font(1)
                    return True
                elif key in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
                    self._change_font(-1)
                    return True
                elif key == Qt.Key.Key_0:
                    self.font_size = 10
                    self.terminal.setFont(_get_terminal_font(10))
                    return True
                if key == Qt.Key.Key_C:
                    if self.terminal.textCursor().hasSelection():
                        self.terminal.copy()
                        return True
                    else:
                        self._send(b'\x03')  # Ctrl-C interrupt like linux terminal
                        return True
                elif key == Qt.Key.Key_V:
                    # Paste from clipboard like linux terminal (Ctrl+Shift+V also)
                    clipboard = QApplication.clipboard()
                    clip_text = clipboard.text()
                    if clip_text:
                        # Send as if typed, handle bracketed paste
                        self._send(clip_text.encode('utf-8', errors='ignore'))
                    return True
                elif key == Qt.Key.Key_L:
                    self.terminal.clear()
                    if self.channel:
                        self._send(b'\x0c')  # Ctrl-L clears like linux
                    return True
                elif key == Qt.Key.Key_D:
                    if self.channel:
                        self._send(b'\x04')
                        return True
                elif key == Qt.Key.Key_A:
                    # Ctrl-A -> home
                    self._send(b'\x01')
                    return True
                elif key == Qt.Key.Key_E:
                    self._send(b'\x05')
                    return True
                elif key == Qt.Key.Key_K:
                    self._send(b'\x0b')
                    return True
                elif key == Qt.Key.Key_U:
                    self._send(b'\x15')
                    return True
                elif key == Qt.Key.Key_W:
                    self._send(b'\x17')
                    return True
                elif key == Qt.Key.Key_Z:
                    self._send(b'\x1a')
                    return True
                elif key == Qt.Key.Key_R:
                    self._send(b'\x12')
                    return True

            # Handle bracketed paste Shift+Insert
            if mods & Qt.KeyboardModifier.ShiftModifier and key == Qt.Key.Key_Insert:
                clipboard = QApplication.clipboard()
                clip_text = clipboard.text()
                if clip_text:
                    self._send(clip_text.encode('utf-8', errors='ignore'))
                return True

            # Handle special keys - linux terminal compatible
            if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
                self._send(b'\n')
                return True
            elif key == Qt.Key.Key_Backspace:
                # Send DEL (0x7f) like linux terminal (stty erase)
                # Do NOT locally delete; let server echo handle (fixes double delete)
                self._send(b'\x7f')
                return True
            elif key == Qt.Key.Key_Tab:
                self._send(b'\t')
                return True
            elif key == Qt.Key.Key_Up:
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    # Shift+Up -> scroll
                    self.terminal.verticalScrollBar().setValue(self.terminal.verticalScrollBar().value() - 20)
                    return True
                self._send(b'\x1b[A')
                return True
            elif key == Qt.Key.Key_Down:
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    self.terminal.verticalScrollBar().setValue(self.terminal.verticalScrollBar().value() + 20)
                    return True
                self._send(b'\x1b[B')
                return True
            elif key == Qt.Key.Key_Right:
                self._send(b'\x1b[C')
                return True
            elif key == Qt.Key.Key_Left:
                self._send(b'\x1b[D')
                return True
            elif key == Qt.Key.Key_Home:
                if mods & Qt.KeyboardModifier.ControlModifier:
                    self._send(b'\x1b[1;5H')
                else:
                    self._send(b'\x1b[H')
                return True
            elif key == Qt.Key.Key_End:
                if mods & Qt.KeyboardModifier.ControlModifier:
                    self._send(b'\x1b[1;5F')
                else:
                    self._send(b'\x1b[F')
                return True
            elif key == Qt.Key.Key_Delete:
                self._send(b'\x1b[3~')
                return True
            elif key == Qt.Key.Key_PageUp:
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    self.terminal.verticalScrollBar().setValue(self.terminal.verticalScrollBar().value() - 100)
                    return True
                self._send(b'\x1b[5~')
                return True
            elif key == Qt.Key.Key_PageDown:
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    self.terminal.verticalScrollBar().setValue(self.terminal.verticalScrollBar().value() + 100)
                    return True
                self._send(b'\x1b[6~')
                return True
            elif key == Qt.Key.Key_Escape:
                self._send(b'\x1b')
                return True
            elif key == Qt.Key.Key_F1:
                self._send(b'\x1bOP')
                return True
            elif key == Qt.Key.Key_F2:
                self._send(b'\x1bOQ')
                return True
            elif key == Qt.Key.Key_F3:
                self._send(b'\x1bOR')
                return True
            elif key == Qt.Key.Key_F4:
                self._send(b'\x1bOS')
                return True
            elif key in (Qt.Key.Key_F5, Qt.Key.Key_F6, Qt.Key.Key_F7, Qt.Key.Key_F8, Qt.Key.Key_F9, Qt.Key.Key_F10, Qt.Key.Key_F11, Qt.Key.Key_F12):
                n = key - Qt.Key.Key_F1 + 1
                # F5 n=5 -> \x1b[15~
                mapping = {5: "15~", 6: "17~", 7: "18~", 8: "19~", 9: "20~", 10: "21~", 11: "23~", 12: "24~"}
                seq = mapping.get(n, "15~")
                self._send(f"\x1b[{seq}".encode())
                return True
            elif text:
                # Regular character - send to shell like linux terminal
                # Handle Alt+char for meta
                if mods & Qt.KeyboardModifier.AltModifier:
                    self._send(b'\x1b' + text.encode('utf-8', errors='ignore'))
                else:
                    self._send(text.encode('utf-8', errors='ignore'))
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
