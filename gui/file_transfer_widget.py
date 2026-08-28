import os, pathlib, stat, hashlib, subprocess, tempfile
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QSplitter, QTableWidget, QTableWidgetItem,
                             QPushButton, QLineEdit, QLabel, QHeaderView, QFileDialog, QProgressBar,
                             QToolBar, QMessageBox, QMenu, QDialog)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer, QFileSystemWatcher, QMimeData, QUrl
from PyQt6.QtGui import QAction, QIcon, QDrag, QShortcut, QKeySequence
import stat as statmod
import shutil
# global clipboard for cut/copy/paste across local/remote
CLIPBOARD = {"op": None, "paths": [], "src_mode": None, "src_ssh": None}

def _unique_local_path(dst):
    if not os.path.exists(dst):
        return dst
    base, ext = os.path.splitext(dst)
    # handle "(copy)" already in base
    for i in range(1, 200):
        if i == 1:
            cand = f"{base} (copy){ext}"
        else:
            cand = f"{base} (copy {i}){ext}"
        if not os.path.exists(cand):
            return cand
    return dst

def _unique_remote_path(ssh, dst):
    # check via sftp_stat, generate unique
    try:
        ssh.sftp_stat(dst)
    except:
        return dst  # not exists
    # exists, generate
    # split name and ext
    # dst is like /path/file.txt
    dirpart = os.path.dirname(dst)
    name = os.path.basename(dst)
    base, ext = os.path.splitext(name)
    for i in range(1, 200):
        cand_name = f"{base} (copy){ext}" if i==1 else f"{base} (copy {i}){ext}"
        cand = dirpart + "/" + cand_name
        try:
            ssh.sftp_stat(cand)
        except:
            return cand
    return dst

# --- SFTP worker (same but supports multiple files for drag-drop) ---
class SFTPWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished_signal = pyqtSignal(bool, str)
    def __init__(self, ssh_wrapper, direction, local_path, remote_path):
        super().__init__()
        self.ssh = ssh_wrapper
        self.direction = direction
        self.local_path = local_path
        self.remote_path = remote_path

    def run(self):
        try:
            if self.direction == "up":
                if os.path.isdir(self.local_path):
                    self.finished_signal.emit(False, "Directory upload not supported yet (zip first)")
                    return
                try:
                    attr = self.ssh.sftp_stat(self.remote_path)
                    if statmod.S_ISDIR(attr.st_mode):
                        remote = os.path.join(self.remote_path, os.path.basename(self.local_path))
                    else:
                        remote = self.remote_path
                except:
                    remote = self.remote_path
                remote = remote.replace("\\", "/")
                def cb(x, y):
                    self.progress.emit(x, y, os.path.basename(self.local_path))
                self.ssh.sftp_put(self.local_path, remote, callback=cb)
            else:
                local = self.local_path
                if os.path.isdir(local):
                    local = os.path.join(local, os.path.basename(self.remote_path))
                def cb(x, y):
                    self.progress.emit(x, y, os.path.basename(self.remote_path))
                self.ssh.sftp_get(self.remote_path, local, callback=cb)
            self.finished_signal.emit(True, "Transfer complete")
        except Exception as e:
            import traceback; traceback.print_exc()
            self.finished_signal.emit(False, str(e))

# --- DragDrop table ---
class DragDropTable(QTableWidget):
    files_dropped = pyqtSignal(list)  # list of local file paths
    remote_drop_requested = pyqtSignal(list)  # for remote table? not used
    drag_started = pyqtSignal(list)  # internal drag start with selected names

    def __init__(self, parent_browser=None):
        super().__init__(parent=parent_browser)
        self.browser = parent_browser
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setDragDropMode(QTableWidget.DragDropMode.DragDrop)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

    def mimeTypes(self):
        return ["text/uri-list", "text/plain"]

    def mimeData(self, items):
        # items are selected indexes - build uri-list for local or remote
        mime = QMimeData()
        urls = []
        # Determine selected rows
        rows = set()
        for idx in self.selectedIndexes():
            rows.add(idx.row())
        paths = []
        for row in rows:
            item = self.item(row, 0)
            if not item:
                continue
            name = item.data(Qt.ItemDataRole.UserRole)
            if self.browser.mode == "local":
                paths.append(os.path.join(self.browser.current_path, name))
            else:
                paths.append(self.browser.current_path.rstrip("/") + "/" + name)
        if self.browser.mode == "local":
            # local files -> file:// urls
            for p in paths:
                urls.append(QUrl.fromLocalFile(p))
            mime.setUrls(urls)
            mime.setText("\n".join(paths))
        else:
            # remote files -> text with remote paths (custom)
            mime.setText("\n".join(paths))
            # also set dummy urls so drop target accepts
            mime.setData("application/x-polarterm-remote", "\n".join(paths).encode())
        return mime

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText() or (event.mimeData().hasFormat("application/x-polarterm-remote") or event.mimeData().hasFormat("application/x-mobaxtreme-remote")):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText() or (event.mimeData().hasFormat("application/x-polarterm-remote") or event.mimeData().hasFormat("application/x-mobaxtreme-remote")):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        mime = event.mimeData()
        # External files (from file manager) -> list of local paths
        if mime.hasUrls():
            paths = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
            # If dropped on remote table and we are remote, upload
            # If dropped on local table and we are local, maybe copy? just indicate
            if self.browser.mode == "remote":
                # emit to parent FileTransferWidget via browser signal
                self.browser.external_drop.emit(paths)
                event.acceptProposedAction()
                return
            elif self.browser.mode == "local":
                # dropped external onto local -> already local, maybe just refresh?
                # For now, if remote drag with custom mime, download
                pass
        # Remote to local drag (custom mime)
        if (mime.hasFormat("application/x-polarterm-remote") or mime.hasFormat("application/x-mobaxtreme-remote")):
            # this is remote files being dropped onto local browser
            if self.browser.mode == "local":
                remote_paths = (bytes(mime.data("application/x-polarterm-remote")).decode() if mime.hasFormat("application/x-polarterm-remote") else bytes(mime.data("application/x-mobaxtreme-remote")).decode()).splitlines()
                remote_paths = [r for r in remote_paths if r]
                self.browser.remote_files_dropped.emit(remote_paths)
                event.acceptProposedAction()
                return
        # Local to remote drag (urls on remote)
        if mime.hasUrls() and self.browser.mode == "remote":
            paths = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
            if paths:
                self.browser.external_drop.emit(paths)
                event.acceptProposedAction()
                return
        # fallback: text plain (maybe remote paths)
        if mime.hasText() and self.browser.mode == "local" and (mime.hasFormat("application/x-polarterm-remote") or mime.hasFormat("application/x-mobaxtreme-remote")):
            # already handled
            pass
        event.ignore()


