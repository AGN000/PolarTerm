from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QSpinBox, QComboBox, QPushButton, QCheckBox, QFileDialog, QLabel, QTextEdit, QGroupBox
from PyQt6.QtCore import Qt
from core.config import Session
import os

class SessionDialog(QDialog):
    def __init__(self, parent=None, session: Session=None):
        super().__init__(parent)
        self.setWindowTitle("New Session" if not session else "Edit Session")
        self.setMinimumWidth(520)
        self.editing = session
        self._setup_ui()
        if session:
            self.load_session(session)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        # Session group
        g1 = QGroupBox("Session")
        f1 = QFormLayout(g1)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("My HPC / my-server")
        self.host_edit = QLineEdit(); self.host_edit.setPlaceholderText("hpc.iitb.ac.in or 192.168.1.10")
        self.port_spin = QSpinBox(); self.port_spin.setRange(1,65535); self.port_spin.setValue(22)
        self.user_edit = QLineEdit(); self.user_edit.setPlaceholderText("username")
        f1.addRow("Session Name*:", self.name_edit)
        f1.addRow("Host*:", self.host_edit)
        f1.addRow("Port:", self.port_spin)
        f1.addRow("Username*:", self.user_edit)
        layout.addWidget(g1)

        # Auth group
        g2 = QGroupBox("Authentication")
        f2 = QFormLayout(g2)
        self.auth_combo = QComboBox(); self.auth_combo.addItems(["password", "key"])
        self.auth_combo.currentTextChanged.connect(self._on_auth_changed)
        self.pass_edit = QLineEdit(); self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password); self.pass_edit.setPlaceholderText("password")
        self.key_edit = QLineEdit(); self.key_edit.setPlaceholderText("~/.ssh/id_rsa")
        self.key_browse = QPushButton("Browse")
        self.key_browse.clicked.connect(self._browse_key)
        key_layout = QHBoxLayout(); key_layout.addWidget(self.key_edit,1); key_layout.addWidget(self.key_browse)
        self.key_pass_edit = QLineEdit(); self.key_pass_edit.setEchoMode(QLineEdit.EchoMode.Password); self.key_pass_edit.setPlaceholderText("optional passphrase")
        self.save_pass_chk = QCheckBox("Save password / passphrase (encrypted with Fernet, 0600 perms in ~/.config/polarterm)")
        f2.addRow("Method:", self.auth_combo)
        f2.addRow("Password:", self.pass_edit)
        f2.addRow("Key File:", key_layout)
        f2.addRow("Key Passphrase:", self.key_pass_edit)
        f2.addRow("", self.save_pass_chk)
        layout.addWidget(g2)

        # Advanced
        g3 = QGroupBox("Advanced (optional)")
        f3 = QFormLayout(g3)
        self.remote_path_edit = QLineEdit(); self.remote_path_edit.setPlaceholderText("~/  or /home/user/project")
        self.remote_path_edit.setText("~")
        self.jump_edit = QLineEdit(); self.jump_edit.setPlaceholderText("user@jump.host:22  (leave empty if none)")
        self.notes_edit = QLineEdit(); self.notes_edit.setPlaceholderText("e.g., PARAM Sathi, CFD cluster")
        f3.addRow("Remote Initial Path:", self.remote_path_edit)
        f3.addRow("Jump Host (Bastion):", self.jump_edit)
        f3.addRow("Notes:", self.notes_edit)
        layout.addWidget(g3)

        # buttons
        btns = QHBoxLayout()
        btns.addStretch()
        self.btn_cancel = QPushButton("Cancel"); self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("Save"); self.btn_ok.setDefault(True); self.btn_ok.setStyleSheet("background:#2196f3; color:white; font-weight:bold; padding:6px 20px;")
        self.btn_ok.clicked.connect(self.accept)
        btns.addWidget(self.btn_cancel); btns.addWidget(self.btn_ok)
        layout.addLayout(btns)

        self._on_auth_changed(self.auth_combo.currentText())

    def _on_auth_changed(self, t):
        is_pass = (t=="password")
        self.pass_edit.setEnabled(is_pass)
        self.key_edit.setEnabled(not is_pass)
        self.key_browse.setEnabled(not is_pass)
        self.key_pass_edit.setEnabled(not is_pass)

    def _browse_key(self):
        p, _ = QFileDialog.getOpenFileName(self, "Select Private Key", os.path.expanduser("~/.ssh"))
        if p:
            self.key_edit.setText(p)

    def load_session(self, s: Session):
        self.name_edit.setText(s.name)
        self.host_edit.setText(s.host)
        self.port_spin.setValue(s.port)
        self.user_edit.setText(s.username)
        self.auth_combo.setCurrentText(s.auth_method)
        self.pass_edit.setText(s.password)
        self.key_edit.setText(s.key_path)
        self.key_pass_edit.setText(s.key_passphrase)
        self.save_pass_chk.setChecked(s.save_password)
        self.remote_path_edit.setText(s.remote_path)
        self.jump_edit.setText(s.jump_host)
        self.notes_edit.setText(s.notes)

    def get_session(self) -> Session:
        return Session(
            name=self.name_edit.text().strip(),
            host=self.host_edit.text().strip(),
            port=self.port_spin.value(),
            username=self.user_edit.text().strip(),
            auth_method=self.auth_combo.currentText(),
            password=self.pass_edit.text(),
            key_path=self.key_edit.text().strip(),
            key_passphrase=self.key_pass_edit.text(),
            remote_path=self.remote_path_edit.text().strip() or "~",
            save_password=self.save_pass_chk.isChecked(),
            jump_host=self.jump_edit.text().strip(),
            notes=self.notes_edit.text().strip()
        )

    def accept(self):
        s = self.get_session()
        if not s.name or not s.host or not s.username:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Missing", "Name, Host and Username are required.")
            return
        super().accept()
