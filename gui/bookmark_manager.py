import os
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QLabel, QInputDialog, QMessageBox, QCheckBox
from PyQt6.QtCore import Qt
from core.config import load_bookmarks, save_bookmarks, add_bookmark, delete_bookmark, Bookmark, load_sessions, save_sessions

class BookmarkManagerDialog(QDialog):
    """Small window to manage bookmarks - add, jump, delete, set auto-jump on login"""
    def __init__(self, parent=None, initial_session=""):
        super().__init__(parent)
        self.setWindowTitle("🔖 Bookmark Manager — PolarTerm")
        self.resize(520, 380)
        self.initial_session = initial_session
        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        # header
        hdr = QLabel("Bookmark folders for quick jump after login. Works for <b>remote</b> and <b>local</b> paths.")
        hdr.setWordWrap(True)
        hdr.setStyleSheet("color:#334155; font-size:11px; background:#f0f9ff; padding:8px; border:1px solid #bae6fd; border-radius:6px;")
        layout.addWidget(hdr)

        self.list = QListWidget()
        self.list.setStyleSheet("""
            QListWidget { background:white; border:1px solid #e2e8f0; border-radius:8px; }
            QListWidget::item { padding:8px; border-bottom:1px solid #f1f5f9; }
            QListWidget::item:selected { background:#fffbeb; color:#92400e; }
        """)
        self.list.doubleClicked.connect(self.jump)
        layout.addWidget(self.list, 1)

        # buttons
        btn_row = QHBoxLayout()
        btn_add = QPushButton("＋ Add Bookmark")
        btn_add.setToolTip("Add current folder (from active Files tab) or manual path")
        btn_add.setStyleSheet("background:#fffbeb; border:1px solid #fcd34d; padding:6px 10px; border-radius:6px;")
        btn_add.clicked.connect(self.add_bookmark)
        btn_add_local = QPushButton("＋ Add Local")
        btn_add_local.setToolTip("Add local host folder")
        btn_add_local.clicked.connect(lambda: self.add_bookmark(kind="local"))
        btn_edit = QPushButton("✏️ Rename")
        btn_edit.clicked.connect(self.rename_bookmark)
        btn_del = QPushButton("✕ Delete")
        btn_del.setStyleSheet("color:#dc2626;")
        btn_del.clicked.connect(self.delete_bookmark)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_add_local)
        btn_row.addWidget(btn_edit)
        btn_row.addWidget(btn_del)
        layout.addLayout(btn_row)

        # jump row
        jump_row = QHBoxLayout()
        self.chk_auto = QCheckBox("Jump to this bookmark automatically on next login (set as default)")
        self.chk_auto.setStyleSheet("font-size:11px;")
        jump_row.addWidget(self.chk_auto, 1)
        btn_jump = QPushButton("→ Jump Now")
        btn_jump.setStyleSheet("background:#0284c7; color:white; font-weight:bold; padding:8px 14px; border-radius:6px;")
        btn_jump.clicked.connect(self.jump)
        jump_row.addWidget(btn_jump)
        layout.addLayout(jump_row)

        # close
        close_row = QHBoxLayout()
        close_row.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        close_row.addWidget(btn_close)
        layout.addLayout(close_row)

        self.list.currentItemChanged.connect(self._on_select)

    def refresh(self):
        self.list.clear()
        for bm in load_bookmarks():
            icon = "📁" if bm.kind=="remote" else "💻"
            # check if is default (session's remote_path == bm.path)
            is_default = False
            if bm.session:
                for s in load_sessions():
                    if s.name == bm.session and s.remote_path == bm.path:
                        is_default = True
                        break
            star = " ⭐" if is_default else ""
            txt = f"{icon} {bm.alias} → {bm.path}{star}"
            if bm.session:
                txt += f"  ({bm.session})"
            item = QListWidgetItem(txt)
            item.setData(Qt.ItemDataRole.UserRole, (bm.alias, bm.session, bm.kind, bm.path))
            if is_default:
                item.setToolTip("⭐ Auto-jump on login for this session")
                item.setBackground(Qt.GlobalColor.yellow)
            self.list.addItem(item)
        if self.list.count()==0:
            self.list.addItem("No bookmarks yet. Click ＋ Add Bookmark to save current folder.")

    def _on_select(self, cur, prev):
        if cur and cur.data(Qt.ItemDataRole.UserRole):
            alias, session, kind, path = cur.data(Qt.ItemDataRole.UserRole)
            # check if this bookmark is default for its session
            is_def = False
            for s in load_sessions():
                if s.name == session and s.remote_path == path:
                    is_def = True
                    break
            self.chk_auto.setChecked(is_def)

    def add_bookmark(self, kind="remote"):
        # try to get current path from parent MainWindow if available
        cur_path = None
        session_name = self.initial_session
        # try to get from parent
        parent = self.parent()
        if parent and hasattr(parent, 'tabs'):
            # find active FileTransferWidget
            from gui.file_transfer_widget import FileTransferWidget
            cur = parent.tabs.currentWidget()
            if isinstance(cur, FileTransferWidget):
                if kind == "remote" and cur.ssh and cur.ssh.connected:
                    cur_path = cur.remote_browser.current_path
                    for name, ssh in parent.ssh_sessions.items():
                        if ssh == cur.ssh:
                            session_name = name
                            break
                elif kind == "local":
                    cur_path = cur.local_browser.current_path
                    # for local, session not needed, but keep
                    for name, ssh in parent.ssh_sessions.items():
                        if ssh == cur.ssh:
                            session_name = name
                            break
            else:
                # try any connected
                for name, ft in getattr(parent, 'transfer_tabs', {}).items():
                    if ft.ssh and ft.ssh.connected:
                        cur_path = ft.remote_browser.current_path if kind=="remote" else ft.local_browser.current_path
                        session_name = name
                        break
        if not cur_path:
            # ask manual
            from PyQt6.QtWidgets import QInputDialog
            cur_path, ok = QInputDialog.getText(self, "Bookmark Path", f"Enter {kind} folder path to bookmark:")
            if not ok or not cur_path.strip():
                return
            cur_path = cur_path.strip()
        alias, ok = QInputDialog.getText(self, "Bookmark Alias", f"Alias for {cur_path}:", text=os.path.basename(cur_path.rstrip("/")) or cur_path)
        if not ok or not alias.strip():
            return
        alias = alias.strip()
        bm = Bookmark(alias=alias, path=cur_path, session=session_name, kind=kind)
        add_bookmark(bm)
        # handle auto-jump checkbox
        if self.chk_auto.isChecked() and session_name:
            for s in load_sessions():
                if s.name == session_name:
                    s.remote_path = cur_path
                    from core.config import add_or_update_session
                    add_or_update_session(s)
                    break
        self.refresh()
        # select new item
        for i in range(self.list.count()):
            item = self.list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and data[0]==alias and data[1]==session_name:
                self.list.setCurrentRow(i)
                break

    def rename_bookmark(self):
        item = self.list.currentItem()
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            return
        alias, session, kind, path = item.data(Qt.ItemDataRole.UserRole)
        new_alias, ok = QInputDialog.getText(self, "Rename Bookmark", "New alias:", text=alias)
        if not ok or not new_alias.strip() or new_alias.strip()==alias:
            return
        new_alias = new_alias.strip()
        # delete old, add new
        delete_bookmark(alias, session)
        bm = Bookmark(alias=new_alias, path=path, session=session, kind=kind)
        add_bookmark(bm)
        self.refresh()

    def delete_bookmark(self):
        item = self.list.currentItem()
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            return
        alias, session, kind, path = item.data(Qt.ItemDataRole.UserRole)
        if QMessageBox.question(self, "Delete Bookmark", f"Delete bookmark '{alias}'?\n{path}")==QMessageBox.StandardButton.Yes:
            delete_bookmark(alias, session)
            self.refresh()

    def jump(self):
        item = self.list.currentItem()
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            QMessageBox.information(self, "Select", "Select a bookmark to jump.")
            return
        alias, session, kind, path = item.data(Qt.ItemDataRole.UserRole)
        parent = self.parent()
        if not parent or not hasattr(parent, 'transfer_tabs'):
            QMessageBox.information(self, "Jump", f"Bookmark: {alias}\n{path}\n\nConnect to {session} then Jump.")
            return
        # find FileTransferWidget
        target_ft = None
        if session and session in parent.transfer_tabs:
            target_ft = parent.transfer_tabs[session]
        else:
            # try active
            from gui.file_transfer_widget import FileTransferWidget
            cur = parent.tabs.currentWidget()
            if isinstance(cur, FileTransferWidget):
                target_ft = cur
            elif parent.transfer_tabs:
                target_ft = list(parent.transfer_tabs.values())[0]
        if target_ft:
            if kind == "remote":
                target_ft.remote_browser.current_path = path
                target_ft.remote_browser.path_edit.setText(path)
                target_ft.remote_browser.refresh()
            else:
                target_ft.local_browser.current_path = path
                target_ft.local_browser.path_edit.setText(path)
                target_ft.local_browser.refresh()
            # bring tab to front
            for i in range(parent.tabs.count()):
                if parent.tabs.widget(i)==target_ft:
                    parent.tabs.setCurrentIndex(i)
                    break
            QMessageBox.information(self, "Jumped", f"Jumped to {alias}:\n{path}")
            self.accept()
        else:
            # not connected - offer to set as default for next login
            if session:
                for s in load_sessions():
                    if s.name == session:
                        s.remote_path = path
                        from core.config import add_or_update_session
                        add_or_update_session(s)
                        QMessageBox.information(self, "Bookmark", f"Will jump to {path} on next connect to {session}")
                        self.accept()
                        break
            else:
                QMessageBox.information(self, "Bookmark", f"Bookmark path: {path}\nConnect to a session first to jump.")
