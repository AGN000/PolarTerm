import os, sys, time, shlex
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
                             QPushButton, QLabel, QTabWidget, QToolBar, QMessageBox, QInputDialog, QMenu, QFrame,
                             QTextEdit, QLineEdit, QComboBox, QGroupBox, QFormLayout, QToolButton)
from PyQt6.QtCore import Qt, QSize, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QFont

from core.config import load_sessions, save_sessions, add_or_update_session, delete_session, Session, load_bookmarks, save_bookmarks, add_bookmark, delete_bookmark, Bookmark
from core.ssh_client import SSHClientWrapper
from gui.session_dialog import SessionDialog
from gui.terminal_widget import TerminalWidget
from gui.file_transfer_widget import FileTransferWidget
from gui.penguin_widget import PenguinIdleWidget, IdleMonitor, FallingPenguinsOverlay, RadioPulseWidget
from gui.job_indicator import JobIndicatorWidget

def _icon_path():
    # try PolarTerm icon
    candidates = [
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "polarterm.png"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "polarterm_256.png"),
        os.path.join(os.path.expanduser("~"), "PolarTerm", "resources", "polarterm.png"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

class ConnectWorker(QThread):
    success = pyqtSignal(object, object)  # wrapper, session
    failed = pyqtSignal(str)
    def __init__(self, session, password, key_pass):
        super().__init__()
        self.session = session
        self.password = password
        self.key_pass = key_pass
        self.wrapper = None
    def run(self):
        try:
            w = SSHClientWrapper()
            w.connect(host=self.session.host, port=self.session.port, username=self.session.username,
                      password=self.password, key_path=self.session.key_path, key_passphrase=self.key_pass,
                      jump_host_str=self.session.jump_host)
            self.wrapper = w
            self.success.emit(w, self.session)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.failed.emit(str(e))
    def cancel(self):
        try:
            if self.wrapper:
                self.wrapper.close()
        except: pass
        self.terminate()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PolarTerm — HPC Terminal & File Manager")
        icon = _icon_path()
        if icon:
            self.setWindowIcon(QIcon(icon))
        self.resize(1400, 850)
        self.ssh_sessions = {}  # name -> SSHClientWrapper
        self.terminal_tabs = {} # name -> TerminalWidget (multiple per session stored as name-idx)
        self.transfer_tabs = {} # name -> FileTransferWidget
        self._setup_ui()
        # idle penguin monitor - must be before refresh_sessions
        self.idle_monitor = IdleMonitor(self, self.penguin_widget, idle_secs=18)
        self.refresh_sessions()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0,0,0,0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter, 1)

        # LEFT panel
        left = QFrame()
        left.setFrameStyle(QFrame.Shape.StyledPanel)
        left.setMaximumWidth(320)
        left.setMinimumWidth(260)
        left.setStyleSheet("QFrame { background: #fafafa; }")
        lyt = QVBoxLayout(left)
        lyt.setContentsMargins(8,8,8,8)

        # header with icon
        header = QHBoxLayout()
        icon = _icon_path()
        if icon:
            ic = QLabel()
            ic.setPixmap(QIcon(icon).pixmap(28,28))
            ic.setFixedSize(28,28)
            header.addWidget(ic)
        title = QLabel("PolarTerm")
        title.setStyleSheet("font-size:16px; font-weight:bold; color:#0c4a6e;")
        header.addWidget(title)
        header.addStretch()
        ver = QLabel("v1.0")
        ver.setStyleSheet("color:#0284c7; font-size:10px; background:#e0f2fe; padding:2px 6px; border-radius:8px;")
        header.addWidget(ver)
        lyt.addLayout(header)

        title2 = QLabel("📦 Sessions")
        title2.setStyleSheet("font-size:13px; font-weight:bold; padding:4px; color:#334155;")
        lyt.addWidget(title2)

        btn_row = QHBoxLayout()
        self.btn_new = QPushButton("＋ New")
        self.btn_new.setStyleSheet("background:#0284c7; color:white; font-weight:bold; padding:6px; border-radius:6px;")
        self.btn_new.clicked.connect(self.new_session)
        self.btn_edit = QPushButton("Edit")
        self.btn_edit.clicked.connect(self.edit_session)
        self.btn_del = QPushButton("Delete")
        self.btn_del.clicked.connect(self.delete_session)
        self.btn_del.setStyleSheet("color:#dc2626;")
        btn_row.addWidget(self.btn_new)
        btn_row.addWidget(self.btn_edit)
        btn_row.addWidget(self.btn_del)
        lyt.addLayout(btn_row)

        self.session_list = QListWidget()
        self.session_list.setStyleSheet("""
            QListWidget { background:white; border:1px solid #e2e8f0; border-radius:8px; }
            QListWidget::item { padding:8px; border-bottom:1px solid #f1f5f9; }
            QListWidget::item:selected { background:#e0f2fe; color:#0c4a6e; }
        """)
        self.session_list.doubleClicked.connect(self.connect_selected)
        self.session_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(self.on_session_context_menu)
        lyt.addWidget(self.session_list, 1)

        conn_layout = QVBoxLayout()
        self.btn_connect = QPushButton("▶ Connect")
        self.btn_connect.setStyleSheet("background:#0284c7; color:white; font-weight:bold; padding:10px; font-size:13px; border-radius:8px;")
        self.btn_connect.clicked.connect(self.connect_selected)
        self.btn_local = QPushButton("💻 Open Local Terminal")
        self.btn_local.clicked.connect(self.open_local_terminal)
        self.btn_local.setStyleSheet("padding:6px; border:1px solid #cbd5e1; border-radius:6px; background:white;")
        conn_layout.addWidget(self.btn_connect)
        conn_layout.addWidget(self.btn_local)
        lyt.addLayout(conn_layout)

        info = QLabel("Tip: Double-click session to connect. If you close Terminal/Files, <b>right-click session → Open Terminal / Open File Manager</b> to reopen without reconnecting. SFTP • Drag & drop • Terminal Here.")
        info.setWordWrap(True)
        info.setStyleSheet("color:#334155; font-size:11px; background:#f0f9ff; padding:6px; border:1px solid #bae6fd; border-radius:6px;")
        lyt.addWidget(info)

        hpc = QGroupBox("HPC Quick Bar")
        hpc.setStyleSheet("QGroupBox { font-weight:bold; color:#0c4a6e; }")
        f = QVBoxLayout(hpc)
        self.hpc_cmd = QComboBox()
        self.hpc_cmd.addItems(["Custom...", "squeue -u $USER", "qstat -u $USER", "sinfo -o \"%P %a %l %D %T\"", "qstat", "pestat", "module avail", "pwd; ls -lh", "watch -n2 squeue -u $USER"])
        self.hpc_cmd_edit = QLineEdit()
        self.hpc_cmd_edit.setPlaceholderText("type command to run on remote")
        btn_hpc = QPushButton("Send to Active Terminal")
        btn_hpc.setStyleSheet("background:#e0f2fe; border:1px solid #7dd3fc; border-radius:6px; padding:6px;")
        btn_hpc.clicked.connect(self.send_hpc_cmd)
        f.addWidget(self.hpc_cmd)
        f.addWidget(self.hpc_cmd_edit)
        f.addWidget(btn_hpc)
        self.hpc_cmd.currentTextChanged.connect(lambda t: self.hpc_cmd_edit.setText(t if t!="Custom..." else ""))
        lyt.addWidget(hpc)

        # Job indicator (icon showing running jobs)
        self.job_indicator = JobIndicatorWidget()
        lyt.addWidget(self.job_indicator)

        # Bookmarks - small window to bookmark folders for quick jump after login
        bm_box = QGroupBox("🔖 Bookmarks")
        bm_box.setStyleSheet("QGroupBox { font-weight:bold; color:#0c4a6e; }")
        bm_lyt = QVBoxLayout(bm_box)
        self.bookmark_list = QListWidget()
        self.bookmark_list.setStyleSheet("""
            QListWidget { background:white; border:1px solid #e2e8f0; border-radius:6px; }
            QListWidget::item { padding:6px; border-bottom:1px solid #f1f5f9; }
            QListWidget::item:selected { background:#fffbeb; color:#92400e; }
        """)
        self.bookmark_list.setMinimumHeight(90)
        self.bookmark_list.setMaximumHeight(160)
        self.bookmark_list.doubleClicked.connect(self.jump_bookmark)
        bm_lyt.addWidget(self.bookmark_list)
        bm_btn_row = QHBoxLayout()
        self.btn_bm_add = QPushButton("＋ Add")
        self.btn_bm_add.setToolTip("Bookmark current remote folder (from active Files tab)")
        self.btn_bm_add.setStyleSheet("background:#fffbeb; border:1px solid #fcd34d; padding:4px; border-radius:6px; font-size:11px;")
        self.btn_bm_add.clicked.connect(self.add_bookmark_current)
        self.btn_bm_del = QPushButton("✕")
        self.btn_bm_del.setFixedWidth(28)
        self.btn_bm_del.setToolTip("Delete selected bookmark")
        self.btn_bm_del.clicked.connect(self.del_bookmark)
        self.btn_bm_jump = QPushButton("→ Jump")
        self.btn_bm_jump.setToolTip("Jump to selected bookmark folder (works after login)")
        self.btn_bm_jump.setStyleSheet("background:#0284c7; color:white; padding:4px 8px; border-radius:6px; font-size:11px;")
        self.btn_bm_jump.clicked.connect(self.jump_bookmark)
        bm_btn_row.addWidget(self.btn_bm_add)
        bm_btn_row.addWidget(self.btn_bm_del)
        bm_btn_row.addWidget(self.btn_bm_jump)
        bm_lyt.addLayout(bm_btn_row)
        # manager button - small window as requested
        self.btn_bm_manage = QPushButton("📖 Manager — Small Window")
        self.btn_bm_manage.setToolTip("Open dedicated bookmark manager window (add/edit/jump with auto-jump on login)")
        self.btn_bm_manage.setStyleSheet("background:white; border:1px solid #cbd5e1; padding:4px; border-radius:6px; font-size:11px;")
        self.btn_bm_manage.clicked.connect(self.open_bookmark_manager)
        bm_lyt.addWidget(self.btn_bm_manage)
        # small hint
        bm_hint = QLabel("Double-click to jump. Bookmarks persist and auto-jump option on connect.")
        bm_hint.setWordWrap(True)
        bm_hint.setStyleSheet("color:#92400e; font-size:9px;")
        bm_lyt.addWidget(bm_hint)
        lyt.addWidget(bm_box)
        self.refresh_bookmarks()

        self.left_status = QLabel("Ready")
        self.left_status.setStyleSheet("color:#64748b; font-size:10px;")
        lyt.addWidget(self.left_status)

        splitter.addWidget(left)

        # RIGHT: tab widget
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border:1px solid #e2e8f0; background:white; }
            QTabBar::tab { background:#f8fafc; padding:8px 16px; border:1px solid #e2e8f0; border-bottom:none; margin-right:2px; border-top-left-radius:8px; border-top-right-radius:8px; }
            QTabBar::tab:selected { background:white; color:#0284c7; font-weight:bold; }
        """)
        welcome = self._create_welcome()
        self.tabs.addTab(welcome, "🏠 Home")
        self.tabs.tabBar().setTabButton(0, self.tabs.tabBar().ButtonPosition.RightSide, None)
        splitter.addWidget(self.tabs)
        splitter.setSizes([300, 1100])

        # penguin idle widget at bottom of main layout (outside splitter)
        self.penguin_widget = PenguinIdleWidget()
        main_layout.addWidget(self.penguin_widget)

        # falling overlay (supports penguin/rose/ice/feather on same icon)
        self.penguin_fall = FallingPenguinsOverlay(central)
        self.penguin_fall.hide()
        # radio pulse for icon click
        self.radio_pulse = RadioPulseWidget(central)
        self.radio_pulse.hide()
        self._fall_mode = "penguin"  # cycle state

        # menubar
        menubar = self.menuBar()
        m_file = menubar.addMenu("File")
        act_new = QAction("New Session", self)
        act_new.setShortcut("Ctrl+N")
        act_new.triggered.connect(self.new_session)
        m_file.addAction(act_new)
        act_local = QAction("Open Local Terminal", self)
        act_local.setShortcut("Ctrl+T")
        act_local.triggered.connect(self.open_local_terminal)
        m_file.addAction(act_local)
        m_file.addSeparator()
        act_quit = QAction("Quit", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        m_file.addAction(act_quit)
        m_help = menubar.addMenu("Help")
        act_about = QAction("About PolarTerm", self)
        act_about.triggered.connect(self.show_about)
        m_help.addAction(act_about)
        m_bm = menubar.addMenu("Bookmarks")
        act_bm_manager = QAction("📖 Bookmark Manager (Small Window)", self)
        act_bm_manager.setShortcut("Ctrl+B")
        act_bm_manager.triggered.connect(self.open_bookmark_manager)
        m_bm.addAction(act_bm_manager)
        act_bm_add = QAction("＋ Add Current Folder", self)
        act_bm_add.triggered.connect(self.add_bookmark_current)
        m_bm.addAction(act_bm_add)

        tb = QToolBar("Main")
        tb.setIconSize(QSize(16,16))
        self.addToolBar(tb)
        tb.addAction(act_new)
        act_conn = QAction(QIcon.fromTheme("network-wired"), "Connect", self)
        act_conn.triggered.connect(self.connect_selected)
        tb.addAction(act_conn)
        tb.addSeparator()
        tb.addAction(act_local)
        act_disc = QAction("Disconnect All", self)
        act_disc.triggered.connect(self.disconnect_all)
        tb.addAction(act_disc)
        tb.addSeparator()
        # Same icon with multiple fall animations (penguin/rose/ice/feather) + radio pulse
        self.btn_snow_tool = QToolButton(self)
        self.btn_snow_tool.setIcon(QIcon(_icon_path()) if _icon_path() else QIcon.fromTheme("weather-snow"))
        self.btn_snow_tool.setText("❄ Fall")
        self.btn_snow_tool.setToolTip("Same icon — click for penguin snow, dropdown for rose/ice/feather/mixture. Shows radio pulse on click.")
        self.btn_snow_tool.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_snow_tool.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        # menu for same icon with different animations
        snow_menu = QMenu(self.btn_snow_tool)
        for label, mode, tip in [
            ("🐧 Penguin Snow", "penguin", "Classic penguins + snow"),
            ("🌹 Rose Petals", "rose", "Falling rose petals"),
            ("🧊 Ice Crystals", "ice", "Ice crystals & snow"),
            ("🪶 Feather Fall", "feather", "Light feathers drifting"),
            ("😊 Smiley Rain", "smiley", "Falling smileys"),
            ("👍 Thumbs Up", "thumbs", "Thumbs up & claps"),
            ("🎭 Mixed", "mixed", "Penguins + roses + ice + feathers + smileys"),
        ]:
            act = QAction(label, self)
            act.setToolTip(tip)
            act.triggered.connect(lambda checked, m=mode, l=label: self.trigger_fall_mode(m, l))
            snow_menu.addAction(act)
        self.btn_snow_tool.setMenu(snow_menu)
        # click on icon itself (not dropdown) → penguin + radio pulse (and cycle)
        self.btn_snow_tool.clicked.connect(lambda: self.trigger_fall_with_radio("penguin"))
        tb.addWidget(self.btn_snow_tool)

    def _create_welcome(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setAlignment(Qt.AlignmentFlag.AlignTop)
        # top banner with penguin
        banner = QHBoxLayout()
        if _icon_path():
            ic = QLabel()
            ic.setPixmap(QIcon(_icon_path()).pixmap(64,64))
            ic.setFixedSize(64,64)
            banner.addWidget(ic)
        col = QVBoxLayout()
        title = QLabel("Welcome to PolarTerm")
        title.setStyleSheet("font-size:24px; font-weight:bold; color:#0c4a6e;")
        col.addWidget(title)
        sub = QLabel("HPC Terminal & File Manager for Linux • Secure • Drag & Drop • Penguin Powered 🐧")
        sub.setStyleSheet("font-size:13px; color:#475569;")
        col.addWidget(sub)
        banner.addLayout(col)
        banner.addStretch()
        # idle demo button + falling button (same icon, multiple animations)
        btn_box = QVBoxLayout()
        btn_peng = QPushButton("🐧 Wake Penguin")
        btn_peng.setStyleSheet("background:#e0f2fe; border:1px solid #7dd3fc; padding:8px 12px; border-radius:8px;")
        btn_peng.clicked.connect(lambda: self.penguin_widget.start() if not self.penguin_widget.isVisible() else self.penguin_widget.stop())
        btn_box.addWidget(btn_peng)
        # Same PolarTerm icon with rose/ice/feather/penguin cycle + radio pulse
        self.btn_fall_welcome = QToolButton()
        self.btn_fall_welcome.setIcon(QIcon(_icon_path()) if _icon_path() else QIcon())
        self.btn_fall_welcome.setText("❄ Let it Snow!")
        self.btn_fall_welcome.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_fall_welcome.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.btn_fall_welcome.setToolTip("Same icon — click for penguin snow, dropdown for rose/ice/feather. Click shows radio pulse.")
        self.btn_fall_welcome.setStyleSheet("background:#0284c7; color:white; font-weight:bold; padding:8px 12px; border-radius:8px;")
        fall_menu = QMenu(self.btn_fall_welcome)
        for label, mode in [("🐧 Penguin Snow","penguin"),("🌹 Rose Petals","rose"),("🧊 Ice Crystals","ice"),("🪶 Feather Fall","feather"),("😊 Smiley Rain","smiley"),("👍 Thumbs Up","thumbs"),("🎭 Mixed","mixed")]:
            act = QAction(label, self)
            act.triggered.connect(lambda checked, m=mode, l=label: self.trigger_fall_mode(m, l))
            fall_menu.addAction(act)
        self.btn_fall_welcome.setMenu(fall_menu)
        self.btn_fall_welcome.clicked.connect(lambda: self.trigger_fall_with_radio("penguin"))
        btn_box.addWidget(self.btn_fall_welcome)
        banner.addLayout(btn_box)
        l.addLayout(banner)

        cards = QHBoxLayout()
        for text in [
            ("🖥 Terminal", "Full interactive SSH shell\ntabs, colors, jump hosts\n+ Terminal Here from files"),
            ("📁 File Transfer", "Dual-pane SFTP\n drag & drop, progress\n local ↔ remote"),
            ("🔒 Secure", "Fernet encrypted passwords\n0600 perms, no plain text\n SSH key support"),
            ("🐧 Penguin", "Idle animation when\n you stare too long\n like classic MobaXterm"),
        ]:
            card = QLabel(f"<b>{text[0]}</b><br><br>{text[1].replace(chr(10),'<br>')}")
            card.setStyleSheet("background:white; border:1px solid #e2e8f0; border-radius:10px; padding:14px; font-size:12px;")
            card.setAlignment(Qt.AlignmentFlag.AlignTop)
            cards.addWidget(card)
        l.addLayout(cards)

        hint = QTextEdit()
        hint.setReadOnly(True)
        hint.setMaximumHeight(220)
        hint.setStyleSheet("background:#0f172a; color:#e2e8f0; font-family: monospace; padding:10px; border-radius:8px;")
        hint.setText("""Quick start:
1. Click ＋ New → Host, User, Auth (password or ~/.ssh/id_rsa)
2. Double-click session → Terminal + Files tabs open
3. In Files: navigate → right-click → 🖥 Terminal Here or drag & drop
4. For HPC: set Remote Path to /scratch/$USER, use HPC Quick Bar

New in PolarTerm:
  • Encrypted passwords (Fernet, 0600)
  • Drag & drop + Cut/Copy/Paste (Ctrl+C/X/V, Del) duplicate
  • Right-click → Edit Locally (auto-upload), Bookmark, New Folder (host)
  • Penguin idle (18s) + ❄ Fall (same icon): 🐧/🌹/🧊/🪶/🎭 + radio pulse on click
  • Job indicator (squeue/qstat) + Bookmarks window
  • Nice PolarTerm icon (no MobaXterm conflict)""")
        l.addWidget(hint)

        footer = QLabel("PolarTerm v1.0 • Built with PyQt6 + Paramiko • Shows 🐧 when idle • Icon: polarterm.png")
        footer.setStyleSheet("color:#64748b; font-size:11px;")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.addWidget(footer)
        l.addStretch()
        return w

    def refresh_sessions(self):
        self.session_list.clear()
        sessions = load_sessions()
        for s in sessions:
            item = QListWidgetItem(f"{s.name}\n  {s.username}@{s.host}:{s.port}  •  {s.auth_method}  {('• '+s.notes) if s.notes else ''}")
            item.setData(Qt.ItemDataRole.UserRole, s.name)
            self.session_list.addItem(item)
        self.left_status.setText(f"{len(sessions)} sessions loaded")
        self.idle_monitor.touch()

    def get_selected_session(self):
        item = self.session_list.currentItem()
        if not item:
            return None
        name = item.data(Qt.ItemDataRole.UserRole)
        for s in load_sessions():
            if s.name==name:
                return s
        return None

    def on_session_context_menu(self, pos):
        item = self.session_list.itemAt(pos)
        if not item:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        s = None
        for sess in load_sessions():
            if sess.name == name:
                s = sess
                break
        if not s:
            return
        menu = QMenu(self)
        is_connected = name in self.ssh_sessions and self.ssh_sessions[name].connected
        # Check if tabs exist
        has_term = any(name in k for k in self.terminal_tabs.keys()) or name in self.terminal_tabs
        has_files = name in self.transfer_tabs
        act_connect = menu.addAction("▶ Connect" if not is_connected else "✓ Connected (focus)")
        act_open_term = menu.addAction("🖥 Open Terminal" + (" (new)" if has_term else ""))
        act_open_files = menu.addAction("📁 Open File Manager" + (" (new)" if has_files else ""))
        act_reopen_both = menu.addAction("🔄 Reopen Terminal + Files")
        menu.addSeparator()
        act_disconnect = menu.addAction("⏏ Disconnect")
        act_disconnect.setEnabled(is_connected)
        act = menu.exec(self.session_list.viewport().mapToGlobal(pos))
        if not act:
            return
        if act == act_connect:
            self.session_list.setCurrentItem(item)
            self.connect_selected()
        elif act == act_open_term:
            self.session_list.setCurrentItem(item)
            if is_connected:
                self.open_terminal_for_session(name)
            else:
                self.connect_selected()
        elif act == act_open_files:
            self.session_list.setCurrentItem(item)
            if is_connected:
                self.open_files_for_session(name)
            else:
                self.connect_selected()
        elif act == act_reopen_both:
            self.session_list.setCurrentItem(item)
            if is_connected:
                self.open_terminal_for_session(name)
                self.open_files_for_session(name)
            else:
                self.connect_selected()
        elif act == act_disconnect:
            if name in self.ssh_sessions:
                try: self.ssh_sessions[name].close()
                except: pass
                del self.ssh_sessions[name]
                # close related tabs
                for idx in reversed(range(self.tabs.count())):
                    w = self.tabs.widget(idx)
                    txt = self.tabs.tabText(idx)
                    if name in txt:
                        try:
                            if isinstance(w, TerminalWidget):
                                w.close_shell()
                        except: pass
                        self.tabs.removeTab(idx)
                self.job_indicator.clear()
                self.left_status.setText(f"Disconnected {name}")

    def open_terminal_for_session(self, session_name):
        self.idle_monitor.touch()
        if session_name not in self.ssh_sessions or not self.ssh_sessions[session_name].connected:
            QMessageBox.information(self, "Not connected", f"{session_name} not connected. Click Connect first.")
            return
        wrapper = self.ssh_sessions[session_name]
        # check if terminal already open - focus it
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i).startswith(f"🖥 {session_name}"):
                self.tabs.setCurrentIndex(i)
                return
        # create new terminal
        term = TerminalWidget(ssh_wrapper=wrapper)
        # use same logic as open_remote_terminal_at but for root
        try:
            channel = wrapper.client.invoke_shell(term="xterm-256color", width=120, height=30)
            channel.settimeout(0.0)
            term.ssh = wrapper
            term.channel = channel
            from gui.terminal_widget import ShellReaderThread
            term.reader = ShellReaderThread(channel)
            term.reader.data_received.connect(term.on_data)
            term.reader.disconnected.connect(term.on_disconnect)
            term.reader.start()
            term.status_label.setText(f"Connected to {wrapper.host} | Shell for {session_name}")
            term.status_label.setStyleSheet("color: #0ea5e9; font-size: 11px;")
        except Exception as e:
            QMessageBox.warning(self, "Terminal error", str(e))
            return
        idx = self.tabs.addTab(term, f"🖥 {session_name}")
        self.tabs.setCurrentIndex(idx)
        key = f"{session_name}-term-{idx}-{int(time.time())}"
        self.terminal_tabs[key]=term

    def open_files_for_session(self, session_name):
        self.idle_monitor.touch()
        if session_name not in self.ssh_sessions or not self.ssh_sessions[session_name].connected:
            QMessageBox.information(self, "Not connected", f"{session_name} not connected. Click Connect first.")
            return
        # if already open, focus
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i).startswith(f"📁 {session_name}"):
                self.tabs.setCurrentIndex(i)
                return
        wrapper = self.ssh_sessions[session_name]
        # find session config for remote_path
        s = None
        for sess in load_sessions():
            if sess.name == session_name:
                s = sess
                break
        ft = FileTransferWidget(ssh_wrapper=wrapper)
        # set paths
        if s and s.remote_path and s.remote_path!="~":
            ft.remote_browser.current_path = s.remote_path
            ft.remote_browser.path_edit.setText(s.remote_path)
        ft.set_ssh(wrapper)
        # connect signals
        ft.remote_browser.open_terminal_here.connect(lambda path, ssh=wrapper, name=session_name: self.open_remote_terminal_at(ssh, path, name))
        ft.local_browser.open_terminal_here.connect(lambda path: self.open_local_terminal_at(path))
        ft.remote_browser.bookmark_requested.connect(lambda path, name=session_name: self.add_bookmark_path(path, name, "remote"))
        ft.local_browser.bookmark_requested.connect(lambda path, name=session_name: self.add_bookmark_path(path, name, "local"))
        idx = self.tabs.addTab(ft, f"📁 {session_name} - Files")
        self.tabs.setCurrentIndex(idx)
        self.transfer_tabs[session_name]=ft
        self.job_indicator.set_session(wrapper, session_name)

    def new_session(self):
        self.idle_monitor.touch()
        dlg = SessionDialog(self)
        if dlg.exec():
            s = dlg.get_session()
            for ex in load_sessions():
                if ex.name==s.name:
                    QMessageBox.warning(self, "Exists", f"Session '{s.name}' already exists.")
                    return
            add_or_update_session(s)
            self.refresh_sessions()

    def edit_session(self):
        self.idle_monitor.touch()
        s = self.get_selected_session()
        if not s:
            QMessageBox.information(self, "Select", "Select a session to edit.")
            return
        dlg = SessionDialog(self, s)
        if dlg.exec():
            ns = dlg.get_session()
            if ns.name != s.name:
                delete_session(s.name)
            add_or_update_session(ns)
            self.refresh_sessions()

    def delete_session(self):
        s = self.get_selected_session()
        if not s:
            return
        if QMessageBox.question(self, "Delete", f"Delete session '{s.name}'?")==QMessageBox.StandardButton.Yes:
            delete_session(s.name)
            self.refresh_sessions()

    # --- Bookmarks ---
    def refresh_bookmarks(self):
        self.bookmark_list.clear()
        for bm in load_bookmarks():
            icon = "📁" if bm.kind=="remote" else "💻"
            txt = f"{icon} {bm.alias} → {bm.path}"
            if bm.session:
                txt += f"  ({bm.session})"
            item = QListWidgetItem(txt)
            item.setData(Qt.ItemDataRole.UserRole, (bm.alias, bm.session))
            self.bookmark_list.addItem(item)
        if self.bookmark_list.count()==0:
            self.bookmark_list.addItem("No bookmarks yet — add current folder")

    def add_bookmark_current(self):
        # try to get current paths from active Files tab (both local and remote)
        cur = self.tabs.currentWidget()
        from gui.file_transfer_widget import FileTransferWidget
        remote_path = None
        local_path = None
        session_name = ""
        if isinstance(cur, FileTransferWidget):
            # has both browsers, even if not connected local is always valid
            local_path = cur.local_browser.current_path
            if cur.ssh and cur.ssh.connected:
                remote_path = cur.remote_browser.current_path
                for name, ssh in self.ssh_sessions.items():
                    if ssh == cur.ssh:
                        session_name = name
                        break
        if not remote_path and not local_path:
            for name, ft in self.transfer_tabs.items():
                if ft.ssh and ft.ssh.connected:
                    remote_path = ft.remote_browser.current_path
                    local_path = ft.local_browser.current_path
                    session_name = name
                    break
        # decide which to bookmark: if both available, ask user
        target_path = None
        kind = "remote"
        if remote_path and local_path:
            # ask
            from PyQt6.QtWidgets import QInputDialog
            items = [f"Remote: {remote_path}", f"Local: {local_path}"]
            choice, ok = QInputDialog.getItem(self, "Bookmark", "Bookmark which current folder?", items, 0, False)
            if not ok:
                return
            if choice.startswith("Local:"):
                target_path = local_path
                kind = "local"
            else:
                target_path = remote_path
                kind = "remote"
        elif remote_path:
            target_path = remote_path
            kind = "remote"
        elif local_path:
            target_path = local_path
            kind = "local"
        else:
            s = self.get_selected_session()
            if s:
                target_path = s.remote_path
                session_name = s.name
                kind = "remote"
            else:
                QMessageBox.information(self, "No folder", "Open a Files tab first, then bookmark.")
                return
        alias, ok = QInputDialog.getText(self, "Bookmark Folder", f"Alias for {target_path}:", text=os.path.basename(target_path.rstrip("/")) or target_path)
        if not ok or not alias.strip():
            return
        alias = alias.strip()
        bm = Bookmark(alias=alias, path=target_path, session=session_name, kind=kind)
        add_bookmark(bm)
        self.refresh_bookmarks()
        self.left_status.setText(f"Bookmarked {alias} → {target_path}")

    def add_bookmark_path(self, path, session_name, kind="remote"):
        alias, ok = QInputDialog.getText(self, "Bookmark Folder", f"Alias for {path}:", text=os.path.basename(path.rstrip("/")) or path)
        if not ok or not alias.strip():
            return
        alias = alias.strip()
        bm = Bookmark(alias=alias, path=path, session=session_name, kind=kind)
        add_bookmark(bm)
        self.refresh_bookmarks()
        self.left_status.setText(f"Bookmarked {alias} → {path}")

    def del_bookmark(self):
        item = self.bookmark_list.currentItem()
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            return
        alias, session = item.data(Qt.ItemDataRole.UserRole)
        if QMessageBox.question(self, "Delete Bookmark", f"Delete bookmark '{alias}'?")==QMessageBox.StandardButton.Yes:
            delete_bookmark(alias, session)
            self.refresh_bookmarks()

    def jump_bookmark(self):
        item = self.bookmark_list.currentItem()
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            return
        alias, session = item.data(Qt.ItemDataRole.UserRole)
        # find bookmark
        for bm in load_bookmarks():
            if bm.alias==alias and bm.session==session:
                # find FileTransferWidget to jump
                target_ft = None
                target_ssh = None
                if bm.session and bm.session in self.transfer_tabs:
                    target_ft = self.transfer_tabs[bm.session]
                    target_ssh = self.ssh_sessions.get(bm.session)
                else:
                    # try active
                    cur = self.tabs.currentWidget()
                    if isinstance(cur, FileTransferWidget):
                        target_ft = cur
                    elif self.transfer_tabs:
                        target_ft = list(self.transfer_tabs.values())[0]
                if target_ft:
                    # handle both local and remote bookmarks
                    if bm.kind == "local":
                        target_ft.local_browser.current_path = bm.path
                        target_ft.local_browser.path_edit.setText(bm.path)
                        target_ft.local_browser.refresh()
                    else:
                        target_ft.remote_browser.current_path = bm.path
                        target_ft.remote_browser.path_edit.setText(bm.path)
                        target_ft.remote_browser.refresh()
                    # also bring tab to front
                    for i in range(self.tabs.count()):
                        if self.tabs.widget(i)==target_ft:
                            self.tabs.setCurrentIndex(i)
                            break
                    self.left_status.setText(f"Jumped to {bm.alias}: {bm.path}")
                else:
                    # not connected - set session's remote_path for next login
                    # update session to use this path as default
                    for s in load_sessions():
                        if s.name==bm.session:
                            s.remote_path = bm.path
                            add_or_update_session(s)
                            self.refresh_sessions()
                            QMessageBox.information(self, "Bookmark", f"Will jump to {bm.path} on next connect to {bm.session}")
                            break
                    else:
                        QMessageBox.information(self, "Bookmark", f"Bookmark path: {bm.path}\nConnect to a session first to jump.")
                break
        self.idle_monitor.touch()

    def open_bookmark_manager(self):
        # small dedicated window as requested
        from gui.bookmark_manager import BookmarkManagerDialog
        dlg = BookmarkManagerDialog(self, initial_session=self.get_selected_session().name if self.get_selected_session() else "")
        dlg.exec()
        self.refresh_bookmarks()
        self.refresh_sessions()  # in case default changed

    def connect_selected(self):
        self.idle_monitor.touch()
        if hasattr(self, '_connect_worker') and self._connect_worker and self._connect_worker.isRunning():
            QMessageBox.information(self, "Connecting", "Already connecting, please wait...")
            return
        s = self.get_selected_session()
        if not s:
            QMessageBox.information(self, "Select", "Select a session and click Connect (or double-click).")
            return
        if s.name in self.ssh_sessions and self.ssh_sessions[s.name].connected:
            # If already connected, allow reopening closed GUIs without reconnecting
            wrapper = self.ssh_sessions[s.name]
            has_term = any(k==s.name or k.startswith(s.name+"-term") for k in self.terminal_tabs.keys())
            # also check actual tabs
            for i in range(self.tabs.count()):
                if self.tabs.tabText(i).startswith(f"🖥 {s.name}"):
                    has_term = True
                    break
            has_files = s.name in self.transfer_tabs
            for i in range(self.tabs.count()):
                if self.tabs.tabText(i).startswith(f"📁 {s.name}"):
                    has_files = True
                    break
            if has_term and has_files:
                # both exist, just focus
                for i in range(self.tabs.count()):
                    if self.tabs.tabText(i).startswith(s.name):
                        self.tabs.setCurrentIndex(i)
                        return
            # need to reopen missing ones using existing wrapper
            if not has_term:
                term = TerminalWidget(ssh_wrapper=wrapper)
                try:
                    channel = wrapper.client.invoke_shell(term="xterm-256color", width=120, height=30)
                    channel.settimeout(0.0)
                    term.ssh = wrapper
                    term.channel = channel
                    from gui.terminal_widget import ShellReaderThread
                    term.reader = ShellReaderThread(channel)
                    term.reader.data_received.connect(term.on_data)
                    term.reader.disconnected.connect(term.on_disconnect)
                    term.reader.start()
                    term.status_label.setText(f"Connected to {wrapper.host} | Reopened terminal for {s.name}")
                except Exception as e:
                    term.status_label.setText(f"Terminal error: {e}")
                idx = self.tabs.addTab(term, f"🖥 {s.name}")
                self.tabs.setCurrentIndex(idx)
                key = f"{s.name}-term-{idx}-{int(time.time())}"
                self.terminal_tabs[key]=term
                has_term = True
            if not has_files:
                ft = FileTransferWidget(ssh_wrapper=wrapper)
                if s.remote_path and s.remote_path!="~":
                    ft.remote_browser.current_path = s.remote_path
                    ft.remote_browser.path_edit.setText(s.remote_path)
                ft.set_ssh(wrapper)
                if s.local_path:
                    ft.local_browser.current_path = s.local_path
                    ft.local_browser.path_edit.setText(s.local_path)
                    ft.local_browser.refresh()
                ft.remote_browser.open_terminal_here.connect(lambda path, ssh=wrapper, name=s.name: self.open_remote_terminal_at(ssh, path, name))
                ft.local_browser.open_terminal_here.connect(lambda path: self.open_local_terminal_at(path))
                ft.remote_browser.bookmark_requested.connect(lambda path, name=s.name: self.add_bookmark_path(path, name, "remote"))
                ft.local_browser.bookmark_requested.connect(lambda path, name=s.name: self.add_bookmark_path(path, name, "local"))
                idx = self.tabs.addTab(ft, f"📁 {s.name} - Files")
                self.transfer_tabs[s.name]=ft
                self.job_indicator.set_session(wrapper, s.name)
                if not has_term:
                    self.tabs.setCurrentIndex(idx)
            # if we reopened, done
            if has_term or has_files:
                return
        password = s.password
        key_pass = s.key_passphrase
        if s.auth_method=="password" and not password:
            pw, ok = QInputDialog.getText(self, "Password", f"Password for {s.username}@{s.host}:", echo=QLineEdit.EchoMode.Password)
            if not ok:
                return
            password = pw
        # Non-blocking connect via worker to avoid GNOME "Not Responding / Force Quit"
        self.left_status.setText(f"Connecting to {s.host}:{s.port}...")
        self.btn_connect.setEnabled(False)
        self.btn_connect.setText("⏳ Connecting...")
        # show small non-modal progress
        from PyQt6.QtWidgets import QProgressDialog
        self._progress = QProgressDialog(f"Connecting to {s.name} ({s.username}@{s.host}:{s.port})...", "Cancel", 0, 0, self)
        self._progress.setWindowTitle("PolarTerm — Connecting")
        self._progress.setWindowModality(Qt.WindowModality.NonModal)
        self._progress.setMinimumDuration(200)
        self._progress.setCancelButtonText("Cancel")
        self._progress.canceled.connect(lambda: self._cancel_connect())
        self._progress.show()
        self._connect_worker = ConnectWorker(s, password, key_pass)
        self._connect_worker.success.connect(self._on_connect_success)
        self._connect_worker.failed.connect(self._on_connect_failed)
        self._connect_worker.finished.connect(lambda: self._progress.close() if hasattr(self, '_progress') else None)
        self._connect_worker.start()

    def _cancel_connect(self):
        if hasattr(self, '_connect_worker') and self._connect_worker.isRunning():
            self._connect_worker.cancel()
            self.left_status.setText("Cancelled")
            self.btn_connect.setEnabled(True)
            self.btn_connect.setText("▶ Connect")

    def _on_connect_success(self, wrapper, s):
        self.ssh_sessions[s.name] = wrapper
        self.left_status.setText(f"Connected: {s.name}")
        self.btn_connect.setEnabled(True)
        self.btn_connect.setText("▶ Connect")
        if hasattr(self, '_progress'):
            self._progress.close()
        term = TerminalWidget(ssh_wrapper=wrapper)
        term_idx = self.tabs.addTab(term, f"🖥 {s.name}")
        term.connect_ssh(wrapper)
        ft = FileTransferWidget(ssh_wrapper=wrapper)
        ft_idx = self.tabs.addTab(ft, f"📁 {s.name} - Files")
        if s.remote_path and s.remote_path!="~":
            ft.remote_browser.current_path = s.remote_path
            ft.remote_browser.path_edit.setText(s.remote_path)
        ft.set_ssh(wrapper)
        if s.local_path:
            ft.local_browser.current_path = s.local_path
            ft.local_browser.path_edit.setText(s.local_path)
            ft.local_browser.refresh()
        ft.remote_browser.open_terminal_here.connect(lambda path, ssh=wrapper, name=s.name: self.open_remote_terminal_at(ssh, path, name))
        ft.local_browser.open_terminal_here.connect(lambda path: self.open_local_terminal_at(path))
        ft.remote_browser.bookmark_requested.connect(lambda path, name=s.name: self.add_bookmark_path(path, name, "remote"))
        ft.local_browser.bookmark_requested.connect(lambda path, name=s.name: self.add_bookmark_path(path, name, "local"))
        self.job_indicator.set_session(wrapper, s.name)
        self.tabs.setCurrentIndex(term_idx)
        self.terminal_tabs[s.name]=term
        self.transfer_tabs[s.name]=ft
        self._connect_worker = None

    def _on_connect_failed(self, msg):
        self.btn_connect.setEnabled(True)
        self.btn_connect.setText("▶ Connect")
        if hasattr(self, '_progress'):
            self._progress.close()
        # find session name from worker if possible
        sname = self._connect_worker.session.name if hasattr(self, '_connect_worker') and self._connect_worker.session else "session"
        QMessageBox.critical(self, "Connection Failed", f"Could not connect to {sname}:\n{msg}\n\nTips:\n• Check host/port/user\n• Check auth (password/key)\n• Jump host format user@host:port\n• VPN/firewall\n• Try increasing timeout")
        self.left_status.setText(f"Failed: {msg}")
        self._connect_worker = None

    def open_local_terminal(self):
        self.idle_monitor.touch()
        import datetime
        name = f"Local-{datetime.datetime.now().strftime('%H%M%S')}"
        term = TerminalWidget()
        idx = self.tabs.addTab(term, f"💻 {name}")
        self.tabs.setCurrentIndex(idx)
        term.connect_local()

    def open_local_terminal_at(self, path):
        self.idle_monitor.touch()
        term = TerminalWidget()
        idx = self.tabs.addTab(term, f"💻 {os.path.basename(path) or path}")
        self.tabs.setCurrentIndex(idx)
        term.connect_local()
        # cd after a short delay
        safe = path.replace("'", "'\"'\"'")
        QTimer.singleShot(600, lambda: term._send(f"cd '{safe}' && pwd\n".encode()))

    def open_remote_terminal_at(self, ssh_wrapper, remote_path, session_name):
        self.idle_monitor.touch()
        # create new terminal tab with same ssh connection (new channel)
        # ensure path is sanitized for shell
        safe = remote_path.replace("'", "'\"'\"'")
        term = TerminalWidget(ssh_wrapper=ssh_wrapper)
        # we need to create a fresh channel without overwriting wrapper.shell too much - use client.invoke_shell directly
        try:
            channel = ssh_wrapper.client.invoke_shell(term="xterm-256color", width=120, height=30)
            channel.settimeout(0.0)
            term.ssh = ssh_wrapper
            term.channel = channel
            from gui.terminal_widget import ShellReaderThread
            term.reader = ShellReaderThread(channel)
            term.reader.data_received.connect(term.on_data)
            term.reader.disconnected.connect(term.on_disconnect)
            term.reader.start()
            term.status_label.setText(f"Connected to {ssh_wrapper.host}:{safe} | Shell in {remote_path}")
            term.status_label.setStyleSheet("color: #0ea5e9; font-size: 11px;")
        except Exception as e:
            QMessageBox.warning(self, "Terminal error", str(e))
            return
        idx = self.tabs.addTab(term, f"🖥 {session_name} - {os.path.basename(remote_path) or remote_path}")
        self.tabs.setCurrentIndex(idx)
        # cd into folder after a brief delay
        QTimer.singleShot(500, lambda: term._send(f"cd '{safe}' && pwd && clear\n".encode()))
        # store with unique key
        key = f"{session_name}-term-{idx}"
        self.terminal_tabs[key]=term

    def send_hpc_cmd(self):
        self.idle_monitor.touch()
        cmd = self.hpc_cmd_edit.text().strip()
        if not cmd:
            cmd = self.hpc_cmd.currentText()
            if cmd=="Custom...":
                return
        cur = self.tabs.currentWidget()
        if isinstance(cur, TerminalWidget):
            cur._send((cmd+"\n").encode())
        else:
            for name, t in self.terminal_tabs.items():
                t._send((cmd+"\n").encode())
                self.left_status.setText(f"Sent to {name}: {cmd}")
                break
            else:
                QMessageBox.information(self, "No terminal", "Open/Select a terminal tab first.")

    def close_tab(self, idx):
        w = self.tabs.widget(idx)
        # keep SSH alive so you can reopen — only remove tab bookkeeping
        if isinstance(w, TerminalWidget):
            w.close_shell()
            for k,v in list(self.terminal_tabs.items()):
                if v==w:
                    del self.terminal_tabs[k]
                    break
        elif isinstance(w, FileTransferWidget):
            for k,v in list(self.transfer_tabs.items()):
                if v==w:
                    del self.transfer_tabs[k]
                    break
        self.tabs.removeTab(idx)
        # keep job indicator if any SSH still alive (even with no tabs)
        if not self.ssh_sessions:
            self.job_indicator.clear()
        else:
            # keep showing first session, even if its tabs were closed — so reopen works
            first = list(self.ssh_sessions.items())[0]
            # only clear if that session's tabs are gone but keep indicator
            # leave indicator as is
            pass
        if self.tabs.count()==0:
            self.tabs.addTab(self._create_welcome(), "🏠 Home")

    def disconnect_all(self):
        self.idle_monitor.touch()
        for k, cli in list(self.ssh_sessions.items()):
            try: cli.close()
            except: pass
        self.ssh_sessions.clear()
        for i in reversed(range(self.tabs.count())):
            w = self.tabs.widget(i)
            if isinstance(w, (TerminalWidget, FileTransferWidget)):
                self.tabs.removeTab(i)
        self.job_indicator.clear()
        self.left_status.setText("All disconnected")

    def show_about(self):
        self.idle_monitor.touch()
        QMessageBox.about(self, "About PolarTerm",
            "<b>PolarTerm v1.0</b> — Polar + Terminal 🐧<br>"
            "HPC Terminal & File Manager for Linux<br><br>"
            "Features:<br>"
            "• SSH terminal with tabs + Terminal Here<br>"
            "• SFTP dual-pane, drag & drop<br>"
            "• Fernet encrypted passwords<br>"
            "• Penguin idle animation + ❄ Fall<br>"
            "• Nice icon: resources/polarterm.png<br><br>"
            "Stack: PyQt6 + Paramiko<br>"
            "Config: ~/.config/polarterm/sessions.json<br>"
            "Icon by PolarTerm (Tux-style)")

    def trigger_penguin_fall(self):
        # backward compat: same icon penguin
        self.trigger_fall_with_radio("penguin")

    def trigger_fall_mode(self, mode, label=""):
        self.idle_monitor.touch()
        # if same mode and visible, toggle off
        if self.penguin_fall.isVisible() and self.penguin_fall.current_mode == mode:
            self.penguin_fall.stop()
            self.left_status.setText(f"{label} stopped")
            return
        # start with mode on same icon
        count = 22 if mode=="penguin" else 26
        self.penguin_fall.start(count=count, mode=mode)
        self.left_status.setText(f"{label or mode} falling — click overlay to stop ❄ (same PolarTerm icon)")
        QTimer.singleShot(12000, self.penguin_fall.stop)

    def trigger_fall_with_radio(self, mode="penguin"):
        self.idle_monitor.touch()
        # nice radio pulse animation on same icon
        try:
            # pulse at toolbar snow button
            if hasattr(self, 'btn_snow_tool'):
                pos = self.btn_snow_tool.mapToGlobal(self.btn_snow_tool.rect().center())
                self.radio_pulse.pulse_at(pos, self.centralWidget())
            # also pulse at welcome button if visible
            if hasattr(self, 'btn_fall_welcome') and self.btn_fall_welcome.isVisible():
                pos2 = self.btn_fall_welcome.mapToGlobal(self.btn_fall_welcome.rect().center())
                # second pulse slightly delayed
                QTimer.singleShot(180, lambda: self.radio_pulse.pulse_at(pos2, self.centralWidget()))
        except: pass
        # cycle mode if clicked same icon repeatedly without menu? keep penguin default
        label_map = {"penguin":"🐧 Penguin Snow","rose":"🌹 Rose Petals","ice":"🧊 Ice Crystals","feather":"🪶 Feather Fall","smiley":"😊 Smiley Rain","thumbs":"👍 Thumbs Up","mixed":"🎭 Mixed"}
        self.trigger_fall_mode(mode, label_map.get(mode, mode))

    def closeEvent(self, event):
        for t in self.terminal_tabs.values():
            try: t.close_shell()
            except: pass
        event.accept()
