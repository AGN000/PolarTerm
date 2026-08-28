from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QToolTip
from PyQt6.QtCore import QTimer, pyqtSignal, Qt, QThread
from PyQt6.QtGui import QFont
import re

class JobPollWorker(QThread):
    result = pyqtSignal(int, str, str)  # count, raw, session
    error = pyqtSignal(str)
    def __init__(self, ssh_wrapper, session_name):
        super().__init__()
        self.ssh = ssh_wrapper
        self.session = session_name

    def run(self):
        try:
            # try squeue (SLURM) then qstat (PBS)
            cmds = [
                "squeue -h -u $USER 2>/dev/null | wc -l",
                "qstat -u $USER 2>/dev/null | tail -n +3 | wc -l",
                "squeue -u $USER 2>&1 | head -n 20",
                "qstat 2>&1 | head -n 20",
            ]
            # we try to get a meaningful count; first try squeue
            import time
            # quick check: try squeue -h
            try:
                stdin, stdout, stderr = self.ssh.exec_command("squeue -h -u $USER 2>&1 | wc -l; echo __SEP__; squeue -h -u $USER 2>&1 | head -n 5", timeout=8)
                out = stdout.read().decode(errors='ignore')
                err = stderr.read().decode(errors='ignore')
                # out contains count + sep + sample
                parts = out.strip().split("__SEP__")
                cnt_str = parts[0].strip().splitlines()[0] if parts else "0"
                sample = parts[1] if len(parts)>1 else ""
                try:
                    cnt = int(re.findall(r'\d+', cnt_str)[0])
                except:
                    cnt = 0
                # if cnt still 0 but sample has jobs, try parsing sample lines
                if cnt==0 and sample.strip() and "not found" not in sample.lower() and "error" not in sample.lower():
                    # count non-empty lines that look like jobs
                    lines = [l for l in sample.strip().splitlines() if l.strip()]
                    if lines:
                        cnt = len(lines)
                self.result.emit(cnt, sample.strip()[:200], self.session)
                return
            except Exception as e:
                pass
            # fallback: try qstat
            stdin, stdout, stderr = self.ssh.exec_command("qstat -u $USER 2>&1 | tail -n +3 | wc -l; echo __SEP__; qstat -u $USER 2>&1 | head -n 8", timeout=8)
            out = stdout.read().decode(errors='ignore')
            parts = out.strip().split("__SEP__")
            cnt_str = parts[0].strip().splitlines()[0] if parts else "0"
            sample = parts[1] if len(parts)>1 else ""
            try:
                cnt = int(re.findall(r'\d+', cnt_str)[0])
            except:
                cnt = 0
            self.result.emit(cnt, sample.strip()[:200], self.session)
        except Exception as e:
            self.error.emit(str(e))

class JobIndicatorWidget(QWidget):
    jump_requested = pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ssh = None
        self.session_name = ""
        self.job_count = 0
        self.setFixedHeight(38)
        self.setStyleSheet("background: #f8fafc; border:1px solid #e2e8f0; border-radius:8px;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8,4,8,4)
        self.icon = QLabel("⚪")
        self.icon.setStyleSheet("font-size:18px;")
        self.icon.setFixedWidth(28)
        layout.addWidget(self.icon)
        self.label = QLabel("No job info")
        self.label.setStyleSheet("color:#475569; font-size:11px;")
        layout.addWidget(self.label, 1)
        self.btn_refresh = QPushButton("⟳")
        self.btn_refresh.setFixedSize(28,28)
        self.btn_refresh.setToolTip("Refresh job status (squeue/qstat)")
        self.btn_refresh.setStyleSheet("background:white; border:1px solid #cbd5e1; border-radius:6px;")
        self.btn_refresh.clicked.connect(self.refresh)
        layout.addWidget(self.btn_refresh)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.setInterval(30000)  # 30s poll

    def set_session(self, ssh_wrapper, session_name):
        self.ssh = ssh_wrapper
        self.session_name = session_name
        if ssh_wrapper and ssh_wrapper.connected:
            self.label.setText(f"Checking {session_name}...")
            self.icon.setText("⏳")
            self.timer.start()
            QTimer.singleShot(800, self.refresh)
        else:
            self.timer.stop()
            self.icon.setText("⚪")
            self.label.setText("Not connected")

    def clear(self):
        self.timer.stop()
        self.ssh = None
        self.session_name = ""
        self.icon.setText("⚪")
        self.label.setText("No job info")

    def refresh(self):
        if not self.ssh or not self.ssh.connected:
            self.icon.setText("⚪")
            self.label.setText("Not connected")
            return
        self.icon.setText("⏳")
        self.label.setText("Checking...")
        self.worker = JobPollWorker(self.ssh, self.session_name)
        self.worker.result.connect(self.on_result)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def on_result(self, cnt, raw, session):
        self.job_count = cnt
        if cnt > 0:
            self.icon.setText("🟢")
            self.label.setText(f"🟢 {cnt} job(s) running")
            self.label.setStyleSheet("color:#15803d; font-size:11px; font-weight:bold;")
            self.setStyleSheet("background: #f0fdf4; border:1px solid #bbf7d0; border-radius:8px;")
        else:
            # check if scheduler not found
            if "not found" in raw.lower() or "command not found" in raw.lower() or raw == "":
                self.icon.setText("⚪")
                self.label.setText("No scheduler (or 0 jobs)")
                self.label.setStyleSheet("color:#64748b; font-size:11px;")
                self.setStyleSheet("background: #f8fafc; border:1px solid #e2e8f0; border-radius:8px;")
            else:
                self.icon.setText("🔵")
                self.label.setText("0 jobs running")
                self.label.setStyleSheet("color:#0284c7; font-size:11px;")
                self.setStyleSheet("background: #f0f9ff; border:1px solid #bae6fd; border-radius:8px;")
        self.setToolTip(raw if raw else "squeue/qstat output")

    def on_error(self, msg):
        self.icon.setText("⚠️")
        self.label.setText(f"Error: {msg[:30]}")
