import os, glob, configparser, mimetypes, subprocess
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QLabel, QLineEdit, QCheckBox
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon

def get_mime_type(filepath):
    # try xdg-mime, then gio, then mimetypes
    try:
        out = subprocess.check_output(["xdg-mime", "query", "filetype", filepath], stderr=subprocess.DEVNULL, timeout=2).decode().strip()
        if out:
            return out
    except: pass
    try:
        out = subprocess.check_output(["gio", "info", "-a", "standard::content-type", filepath], stderr=subprocess.DEVNULL, timeout=2).decode()
        for line in out.splitlines():
            if "standard::content-type" in line:
                return line.split(":")[-1].strip()
    except: pass
    mt, _ = mimetypes.guess_type(filepath)
    return mt or "application/octet-stream"

def scan_desktop_files():
    apps = []
    seen = set()
    for d in ["/usr/share/applications", os.path.expanduser("~/.local/share/applications"), "/var/lib/snapd/desktop/applications"]:
        if not os.path.isdir(d):
            continue
        for fp in glob.glob(os.path.join(d, "*.desktop")):
            try:
                base = os.path.basename(fp)
                if base in seen:
                    continue
                seen.add(base)
                cp = configparser.ConfigParser(interpolation=None)
                cp.optionxform = str
                # need to handle desktop files with only [Desktop Entry]
                try:
                    cp.read(fp, encoding='utf-8')
                except:
                    continue
                if "Desktop Entry" not in cp:
                    continue
                entry = cp["Desktop Entry"]
                if entry.get("NoDisplay", "false").lower() == "true": continue
                if entry.get("Hidden", "false").lower() == "true": continue
                if entry.get("Type", "Application") != "Application": continue
                name = entry.get("Name", base)
                exec_cmd = entry.get("Exec", "")
                if not exec_cmd: continue
                icon = entry.get("Icon", "")
                mime = entry.get("MimeType", "")
                # skip if Exec is just env etc.
                apps.append({"name": name, "exec": exec_cmd, "icon": icon, "mime": mime, "file": fp, "desktop": base})
            except: continue
    apps.sort(key=lambda x: x["name"].lower())
    return apps

def apps_for_mime(mime, apps):
    # return recommended + others
    if not mime:
        return apps, []
    recommended = []
    others = []
    # mime could be like text/markdown, we match exact and also type/*
    mtype = mime.split("/")[0] if "/" in mime else mime
    for a in apps:
        mimes = a["mime"]
        if mime in mimes or f"{mtype}/*" in mimes or "application/octet-stream" in mimes:
            recommended.append(a)
        elif mtype == "text" and "text/plain" in mimes:
            recommended.append(a)
        else:
            # also include if no mime filtering? We'll put in others
            others.append(a)
    # if no recommended, show all as recommended
    if not recommended:
        recommended = apps[:15]
        others = apps[15:]
    else:
        # limit recommended to reasonable
        # keep others as rest
        pass
    return recommended, others