class FileBrowserWidget(QWidget):
    navigate = pyqtSignal(str)
    transfer_requested = pyqtSignal(str, str)
    external_drop = pyqtSignal(list)  # list of local paths dropped onto remote
    remote_files_dropped = pyqtSignal(list)  # list of remote paths dropped onto local
    open_terminal_here = pyqtSignal(str)  # path (current or selected folder)
    bookmark_requested = pyqtSignal(str)  # path to bookmark

    def __init__(self, mode="local", ssh_wrapper=None):
        super().__init__()
        self.mode = mode
        self.ssh = ssh_wrapper
        self.current_path = os.path.expanduser("~") if mode=="local" else "~"
        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4,4,4,4)
        path_layout = QHBoxLayout()
        self.path_edit = QLineEdit(self.current_path)
        self.path_edit.returnPressed.connect(self._on_path_enter)
        self.btn_up = QPushButton("↑ Up")
        self.btn_up.setFixedWidth(50)
        self.btn_up.clicked.connect(self.go_up)
        self.btn_refresh = QPushButton("⟳")
        self.btn_refresh.setFixedWidth(30)
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_hidden = QPushButton("👁")
        self.btn_hidden.setCheckable(True)
        self.btn_hidden.setToolTip("Show hidden files")
        self.btn_hidden.setFixedWidth(30)
        self.btn_hidden.toggled.connect(lambda _: self.refresh())
        path_layout.addWidget(QLabel("Path:"))
        path_layout.addWidget(self.path_edit, 1)
        path_layout.addWidget(self.btn_up)
        path_layout.addWidget(self.btn_refresh)
        path_layout.addWidget(self.btn_hidden)
        self.btn_term_here = QPushButton("🖥 Terminal Here")
        self.btn_term_here.setToolTip("Open terminal in this folder")
        self.btn_term_here.setFixedWidth(110)
        self.btn_term_here.setStyleSheet("background:#ff9800; color:white; font-weight:bold; padding:4px; border-radius:4px;")
        self.btn_term_here.clicked.connect(lambda: self.open_terminal_here.emit(self.current_path))
        path_layout.addWidget(self.btn_term_here)
        layout.addLayout(path_layout)

        # table with drag-drop
        self.table = DragDropTable(parent_browser=self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Name", "Size", "Type", "Modified"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(2, 70)
        self.table.setColumnWidth(3, 140)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        # shortcuts for cut/copy/paste - keep refs to avoid GC
        self._sc_copy = QShortcut(QKeySequence("Ctrl+C"), self.table)
        self._sc_copy.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._sc_copy.activated.connect(lambda: self._on_copy())
        self._sc_cut = QShortcut(QKeySequence("Ctrl+X"), self.table)
        self._sc_cut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._sc_cut.activated.connect(lambda: self._on_cut())
        self._sc_paste = QShortcut(QKeySequence("Ctrl+V"), self.table)
        self._sc_paste.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._sc_paste.activated.connect(lambda: self._on_paste())
        # also allow Ctrl+D for duplicate in place (copy-paste same folder)
        self._sc_dup = QShortcut(QKeySequence("Ctrl+D"), self.table)
        self._sc_dup.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._sc_dup.activated.connect(lambda: self._on_duplicate())
        # Delete key (Del)
        self._sc_del = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.table)
        self._sc_del.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._sc_del.activated.connect(lambda: self._on_delete())
        layout.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        if self.mode == "local":
            self.btn_open_local = QPushButton("📂 Open")
            self.btn_open_local.setToolTip("Open host folder")
            self.btn_open_local.clicked.connect(self._on_open_folder)
            bottom.addWidget(self.btn_open_local)
            self.btn_new_local = QPushButton("📁+ New Folder")
            self.btn_new_local.setToolTip("Create new folder in host (local)")
            self.btn_new_local.setStyleSheet("background:#e0f2fe; border:1px solid #7dd3fc; padding:4px 8px; border-radius:6px;")
            self.btn_new_local.clicked.connect(self._on_new_folder)
            bottom.addWidget(self.btn_new_local)
        else:
            self.btn_open_local = QPushButton("📁+ New Folder")
            self.btn_open_local.setToolTip("Create new remote folder")
            self.btn_open_local.setStyleSheet("background:#e0f2fe; border:1px solid #7dd3fc; padding:4px 8px; border-radius:6px;")
            self.btn_open_local.clicked.connect(self._on_new_folder)
            bottom.addWidget(self.btn_open_local)
        bottom.addStretch()
        self.info_label = QLabel("")
        self.info_label.setStyleSheet("color: #666; font-size: 10px;")
        bottom.addWidget(self.info_label)
        layout.addLayout(bottom)

        # placeholder for drop hint
        self.table.setToolTip("Drag & drop supported: drag files from OS file manager or between panes")

    def set_ssh(self, ssh):
        self.ssh = ssh
        if self.mode=="remote" and ssh:
            try:
                self.current_path = ssh.sftp_normalize("~")
            except:
                try:
                    self.current_path = ssh.get_home()
                except:
                    self.current_path = "."
            self.path_edit.setText(self.current_path)
            self.refresh()

    def _on_path_enter(self):
        self.current_path = self.path_edit.text().strip()
        self.refresh()

    def go_up(self):
        if self.mode=="local":
            self.current_path = os.path.dirname(self.current_path.rstrip("/")) or "/"
        else:
            p = self.current_path.rstrip("/")
            if "/" in p:
                self.current_path = p.rsplit("/",1)[0] or "/"
            else:
                self.current_path = "/"
            if self.ssh:
                try:
                    self.current_path = self.ssh.sftp_normalize(self.current_path)
                except: pass
        self.path_edit.setText(self.current_path)
        self.refresh()

    def _on_open_folder(self):
        # Only for local: open directory chooser
        d = QFileDialog.getExistingDirectory(self, "Select Folder", self.current_path)
        if d:
            self.current_path = d
            self.path_edit.setText(d)
            self.refresh()

    def _on_new_folder(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Folder", f"Folder name in {'host' if self.mode=='local' else 'remote'} {self.current_path}:")
        if not ok or not name:
            return
        # sanitize name
        name = name.strip().replace("/", "_").replace("\\", "_")
        if not name:
            return
        try:
            if self.mode == "local":
                new_path = os.path.join(self.current_path, name)
                os.makedirs(new_path, exist_ok=False)
                self.refresh()
                self.info_label.setText(f"Created folder: {new_path}")
            else:
                if not self.ssh or not self.ssh.connected:
                    QMessageBox.warning(self, "Not connected", "Connect to remote first.")
                    return
                new_path = self.current_path.rstrip("/") + "/" + name
                self.ssh.sftp_mkdir(new_path)
                self.refresh()
                self.info_label.setText(f"Created remote folder: {new_path}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to create folder:\n{e}")

    # --- Cut / Copy / Paste ---
    def _on_copy(self, paths=None):
        if paths is None:
            paths = self.selected_paths()
            if not paths:
                # if empty area, copy current folder? no
                return
        CLIPBOARD["op"] = "copy"
        CLIPBOARD["paths"] = list(paths)
        CLIPBOARD["src_mode"] = self.mode
        CLIPBOARD["src_ssh"] = self.ssh if self.mode=="remote" else None
        self.info_label.setText(f"Copied {len(paths)} item(s) — use Paste (Ctrl+V) in target folder")
        self.info_label.setStyleSheet("color:#0284c7; font-size:10px;")

    def _on_cut(self, paths=None):
        if paths is None:
            paths = self.selected_paths()
            if not paths:
                return
        CLIPBOARD["op"] = "cut"
        CLIPBOARD["paths"] = list(paths)
        CLIPBOARD["src_mode"] = self.mode
        CLIPBOARD["src_ssh"] = self.ssh if self.mode=="remote" else None
        self.info_label.setText(f"Cut {len(paths)} item(s) — use Paste (Ctrl+V) in target folder")
        self.info_label.setStyleSheet("color:#ea580c; font-size:10px;")

    def _on_duplicate(self):
        # Ctrl+D: duplicate selected in place (copy-paste same folder)
        paths = self.selected_paths()
        if not paths:
            return
        self._on_copy(paths)
        # temporarily ensure duplicate handling will make copy even if same folder
        self._on_paste()

    def _on_delete(self):
        paths = self.selected_paths()
        if not paths:
            return
        # confirm
        if len(paths) == 1:
            name = os.path.basename(paths[0].rstrip("/"))
            msg = f"Delete {name}?"
        else:
            msg = f"Delete {len(paths)} selected items?"
        if QMessageBox.question(self, "Delete", msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        for full in paths:
            try:
                if self.mode == "local":
                    if os.path.isdir(full):
                        shutil.rmtree(full)
                    else:
                        os.remove(full)
                else:
                    if not self.ssh or not self.ssh.connected:
                        QMessageBox.warning(self, "Not connected", "Connect first")
                        return
                    try:
                        attr = self.ssh.sftp_stat(full)
                        if statmod.S_ISDIR(attr.st_mode):
                            # try rmdir, if not empty, need to handle? use exec rm -rf?
                            try:
                                self.ssh.sftp_rmdir(full)
                            except:
                                # try rm -rf via ssh
                                self.ssh.exec_command(f"rm -rf '{full}'", timeout=5)
                        else:
                            self.ssh.sftp_remove(full)
                    except Exception as e:
                        # try fallback rm
                        try:
                            self.ssh.exec_command(f"rm -rf '{full}'", timeout=5)
                        except:
                            raise e
            except Exception as e:
                QMessageBox.warning(self, "Delete failed", f"{full}\n{e}")
        self.refresh()
        # also refresh parent if needed
        try:
            parent = self.parent()
            while parent and not isinstance(parent, FileTransferWidget):
                parent = parent.parent()
            if parent:
                parent.local_browser.refresh()
                parent.remote_browser.refresh()
        except: pass

    def _on_paste(self):
        if not CLIPBOARD["op"] or not CLIPBOARD["paths"]:
            self.info_label.setText("Clipboard empty — copy/cut first")
            return
        op = CLIPBOARD["op"]
        src_mode = CLIPBOARD["src_mode"]
        dst_mode = self.mode
        dst_dir = self.current_path
        # need to handle each path
        for src in list(CLIPBOARD["paths"]):
            name = os.path.basename(src.rstrip("/"))
            dst = os.path.join(dst_dir, name) if dst_mode=="local" else dst_dir.rstrip("/") + "/" + name
            # duplicate handling: if copy and dst exists or is same file, make unique
            if op == "copy":
                if dst_mode == "local":
                    # same file check (normpath)
                    if os.path.abspath(src) == os.path.abspath(dst) if src_mode=="local" else False:
                        dst = _unique_local_path(dst)
                    elif os.path.exists(dst):
                        dst = _unique_local_path(dst)
                else: # remote dst
                    # need ssh to check
                    dst_ssh = self.ssh if dst_mode=="remote" else CLIPBOARD["src_ssh"]
                    if dst_ssh and dst_ssh.connected:
                        # same path check for remote->remote copy in same folder
                        if src_mode=="remote" and src == dst:
                            dst = _unique_remote_path(dst_ssh, dst)
                        else:
                            try:
                                dst_ssh.sftp_stat(dst)
                                dst = _unique_remote_path(dst_ssh, dst)
                            except:
                                pass
                    else:
                        # for local->remote, check dst exists
                        if self.ssh and self.ssh.connected:
                            try:
                                self.ssh.sftp_stat(dst)
                                dst = _unique_remote_path(self.ssh, dst)
                            except:
                                pass

            try:
                if src_mode=="local" and dst_mode=="local":
                    # local -> local
                    if op=="copy":
                        if os.path.isdir(src):
                            shutil.copytree(src, dst)
                        else:
                            shutil.copy2(src, dst)
                    else: # cut = move
                        shutil.move(src, dst)
                elif src_mode=="remote" and dst_mode=="remote":
                    # remote -> remote on same host (if same ssh)
                    # use sftp rename for cut, and copy via temp for copy
                    if CLIPBOARD["src_ssh"] == self.ssh or CLIPBOARD["src_ssh"] is None:
                        if op=="cut":
                            self.ssh.sftp_rename(src, dst)
                        else:
                            # copy: download to temp then upload
                            import tempfile
                            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                                tmp_path = tmp.name
                            try:
                                self.ssh.sftp_get(src, tmp_path)
                                self.ssh.sftp_put(tmp_path, dst)
                            finally:
                                try: os.unlink(tmp_path)
                                except: pass
                    else:
                        # different hosts - need cross-host via local temp
                        import tempfile
                        with tempfile.NamedTemporaryFile(delete=False) as tmp:
                            tmp_path = tmp.name
                        try:
                            CLIPBOARD["src_ssh"].sftp_get(src, tmp_path)
                            self.ssh.sftp_put(tmp_path, dst)
                            if op=="cut":
                                # delete source via its ssh
                                try:
                                    attr = CLIPBOARD["src_ssh"].sftp_stat(src)
                                    if statmod.S_ISDIR(attr.st_mode):
                                        CLIPBOARD["src_ssh"].sftp_rmdir(src)
                                    else:
                                        CLIPBOARD["src_ssh"].sftp_remove(src)
                                except: pass
                        finally:
                            try: os.unlink(tmp_path)
                            except: pass
                elif src_mode=="local" and dst_mode=="remote":
                    # upload
                    if not self.ssh or not self.ssh.connected:
                        QMessageBox.warning(self, "Not connected", "Connect remote first")
                        return
                    if os.path.isdir(src):
                        QMessageBox.information(self, "Folder", f"Folder paste not yet recursive: {src}")
                        continue
                    self.ssh.sftp_put(src, dst)
                    if op=="cut":
                        # delete local source
                        try:
                            if os.path.isdir(src):
                                shutil.rmtree(src)
                            else:
                                os.remove(src)
                        except: pass
                elif src_mode=="remote" and dst_mode=="local":
                    # download
                    if not CLIPBOARD["src_ssh"] or not CLIPBOARD["src_ssh"].connected:
                        QMessageBox.warning(self, "Not connected", "Source no longer connected")
                        return
                    # dst is local path
                    try:
                        CLIPBOARD["src_ssh"].sftp_get(src, dst)
                        if op=="cut":
                            try:
                                CLIPBOARD["src_ssh"].sftp_remove(src)
                            except: pass
                    except Exception as e:
                        QMessageBox.warning(self, "Paste failed", str(e))
                        continue
            except Exception as e:
                QMessageBox.warning(self, "Paste failed", f"{src} → {dst}\n{e}")
                continue
        self.refresh()
        # if cut, clear clipboard after successful paste
        if op=="cut":
            CLIPBOARD["op"] = None
            CLIPBOARD["paths"] = []
            CLIPBOARD["src_mode"] = None
            CLIPBOARD["src_ssh"] = None
            self.info_label.setText("Moved — clipboard cleared")
        else:
            self.info_label.setText(f"Pasted {len(CLIPBOARD['paths'])} item(s)")
        # also refresh source if needed? For same-mode cut we already moved, but for cross we handled
        # try to refresh source browser via parent FileTransferWidget if exists
        try:
            # find other browser to refresh if needed
            parent = self.parent()
            while parent and not isinstance(parent, FileTransferWidget):
                parent = parent.parent()
            if parent:
                parent.local_browser.refresh()
                parent.remote_browser.refresh()
        except: pass

    def refresh(self):
        self.table.setRowCount(0)
        try:
            entries = []
            show_hidden = self.btn_hidden.isChecked()
            if self.mode=="local":
                p = os.path.expanduser(self.current_path)
                if not os.path.exists(p):
                    self.info_label.setText("Path not found")
                    self.info_label.setStyleSheet("color:#d32f2f; font-size:10px;")
                    return
                self.current_path = p
                self.path_edit.setText(p)
                for name in os.listdir(p):
                    if not show_hidden and name.startswith("."):
                        continue
                    full = os.path.join(p, name)
                    try:
                        st = os.stat(full)
                        is_dir = os.path.isdir(full)
                        entries.append((name, st.st_size, is_dir, st.st_mtime))
                    except: pass
                entries.sort(key=lambda x: (not x[2], x[0].lower()))
            else:
                if not self.ssh or not self.ssh.connected or not self.ssh.sftp:
                    self.info_label.setText("Not connected - connect session first")
                    self.info_label.setStyleSheet("color:#d32f2f; font-size:10px;")
                    return
                try:
                    norm = self.ssh.sftp_normalize(self.current_path)
                    self.current_path = norm
                    self.path_edit.setText(norm)
                    attrs = self.ssh.sftp_listdir(norm)
                    for a in attrs:
                        if not show_hidden and a.filename.startswith("."):
                            continue
                        is_dir = statmod.S_ISDIR(a.st_mode)
                        # also handle symlinks? show as file/dir via lstat?
                        entries.append((a.filename, a.st_size, is_dir, a.st_mtime))
                    entries.sort(key=lambda x: (not x[2], x[0].lower()))
                except Exception as e:
                    self.info_label.setText(f"Error: {e}")
                    self.info_label.setStyleSheet("color:#d32f2f; font-size:10px;")
                    # debug log
                    print(f"[remote refresh] {e}")
                    # fallback via exec ls
                    try:
                        stdin, stdout, stderr = self.ssh.exec_command(f"ls -la '{self.current_path}'", timeout=5)
                        out = stdout.read().decode()
                        err = stderr.read().decode()
                        if out:
                            self.info_label.setText(f"SFTP error, ls fallback: {out[:80]}")
                    except: pass
                    return
            self.table.setRowCount(len(entries))
            import datetime
            for i, (name, size, is_dir, mtime) in enumerate(entries):
                icon = "📁 " if is_dir else "📄 "
                item0 = QTableWidgetItem(icon + name)
                item0.setData(Qt.ItemDataRole.UserRole, name)
                if is_dir:
                    size_str = "<DIR>"
                else:
                    if size < 1024: size_str = f"{size} B"
                    elif size < 1024*1024: size_str = f"{size/1024:.1f} KB"
                    elif size < 1024*1024*1024: size_str = f"{size/1024/1024:.1f} MB"
                    else: size_str = f"{size/1024/1024/1024:.2f} GB"
                item1 = QTableWidgetItem(size_str)
                item2 = QTableWidgetItem("Folder" if is_dir else "File")
                try:
                    dt = datetime.datetime.fromtimestamp(mtime)
                    item3 = QTableWidgetItem(dt.strftime("%Y-%m-%d %H:%M"))
                except:
                    item3 = QTableWidgetItem("-")
                item1.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                for it in [item0,item1,item2,item3]:
                    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    # enable drag
                    it.setFlags(it.flags() | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled)
                self.table.setItem(i,0,item0)
                self.table.setItem(i,1,item1)
                self.table.setItem(i,2,item2)
                self.table.setItem(i,3,item3)
            self.info_label.setStyleSheet("color:#4caf50; font-size:10px;" if entries else "color:#888; font-size:10px;")
            self.info_label.setText(f"{len(entries)} items  |  {self.current_path}  |  drag & drop enabled")
        except Exception as e:
            self.info_label.setText(f"Error: {e}")
            self.info_label.setStyleSheet("color:#d32f2f; font-size:10px;")

    def _on_double_click(self, idx):
        row = idx.row()
        item = self.table.item(row, 0)
        name = item.data(Qt.ItemDataRole.UserRole)
        if self.mode=="local":
            full = os.path.join(self.current_path, name)
            if os.path.isdir(full):
                self.current_path = full
                self.path_edit.setText(full)
                self.refresh()
            else:
                # open locally?
                try:
                    subprocess.Popen(["xdg-open", full], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except: pass
                self.info_label.setText(f"Opened: {full}")
        else:
            new_path = self.current_path.rstrip("/") + "/" + name
            try:
                attr = self.ssh.sftp_stat(new_path)
                if statmod.S_ISDIR(attr.st_mode):
                    self.current_path = new_path
                    self.path_edit.setText(new_path)
                    self.refresh()
                else:
                    # Ask to edit locally
                    self._prompt_edit_remote(new_path)
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))

    def _prompt_edit_remote(self, remote_path):
        # Offer to download & edit
        m = QMessageBox(self)
        m.setWindowTitle("Open remote file")
        m.setText(f"Open {os.path.basename(remote_path)} locally?\n\nIt will download to temp, open with default app, and auto-upload on save.")
        m.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        m.setDefaultButton(QMessageBox.StandardButton.Yes)
        # extra button for download only
        btn_download = m.addButton("Download only", QMessageBox.ButtonRole.ActionRole)
        if m.exec() == QMessageBox.StandardButton.Yes:
            # trigger edit
            self.transfer_requested.emit(remote_path, "edit")
        elif m.clickedButton() == btn_download:
            self.transfer_requested.emit(remote_path, "download")

    def _on_context_menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            # empty area -> offer actions for current folder
            menu = QMenu(self)
            act_term_cur = menu.addAction("🖥 Terminal Here (current folder)")
            act_refresh = menu.addAction("⟳ Refresh")
            act_bookmark = menu.addAction("🔖 Bookmark This Folder")
            # Paste with shortcut hint
            act_paste = menu.addAction("📋 Paste  (Ctrl+V)")
            act_paste.setEnabled(bool(CLIPBOARD["op"] and CLIPBOARD["paths"]))
            if self.mode == "local":
                act_new_folder = menu.addAction("📁+ New Folder (host)")
                act_open_folder = menu.addAction("📂 Open Folder...")
            else:
                act_new_folder = menu.addAction("📁+ New Folder (remote)")
                act_open_folder = None
            act = menu.exec(self.table.viewport().mapToGlobal(pos))
            if act == act_term_cur:
                self.open_terminal_here.emit(self.current_path)
            elif act == act_refresh:
                self.refresh()
            elif act == act_bookmark:
                self.bookmark_requested.emit(self.current_path)
            elif act == act_paste:
                self._on_paste()
            elif act == act_new_folder:
                self._on_new_folder()
            elif act_open_folder and act == act_open_folder:
                self._on_open_folder()
            return
        row = idx.row()
        name = self.table.item(row,0).data(Qt.ItemDataRole.UserRole)
        full = (os.path.join(self.current_path, name) if self.mode=="local" else self.current_path.rstrip("/")+"/"+name)
        is_dir = False
        try:
            if self.mode=="local":
                is_dir = os.path.isdir(full)
            else:
                attr = self.ssh.sftp_stat(full)
                is_dir = statmod.S_ISDIR(attr.st_mode)
        except: pass
        menu = QMenu(self)
        # Cut / Copy / Paste - like host file manager
        act_cut = menu.addAction("✂️ Cut  (Ctrl+X)")
        act_copy = menu.addAction("📋 Copy  (Ctrl+C)")
        act_paste = menu.addAction("📋 Paste  (Ctrl+V)")
        act_paste.setEnabled(bool(CLIPBOARD["op"] and CLIPBOARD["paths"]))
        menu.addSeparator()
        # Terminal Here always for folders, and for current folder
        if is_dir:
            act_term_here = menu.addAction("🖥 Open Terminal Here")
        else:
            act_term_here = None
        # Bookmark for folders and current
        act_bookmark = menu.addAction("🔖 Bookmark This Folder" if is_dir else "🔖 Bookmark Current Folder")
        # Also add Terminal Here for current folder via empty-area menu - handled elsewhere
        if self.mode=="remote" and not is_dir:
            act_edit = menu.addAction("✏️ Edit Locally (auto-upload)")
            act_edit.setToolTip("Download, open with local app, watch for changes")
        act_open = menu.addAction("Open")
        act_delete = menu.addAction("Delete")
        act_rename = menu.addAction("Rename")
        act_transfer = menu.addAction("Upload" if self.mode=="local" else "Download")
        if self.mode=="remote" and not is_dir:
            act_open_local = menu.addAction("Open With...")
        else:
            act_open_local = None
        # Always offer Terminal Here for current directory even on file? add
        act_term_cur = menu.addAction("🖥 Terminal Here (current folder)")
        act = menu.exec(self.table.viewport().mapToGlobal(pos))
        if not act:
            return
        if act == act_bookmark:
            # bookmark folder if is_dir else current
            bm_path = full if is_dir else self.current_path
            self.bookmark_requested.emit(bm_path)
            return
        if act == act_cut:
            # include clicked item if not selected
            paths = self.selected_paths()
            if full not in paths:
                paths = [full] + paths if paths else [full]
            self._on_cut(paths)
            return
        if act == act_copy:
            paths = self.selected_paths()
            if full not in paths:
                paths = [full] + paths if paths else [full]
            self._on_copy(paths)
            return
        if act == act_paste:
            self._on_paste()
            return
        if act_term_here and act == act_term_here:
            self.open_terminal_here.emit(full)
            return
        if act == act_term_cur:
            self.open_terminal_here.emit(self.current_path)
            return
        if self.mode=="remote" and not is_dir and act.text().startswith("✏️"):
            self.transfer_requested.emit(full, "edit")
        elif act == act_delete:
            if QMessageBox.question(self, "Delete", f"Delete {name}?") == QMessageBox.StandardButton.Yes:
                try:
                    if self.mode=="local":
                        import shutil
                        if os.path.isdir(full):
                            shutil.rmtree(full)
                        else:
                            os.remove(full)
                    else:
                        attr = self.ssh.sftp_stat(full)
                        if statmod.S_ISDIR(attr.st_mode):
                            self.ssh.sftp_rmdir(full)
                        else:
                            self.ssh.sftp_remove(full)
                    self.refresh()
                except Exception as e:
                    QMessageBox.warning(self, "Error", str(e))
        elif act == act_rename:
            from PyQt6.QtWidgets import QInputDialog
            new, ok = QInputDialog.getText(self, "Rename", "New name:", text=name)
            if ok and new:
                try:
                    if self.mode=="local":
                        os.rename(full, os.path.join(self.current_path, new))
                    else:
                        self.ssh.sftp_rename(full, self.current_path.rstrip("/")+"/"+new)
                    self.refresh()
                except Exception as e:
                    QMessageBox.warning(self, "Error", str(e))
        elif act == act_transfer:
            self.transfer_requested.emit(full, self.mode)
        elif act_open_local and act == act_open_local:
            # choose app
            self.transfer_requested.emit(full, "edit_with")
        elif act == act_open:
            # open action - for remote file, edit; for local, open
            if self.mode=="local":
                try:
                    subprocess.Popen(["xdg-open", full])
                except Exception as e:
                    QMessageBox.warning(self, "Error", str(e))
            else:
                if is_dir:
                    self.current_path = full
                    self.path_edit.setText(full)
                    self.refresh()
                else:
                    self.transfer_requested.emit(full, "edit")

    def selected_path(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        name = self.table.item(row,0).data(Qt.ItemDataRole.UserRole)
        return (os.path.join(self.current_path, name) if self.mode=="local" else self.current_path.rstrip("/")+"/"+name)

    def selected_paths(self):
        rows = self.table.selectionModel().selectedRows()
        out = []
        for r in rows:
            name = self.table.item(r.row(),0).data(Qt.ItemDataRole.UserRole)
            out.append(os.path.join(self.current_path, name) if self.mode=="local" else self.current_path.rstrip("/")+"/"+name)
        return out

class FileTransferWidget(QWidget):
    def __init__(self, ssh_wrapper=None, parent=None):
        super().__init__(parent)
        self.ssh = ssh_wrapper
        self.watchers = {}  # remote_path -> RemoteEditWatcher
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.local_browser = FileBrowserWidget(mode="local", ssh_wrapper=self.ssh)
        self.remote_browser = FileBrowserWidget(mode="remote", ssh_wrapper=self.ssh)
        splitter.addWidget(self._wrap_with_title(self.local_browser, "💻 Local Files  (drag from file manager here)"))
        splitter.addWidget(self._wrap_with_title(self.remote_browser, "🌐 Remote Files (SFTP)  [drag-drop enabled]"))
        splitter.setSizes([500,500])
        layout.addWidget(splitter, 1)

        ctrl = QHBoxLayout()
        self.btn_upload = QPushButton("Upload → →")
        self.btn_upload.setStyleSheet("background:#4caf50; color:white; font-weight:bold; padding:6px;")
        self.btn_upload.clicked.connect(self.do_upload)
        self.btn_download = QPushButton("← ← Download")
        self.btn_download.setStyleSheet("background:#2196f3; color:white; font-weight:bold; padding:6px;")
        self.btn_download.clicked.connect(self.do_download)
        self.btn_refresh_both = QPushButton("Refresh Both")
        self.btn_refresh_both.clicked.connect(lambda: (self.local_browser.refresh(), self.remote_browser.refresh()))
        self.btn_edit = QPushButton("✏️ Edit Remote")
        self.btn_edit.setToolTip("Download remote file, edit locally, auto-upload on save")
        self.btn_edit.clicked.connect(self.do_edit_remote)
        ctrl.addWidget(self.btn_upload)
        ctrl.addWidget(self.btn_download)
        ctrl.addWidget(self.btn_edit)
        ctrl.addWidget(self.btn_refresh_both)
        ctrl.addStretch()
        self.progress = QProgressBar()
        self.progress.setFixedWidth(280)
        self.progress.setVisible(False)
        ctrl.addWidget(self.progress)
        self.status = QLabel("Drag & drop: drop OS files onto Remote pane to upload, drag Remote files onto Local pane to download")
        self.status.setStyleSheet("color:#666; font-size:10px;")
        self.status.setWordWrap(True)
        ctrl.addWidget(self.status)
        layout.addLayout(ctrl)

        # connect transfer signals
        self.local_browser.transfer_requested.connect(self._on_local_transfer)
        self.remote_browser.transfer_requested.connect(self._on_remote_transfer)
        # drag-drop signals
        self.remote_browser.external_drop.connect(self._on_external_drop_upload)
        self.local_browser.remote_files_dropped.connect(self._on_remote_drop_download)

    def _wrap_with_title(self, widget, title):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0,0,0,0)
        lbl = QLabel(title)
        lbl.setStyleSheet("background:#2d2d2d; color:white; padding:6px; font-weight:bold;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.addWidget(lbl)
        l.addWidget(widget,1)
        return w

    def set_ssh(self, ssh):
        self.ssh = ssh
        self.local_browser.ssh = ssh
        self.remote_browser.set_ssh(ssh)
        enabled = ssh and ssh.connected
        self.btn_upload.setEnabled(enabled)
        self.btn_download.setEnabled(enabled)
        self.btn_edit.setEnabled(enabled)

    # --- drag-drop handlers ---
    def _on_external_drop_upload(self, local_paths):
        if not self.ssh or not self.ssh.connected:
            QMessageBox.warning(self, "Not connected", "Connect first")
            return
        for lp in local_paths:
            if os.path.isfile(lp):
                self._start_transfer("up", lp, self.remote_browser.current_path)
            elif os.path.isdir(lp):
                QMessageBox.information(self, "Folder", f"Folder drop not yet recursive: {lp}\nZip it first.")
        self.status.setText(f"Dropped {len(local_paths)} files for upload")

    def _on_remote_drop_download(self, remote_paths):
        if not self.ssh or not self.ssh.connected:
            return
        for rp in remote_paths:
            self._start_transfer("down", self.local_browser.current_path, rp)
        self.status.setText(f"Downloading {len(remote_paths)} files via drag-drop")

    def _on_local_transfer(self, path, mode):
        # from local browser: path is local file
        self.do_upload(path)

    def _on_remote_transfer(self, path, mode):
        if mode == "edit":
            self.do_edit_remote(path)
        elif mode == "edit_with":
            self.do_edit_remote(path, choose_app=True)
        elif mode == "download":
            self.do_download(path)
        else:
            self.do_download(path)

    def do_upload(self, local_path=None):
        if not self.ssh or not self.ssh.connected:
            QMessageBox.warning(self, "Not connected", "Connect to remote first.")
            return
        if local_path is None:
            # support multi-select
            paths = self.local_browser.selected_paths()
            if not paths:
                QMessageBox.information(self, "Select file", "Select files in Local pane.")
                return
            for p in paths:
                self._start_transfer("up", p, self.remote_browser.current_path)
            return
        # single path may be list? handle
        if isinstance(local_path, list):
            for p in local_path:
                self._start_transfer("up", p, self.remote_browser.current_path)
            return
        remote_dir = self.remote_browser.current_path
        self._start_transfer("up", local_path, remote_dir)

    def do_download(self, remote_path=None):
        if not self.ssh or not self.ssh.connected:
            QMessageBox.warning(self, "Not connected", "Connect to remote first.")
            return
        if remote_path is None:
            paths = self.remote_browser.selected_paths()
            if not paths:
                QMessageBox.information(self, "Select file", "Select files in Remote pane.")
                return
            for p in paths:
                self._start_transfer("down", self.local_browser.current_path, p)
            return
        if isinstance(remote_path, list):
            for p in remote_path:
                self._start_transfer("down", self.local_browser.current_path, p)
            return
        local_dir = self.local_browser.current_path
        self._start_transfer("down", local_dir, remote_path)

    def do_edit_remote(self, remote_path=None, choose_app=False):
        # Use QTimer to defer dialog so context menu has closed (avoids reentrancy crash)
        if choose_app:
            # defer to avoid crash when called from context menu
            QTimer.singleShot(100, lambda: self._do_edit_remote_impl(remote_path, True))
            return
        self._do_edit_remote_impl(remote_path, False)

    def _do_edit_remote_impl(self, remote_path=None, choose_app=False):
        try:
            if not self.ssh or not self.ssh.connected:
                QMessageBox.warning(self, "Not connected", "Connect first")
                return
            if remote_path is None:
                remote_path = self.remote_browser.selected_path()
            if not remote_path:
                QMessageBox.information(self, "Select", "Select a remote file to edit")
                return
            # check is dir?
            try:
                attr = self.ssh.sftp_stat(remote_path)
                if statmod.S_ISDIR(attr.st_mode):
                    QMessageBox.information(self, "Folder", "Can't edit a folder")
                    return
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))
                return
            # download to temp
            from utils.remote_edit import get_tmp_for_remote, open_with_local_app, RemoteEditWatcher
            tmp = get_tmp_for_remote(self.ssh.host, remote_path)
            self.status.setText(f"Downloading {os.path.basename(remote_path)} for edit...")
            try:
                self.ssh.sftp_get(remote_path, tmp)
            except Exception as e:
                QMessageBox.warning(self, "Download failed", str(e))
                return
            # open - Ubuntu-like Open With dialog (shows app list, not folder)
            opened = False
            if choose_app:
                try:
                    from gui.open_with_dialog import OpenWithDialog, launch_with_app
                    dlg = OpenWithDialog(tmp, self)
                    # use show to avoid blocking? exec is fine as we are deferred
                    if dlg.exec() == QDialog.DialogCode.Accepted:
                        app_info = dlg.get_selected()
                        if app_info:
                            # launch with chosen app via its Exec
                            if launch_with_app(app_info, tmp):
                                opened = True
                            else:
                                raise Exception(f"Failed to launch {app_info['name']}")
                        else:
                            # Open with Default (xdg-open)
                            open_with_local_app(tmp)
                            opened = True
                    else:
                        # cancelled - don't open, but not crash
                        self.status.setText("Open With cancelled")
                        return
                except Exception as e:
                    print(f"[Open With] dialog failed {e}, fallback to xdg-open")
                    try:
                        open_with_local_app(tmp)
                        opened = True
                    except Exception as e2:
                        QMessageBox.warning(self, "Open failed", f"Could not open:\n{e}\n{e2}")
                        return
            else:
                try:
                    open_with_local_app(tmp)
                    opened = True
                except Exception as e:
                    QMessageBox.warning(self, "Open failed", str(e))
                    return
            if not opened:
                return
            if remote_path in self.watchers:
                try: self.watchers[remote_path].stop()
                except: pass
            watcher = RemoteEditWatcher(self.ssh, remote_path, tmp, parent=self)
            watcher.uploaded.connect(self._on_edit_uploaded)
            self.watchers[remote_path] = watcher
            self.status.setText(f"Editing {os.path.basename(remote_path)} — save in local app to auto-upload")
            QMessageBox.information(self, "Editing", f"Opened {os.path.basename(remote_path)}\n\nLocal copy: {tmp}\n\nEdit and Save — it will auto-upload to remote.\nWatcher active (poll 1.5s).")
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "Error", f"Open With failed (not crashing):\n{e}")

    def _on_edit_uploaded(self, remote_path, ok, msg):
        if ok:
            self.status.setText(f"✓ Auto-uploaded {os.path.basename(remote_path)}")
            self.remote_browser.refresh()
        else:
            self.status.setText(f"✗ Auto-upload failed: {msg}")

    def _start_transfer(self, direction, local, remote):
        worker = SFTPWorker(self.ssh, direction, local, remote)
        worker.progress.connect(self._on_progress)
        worker.finished_signal.connect(self._on_finished)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.status.setText(f"{'Uploading' if direction=='up' else 'Downloading'} {os.path.basename(local if direction=='up' else remote)}...")
        self._worker = worker  # keep ref (last only, for multi need list)
        # for multi, we keep list
        if not hasattr(self, "_workers"):
            self._workers = []
        self._workers.append(worker)
        worker.start()

    def _on_progress(self, cur, total, name):
        if total>0:
            pct = int(cur/total*100)
            self.progress.setValue(pct)
            self.status.setText(f"{name}: {pct}%")

    def _on_finished(self, ok, msg):
        self.progress.setVisible(False)
        if ok:
            self.status.setText(msg)
            self.local_browser.refresh()
            self.remote_browser.refresh()
        else:
            self.status.setText(f"Error: {msg}")
            QMessageBox.warning(self, "Transfer failed", msg)
