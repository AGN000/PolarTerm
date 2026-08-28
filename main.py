#!/usr/bin/env python3
import sys
import os
import traceback
import logging
# --- stability env before Qt import ---
# Force XCB on X11 (fixes Wayland/anaconda Qt mismatch), disable problematic IM
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
os.environ["QT_IM_MODULE"] = os.environ.get("QT_IM_MODULE", "")
# Ensure project root in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# logging to file for diagnosis of "unstable"
LOG_FILE = "/tmp/polarterm.log"
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
def log_except(exctype, value, tb):
    logging.error("Uncaught exception", exc_info=(exctype, value, tb))
    traceback.print_exception(exctype, value, tb)
    # also print to stderr
    sys.stderr.write("".join(traceback.format_exception(exctype, value, tb)))

sys.excepthook = log_except

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt
from gui.main_window import MainWindow

def main():
    logging.info("Starting PolarTerm")
    # High DPI handling
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except: pass

    app = QApplication(sys.argv)
    app.setApplicationName("PolarTerm")
    app.setOrganizationName("PolarTerm")
    app.setStyle("Fusion")
    # Prevent quit when last window closed accidentally? Keep stable
    app.setQuitOnLastWindowClosed(True)

    # Global exception handling inside Qt event loop
    def handle_qt_exception(*args):
        logging.error(f"Qt exception: {args}")
    try:
        w = MainWindow()
        w.show()
        logging.info("MainWindow shown")
        # raise to handle window close cleanup logging
        code = app.exec()
        logging.info(f"app.exec finished code={code}")
        sys.exit(code)
    except Exception as e:
        logging.error(f"MainWindow failed: {e}", exc_info=True)
        try:
            QMessageBox.critical(None, "PolarTerm crashed", f"{e}\n\nSee {LOG_FILE}")
        except: pass
        sys.exit(1)

if __name__ == "__main__":
    main()