class OpenWithDialog(QDialog):
    """Ubuntu-like Open With dialog: shows available apps for file's mime type with icons."""
    def __init__(self, filepath, parent=None):
        super().__init__(parent)
        self.filepath = filepath
        self.selected_app = None
        self.setWindowTitle(f"Open With — {os.path.basename(filepath)}")
        self.resize(520, 460)
        self.setModal(True)
        layout = QVBoxLayout(self)
        # header
        mime = get_mime_type(filepath)
        hdr = QLabel(f"Select application to open <b>{os.path.basename(filepath)}</b><br><span style='color:#64748b; font-size:11px;'>{mime} — {filepath}</span>")
        hdr.setWordWrap(True)
        layout.addWidget(hdr)
        # search
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter applications...")
        self.search.textChanged.connect(self._filter)
        search_row.addWidget(self.search)
        layout.addLayout(search_row)
        # list
        self.list = QListWidget()
        self.list.setIconSize(QSize(24,24))
        self.list.setStyleSheet("""
            QListWidget { background:white; border:1px solid #e2e8f0; border-radius:8px; }
            QListWidget::item { padding:8px; border-bottom:1px solid #f1f5f9; }
            QListWidget::item:selected { background:#e0f2fe; color:#0c4a6e; }
        """)
        self.list.doubleClicked.connect(self.accept)
        layout.addWidget(self.list, 1)
        # buttons
        btn_row = QHBoxLayout()
        self.btn_default = QPushButton("Open with Default")
        self.btn_default.setToolTip("Use xdg-open / default app")
        self.btn_default.clicked.connect(self._use_default)
        btn_row.addWidget(self.btn_default)
        btn_row.addStretch()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("Open")
        btn_ok.setDefault(True)
        btn_ok.setStyleSheet("background:#0284c7; color:white; font-weight:bold; padding:6px 14px; border-radius:6px;")
        btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)
        # other apps checkbox
        self.show_all = QCheckBox("Show all applications")
        self.show_all.toggled.connect(self._reload)
        layout.addWidget(self.show_all)
        # load
        self.all_apps = scan_desktop_files()
        self.mime = mime
        self._reload()
        # select first
        if self.list.count()>0:
            self.list.setCurrentRow(0)

    def _reload(self):
        self.list.clear()
        rec, others = apps_for_mime(self.mime, self.all_apps)
        show = rec if not self.show_all.isChecked() else self.all_apps
        filt = self.search.text().lower().strip()
        for app in show:
            if filt and filt not in app["name"].lower() and filt not in app["exec"].lower():
                continue
            item = QListWidgetItem(app["name"])
            # icon
            icon = None
            if app["icon"]:
                # try theme icon, then file path
                icon = QIcon.fromTheme(app["icon"])
                if icon.isNull() and os.path.exists(app["icon"]):
                    icon = QIcon(app["icon"])
                # also try /usr/share/icons
                if icon.isNull():
                    # try to find icon file
                    for base in ["/usr/share/icons", "/usr/share/pixmaps"]:
                        for ext in [".png",".svg",".xpm"]:
                            cand = os.path.join(base, app["icon"]+ext)
                            if os.path.exists(cand):
                                icon = QIcon(cand)
                                break
            if icon and not icon.isNull():
                item.setIcon(icon)
            else:
                item.setIcon(QIcon.fromTheme("application-x-executable"))
            item.setData(Qt.ItemDataRole.UserRole, app)
            item.setToolTip(f"{app['name']}\n{app['exec']}\n{app['file']}")
            self.list.addItem(item)
        if self.list.count()==0:
            self.list.addItem("No matching applications — try 'Show all'")

    def _filter(self, _):
        self._reload()

    def _use_default(self):
        self.selected_app = None
        self.accept()

    def accept(self):
        cur = self.list.currentItem()
        if cur and cur.data(Qt.ItemDataRole.UserRole):
            self.selected_app = cur.data(Qt.ItemDataRole.UserRole)
        super().accept()

    def get_selected(self):
        return self.selected_app

def launch_with_app(app_info, filepath):
    """Launch file with app_info Exec, handling %f/%F/%u/%U"""
    exec_cmd = app_info["exec"]
    # remove field codes not needed and handle
    # Exec may contain %f, %F, %u, %U, %i, %c, %k etc.
    # Simplest: replace %f/%F/%u/%U with filepath, remove others
    import shlex
    # Remove deprecated %i, %c, %k etc. with their values
    # For simplicity, replace known placeholders
    # Use shlex to split Exec then rejoin
    try:
        # Remove field codes that would be expanded by desktop environment
        # e.g., Exec=gnome-text-editor %U  -> gnome-text-editor <file>
        cmd = exec_cmd
        # Remove %i, %c, %k and following?
        for code in ["%i", "%c", "%k"]:
            cmd = cmd.replace(code, "")
        # Replace file placeholders
        if "%F" in cmd:
            cmd = cmd.replace("%F", shlex.quote(filepath))
        elif "%f" in cmd:
            cmd = cmd.replace("%f", shlex.quote(filepath))
        elif "%U" in cmd:
            cmd = cmd.replace("%U", shlex.quote(filepath))
        elif "%u" in cmd:
            cmd = cmd.replace("%u", shlex.quote(filepath))
        else:
            cmd += " " + shlex.quote(filepath)
        # Now split and launch
        import subprocess, shlex as sh
        # Use shell=False with shlex.split to handle Exec properly
        parts = sh.split(cmd)
        subprocess.Popen(parts, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except Exception as e:
        print(f"[open_with] launch failed {e}")
        return False
