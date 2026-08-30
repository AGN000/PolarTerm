import os
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QLabel,
                             QInputDialog, QMessageBox, QFileDialog, QTextEdit, QSplitter, QCheckBox)
from PyQt6.QtCore import Qt
from core.config import load_command_files, save_command_files, add_command_file, delete_command_file, CommandFile, get_command_file_commands

class CommandManagerDialog(QDialog):
    """Manager for bash command files - add multiple files, each with alias, preview and run in terminal."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚡ Command Files — PolarTerm")
        self.resize(700, 450)
        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        hdr = QLabel("Add files containing bash commands/comments. Each file has a name; select and click <b>Run</b> to execute in the active terminal (no copy-paste).")
        hdr.setWordWrap(True)
        hdr.setStyleSheet("color:#334155; font-size:11px; background:#f0f9ff; padding:8px; border:1px solid #bae6fd; border-radius:6px;")
        layout.addWidget(hdr)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        # left: files list
        left_w = QVBoxLayout()
        left_container = QLabel()
        # Actually use QWidget
        from PyQt6.QtWidgets import QWidget
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0,0,0,0)
        left_layout.addWidget(QLabel("<b>Command Files</b>"))
        self.file_list = QListWidget()
        self.file_list.setStyleSheet("""
            QListWidget { background:white; border:1px solid #e2e8f0; border-radius:8px; }
            QListWidget::item { padding:8px; border-bottom:1px solid #f1f5f9; }
            QListWidget::item:selected { background:#fffbeb; color:#92400e; }
        """)
        self.file_list.currentItemChanged.connect(self.on_file_select)
        self.file_list.doubleClicked.connect(self.run_all)
        left_layout.addWidget(self.file_list, 1)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("＋ Add File")
        btn_add.setToolTip("Choose existing .sh file")
        btn_add.setStyleSheet("background:#fffbeb; border:1px solid #fcd34d; padding:6px 8px; border-radius:6px;")
        btn_add.clicked.connect(self.add_file)
        btn_new = QPushButton("＋ New File")
        btn_new.setToolTip("Create new empty command file")
        btn_new.setStyleSheet("background:#e0f2fe; border:1px solid #7dd3fc; padding:6px 8px; border-radius:6px;")
        btn_new.clicked.connect(self.new_file)
        btn_del = QPushButton("✕ Remove")
        btn_del.setStyleSheet("color:#dc2626;")
        btn_del.clicked.connect(self.delete_file)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_new)
        btn_row.addWidget(btn_del)
        left_layout.addLayout(btn_row)
        btn_row2 = QHBoxLayout()
        btn_rename = QPushButton("✏️ Rename")
        btn_rename.clicked.connect(self.rename_file)
        btn_edit = QPushButton("📝 Edit File")
        btn_edit.setToolTip("Open file in local editor")
        btn_edit.clicked.connect(self.edit_file)
        btn_row2.addWidget(btn_rename)
        btn_row2.addWidget(btn_edit)
        left_layout.addLayout(btn_row2)
        splitter.addWidget(left_widget)

        # right: commands preview
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0,0,0,0)
        self.preview_label = QLabel("<b>Commands Preview</b> (click Run to execute in active terminal)")
        right_layout.addWidget(self.preview_label)
        self.cmd_list = QListWidget()
        self.cmd_list.setStyleSheet("""
            QListWidget { background:#0f172a; color:#e2e8f0; border:1px solid #334155; border-radius:8px; font-family: monospace; }
            QListWidget::item { padding:4px; }
            QListWidget::item:selected { background:#1e3a5f; }
        """)
        self.cmd_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.cmd_list.doubleClicked.connect(self.run_selected)
        right_layout.addWidget(self.cmd_list, 1)
        # preview text edit for file not found
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setStyleSheet("background:#0f172a; color:#e2e8f0; font-family: monospace; border-radius:8px;")
        self.preview_text.hide()
        right_layout.addWidget(self.preview_text, 1)

        run_row = QHBoxLayout()
        btn_run_sel = QPushButton("▶ Run Selected")
        btn_run_sel.setStyleSheet("background:#0284c7; color:white; font-weight:bold; padding:8px 12px; border-radius:6px;")
        btn_run_sel.setToolTip("Execute selected lines in active terminal (uses _do_paste line-by-line)")
        btn_run_sel.clicked.connect(self.run_selected)
        btn_run_all = QPushButton("▶▶ Run All")
        btn_run_all.setStyleSheet("background:#059669; color:white; font-weight:bold; padding:8px 12px; border-radius:6px;")
        btn_run_all.setToolTip("Execute all commands in file sequentially")
        btn_run_all.clicked.connect(self.run_all)
        run_row.addWidget(btn_run_sel)
        run_row.addWidget(btn_run_all)
        right_layout.addLayout(run_row)

        splitter.addWidget(right_widget)
        splitter.setSizes([250, 450])
        layout.addWidget(splitter, 1)

        # bottom close
        close_row = QHBoxLayout()
        close_row.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        close_row.addWidget(btn_close)
        layout.addLayout(close_row)

    def refresh(self):
        self.file_list.clear()
        for cf in load_command_files():
            exists = "✅" if os.path.exists(cf.path) else "⚠️"
            txt = f"{exists} {cf.alias} → {cf.path}"
            if cf.description:
                txt += f"  ({cf.description})"
            item = QListWidgetItem(txt)
            item.setData(Qt.ItemDataRole.UserRole, cf.alias)
            if not os.path.exists(cf.path):
                item.setToolTip("File not found - double-click to locate or remove")
            else:
                item.setToolTip(cf.path)
            self.file_list.addItem(item)
        if self.file_list.count()==0:
            self.file_list.addItem("No command files yet. Click ＋ Add File.")

    def on_file_select(self, cur, prev):
        self.cmd_list.clear()
        self.preview_text.hide()
        self.cmd_list.show()
        if not cur or not cur.data(Qt.ItemDataRole.UserRole):
            self.preview_label.setText("<b>Commands Preview</b>")
            return
        alias = cur.data(Qt.ItemDataRole.UserRole)
        cfs = {cf.alias: cf for cf in load_command_files()}
        cf = cfs.get(alias)
        if not cf:
            return
        self.preview_label.setText(f"<b>{cf.alias}</b> — {cf.path}")
        if not os.path.exists(cf.path):
            self.cmd_list.hide()
            self.preview_text.show()
            self.preview_text.setPlainText(f"File not found:\n{cf.path}\n\nRemove and re-add.")
            return
        cmds = get_command_file_commands(cf)
        if not cmds:
            self.cmd_list.addItem("(empty - no commands)")
            return
        for idx, line in enumerate(cmds):
            # show line numbers
            display = f"{idx+1:2d} | {line}"
            # mark comments differently
            item = QListWidgetItem(display)
            if line.strip().startswith("#"):
                item.setForeground(Qt.GlobalColor.gray)
                item.setToolTip("Comment line - will be sent but bash will ignore")
            else:
                item.setToolTip("Double-click to run this line")
            item.setData(Qt.ItemDataRole.UserRole, line)
            self.cmd_list.addItem(item)

    def add_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Bash Command File", os.path.expanduser("~"), "Shell Scripts (*.sh *.bash *.txt);;All Files (*)")
        if not path:
            return
        alias, ok = QInputDialog.getText(self, "Command File Name", f"Display name for\n{path}:", text=os.path.splitext(os.path.basename(path))[0] or "commands")
        if not ok or not alias.strip():
            return
        alias = alias.strip()
        # check duplicate
        for cf in load_command_files():
            if cf.alias == alias:
                QMessageBox.warning(self, "Exists", f"Name '{alias}' already exists. Choose another.")
                return
        desc, ok2 = QInputDialog.getText(self, "Description (optional)", "Short description:")
        if not ok2:
            desc = ""
        cf = CommandFile(alias=alias, path=path, description=desc.strip())
        add_command_file(cf)
        self.refresh()
        # select new
        for i in range(self.file_list.count()):
            if self.file_list.item(i).data(Qt.ItemDataRole.UserRole)==alias:
                self.file_list.setCurrentRow(i)
                break

    def new_file(self):
        alias, ok = QInputDialog.getText(self, "New Command File", "Name for new file:")
        if not ok or not alias.strip():
            return
        alias = alias.strip()
        for cf in load_command_files():
            if cf.alias == alias:
                QMessageBox.warning(self, "Exists", f"Name '{alias}' exists.")
                return
        path, _ = QFileDialog.getSaveFileName(self, "Create New Command File", os.path.join(os.path.expanduser("~"), f"{alias}.sh"), "Shell Scripts (*.sh);;All Files (*)")
        if not path:
            return
        # create empty file with shebang and example
        try:
            with open(path, 'w') as f:
                f.write("#!/bin/bash\n# Add your bash commands below, one per line\n# Example:\n# module purge\n# module load openmpi/gnu/4.1.6.5\n# source /path/to/bashrc\n")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not create file:\n{e}")
            return
        desc, _ = QInputDialog.getText(self, "Description", "Description:")
        cf = CommandFile(alias=alias, path=path, description=desc.strip() if desc else "")
        add_command_file(cf)
        self.refresh()
        for i in range(self.file_list.count()):
            if self.file_list.item(i).data(Qt.ItemDataRole.UserRole)==alias:
                self.file_list.setCurrentRow(i)
                break

    def delete_file(self):
        item = self.file_list.currentItem()
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            return
        alias = item.data(Qt.ItemDataRole.UserRole)
        if QMessageBox.question(self, "Remove", f"Remove command file '{alias}' from list?\n(File on disk will NOT be deleted)") == QMessageBox.StandardButton.Yes:
            delete_command_file(alias)
            self.refresh()
            self.cmd_list.clear()

    def rename_file(self):
        item = self.file_list.currentItem()
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            return
        alias = item.data(Qt.ItemDataRole.UserRole)
        new_alias, ok = QInputDialog.getText(self, "Rename", "New name:", text=alias)
        if not ok or not new_alias.strip() or new_alias.strip()==alias:
            return
        new_alias = new_alias.strip()
        for cf in load_command_files():
            if cf.alias == new_alias:
                QMessageBox.warning(self, "Exists", f"Name '{new_alias}' exists.")
                return
        cfs = load_command_files()
        for cf in cfs:
            if cf.alias == alias:
                cf.alias = new_alias
                break
        from core.config import save_command_files
        save_command_files(cfs)
        self.refresh()
        for i in range(self.file_list.count()):
            if self.file_list.item(i).data(Qt.ItemDataRole.UserRole)==new_alias:
                self.file_list.setCurrentRow(i)
                break

    def edit_file(self):
        item = self.file_list.currentItem()
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            return
        alias = item.data(Qt.ItemDataRole.UserRole)
        cf = next((c for c in load_command_files() if c.alias==alias), None)
        if not cf or not os.path.exists(cf.path):
            QMessageBox.warning(self, "Not found", f"File not found:\n{cf.path if cf else 'unknown'}")
            return
        # Try xdg-open
        import subprocess
        try:
            subprocess.Popen(["xdg-open", cf.path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except:
            QMessageBox.information(self, "Edit", f"Edit file manually:\n{cf.path}")

    def _get_active_terminal(self):
        parent = self.parent()
        if not parent or not hasattr(parent, 'tabs'):
            return None
        # try current tab first
        cur = parent.tabs.currentWidget()
        if hasattr(cur, '_send') or hasattr(cur, '_do_paste'):
            # check if it's a terminal (not FileTransfer)
            from gui.file_transfer_widget import FileTransferWidget
            if not isinstance(cur, FileTransferWidget):
                return cur
        # fallback: find any terminal tab
        for idx in range(parent.tabs.count()):
            w = parent.tabs.widget(idx)
            if hasattr(w, '_send') and hasattr(w, '_do_paste'):
                from gui.file_transfer_widget import FileTransferWidget
                if not isinstance(w, FileTransferWidget):
                    return w
        # also check terminal_tabs dict
        if hasattr(parent, 'terminal_tabs'):
            for t in parent.terminal_tabs.values():
                if hasattr(t, '_send'):
                    return t
        return None

    def _send_commands(self, commands):
        if not commands:
            QMessageBox.information(self, "No commands", "No commands to run.")
            return
        term = self._get_active_terminal()
        if not term:
            QMessageBox.information(self, "No terminal", "Open a terminal tab first (SSH or Local), then Run.")
            return
        # Filter: keep all non-empty lines; comments will be sent but bash ignores
        # Join with \n and ensure trailing \n
        text = "\n".join(commands)
        if not text.endswith("\n"):
            text += "\n"
        # Prefer _do_paste for multi-line handling (40ms spacing, bracketed-paste fix)
        try:
            if hasattr(term, '_do_paste'):
                term._do_paste(text)
            elif hasattr(term, '_send'):
                term._send(text.encode())
            # bring terminal tab to front
            parent = self.parent()
            if parent and hasattr(parent, 'tabs'):
                for i in range(parent.tabs.count()):
                    if parent.tabs.widget(i) == term:
                        parent.tabs.setCurrentIndex(i)
                        break
                # also try to find via terminal_tabs
                if hasattr(term, 'terminal'):
                    # ensure not native xterm which doesn't support _send
                    from gui.native_terminal import XTermEmbeddedWidget
                    if isinstance(term, XTermEmbeddedWidget):
                        QMessageBox.information(self, "Native Terminal", "Native xterm: commands were not auto-sent. Please type or use emulated terminal (View → uncheck Native).")
                        return
        except Exception as e:
            QMessageBox.warning(self, "Send failed", str(e))

    def run_selected(self):
        item = self.file_list.currentItem()
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            QMessageBox.information(self, "Select", "Select a command file first.")
            return
        alias = item.data(Qt.ItemDataRole.UserRole)
        cf = next((c for c in load_command_files() if c.alias==alias), None)
        if not cf:
            return
        selected = self.cmd_list.selectedItems()
        if not selected:
            # if double-clicked single item, run that one
            row = self.cmd_list.currentRow()
            if row >=0:
                it = self.cmd_list.item(row)
                line = it.data(Qt.ItemDataRole.UserRole)
                if line is not None:
                    self._send_commands([line])
                    return
            QMessageBox.information(self, "Select", "Select one or more commands (Ctrl+Click) then Run Selected, or double-click a line.")
            return
        cmds = [it.data(Qt.ItemDataRole.UserRole) for it in selected if it.data(Qt.ItemDataRole.UserRole) is not None]
        # filter out pure comment lines? keep but bash will ignore
        self._send_commands(cmds)

    def run_all(self):
        item = self.file_list.currentItem()
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            # try double-click sender
            alias = item.data(Qt.ItemDataRole.UserRole) if item else None
            if not alias:
                QMessageBox.information(self, "Select", "Select a command file.")
                return
        else:
            alias = item.data(Qt.ItemDataRole.UserRole)
        cf = next((c for c in load_command_files() if c.alias==alias), None)
        if not cf or not os.path.exists(cf.path):
            QMessageBox.warning(self, "Not found", f"File not found:\n{cf.path if cf else 'unknown'}")
            return
        cmds = get_command_file_commands(cf)
        if not cmds:
            QMessageBox.information(self, "Empty", "File has no commands.")
            return
        # confirm if many
        if len(cmds) > 10:
            if QMessageBox.question(self, "Run All", f"Run all {len(cmds)} commands from '{alias}' in active terminal?") != QMessageBox.StandardButton.Yes:
                return
        self._send_commands(cmds)
