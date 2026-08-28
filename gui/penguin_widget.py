from PyQt6.QtWidgets import QWidget, QLabel, QHBoxLayout
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPropertyAnimation, QPoint, QEasingCurve, QRect
from PyQt6.QtGui import QFont
import random
import math

class PenguinIdleWidget(QWidget):
    """A little penguin that waddles across the bottom when idle. Like MobaXterm's idle animation."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)
        self.setStyleSheet("background: #e0f2fe; border-top: 1px solid #7dd3fc; border-radius: 6px;")
        self.hide()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8,2,8,2)
        self.ice = QLabel("❄")
        self.ice.setStyleSheet("font-size: 14px;")
        self.penguin = QLabel("🐧")
        self.penguin.setStyleSheet("font-size: 20px;")
        self.msg = QLabel("PolarTerm idle — penguin is patrolling... ❄")
        self.msg.setStyleSheet("color:#0c4a6e; font-size:11px; font-style: italic;")
        layout.addWidget(self.ice)
        layout.addWidget(self.penguin)
        layout.addWidget(self.msg)
        layout.addStretch()
        self.snow = QLabel("❄ ❄ ❄")
        self.snow.setStyleSheet("color:#0284c7; font-size:12px;")
        layout.addWidget(self.snow)

        self._pos = 0
        self._dir = 1
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._waddle)
        self.bob_timer = QTimer(self)
        self.bob_timer.timeout.connect(self._bob)
        self.bob_state = 0

    def start(self):
        self.show()
        self._pos = 0
        self.timer.start(120)
        self.bob_timer.start(300)

    def stop(self):
        self.hide()
        self.timer.stop()
        self.bob_timer.stop()

    def _waddle(self):
        # move penguin label slightly and flip
        self._pos += self._dir * 2
        if self._pos > 20: self._dir = -1
        if self._pos < -20: self._dir = 1
        # waddle by swapping flip?
        if random.random() < 0.05:
            self.penguin.setText("🐧" if self.penguin.text()=="🐧" else "🐧")
        # move via margin
        self.penguin.move(self.penguin.x() + self._dir, self.penguin.y())

    def _bob(self):
        self.bob_state = 1 - self.bob_state
        y = 2 if self.bob_state else 0
        self.penguin.setStyleSheet(f"font-size: 20px; margin-top: {y}px;")

class IdleMonitor(QTimer):
    activity = pyqtSignal()
    def __init__(self, parent, penguin_widget, idle_secs=18):
        super().__init__(parent)
        self.penguin = penguin_widget
        self.idle_secs = idle_secs
        self.last_activity = 0
        import time
        self._time = time
        self.last_activity = self._time.time()
        self.timeout.connect(self.check)
        self.start(3000)
        # install event filter on parent to catch activity
        parent.installEventFilter(self)

    def eventFilter(self, obj, event):
        # any key or mouse resets idle
        from PyQt6.QtCore import QEvent
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress, QEvent.Type.Wheel, QEvent.Type.MouseMove):
            self.touch()
        return False

    def touch(self):
        import time
        self.last_activity = time.time()
        if self.penguin.isVisible():
            self.penguin.stop()

    def check(self):
        import time
        if time.time() - self.last_activity > self.idle_secs:
            if not self.penguin.isVisible():
                self.penguin.start()

class FallingPenguinsOverlay(QWidget):
    """Full-window overlay with falling particles like MobaXterm easter egg. Supports penguin/rose/ice/feather on same icon."""
    # mode -> (primary emojis, secondary emojis, colors)
    THEMES = {
        "penguin": (["🐧"], ["❄"], ["#0ea5e9"]),
        "rose": (["🌹","🌸","🌷","🥀","🌺"], ["❀"," petals"], ["#f43f5e","#ec4899","#be123c"]),
        "ice": (["🧊","❄","❅","❆","💎"], ["·"], ["#7dd3fc","#0ea5e9","#e0f2fe"]),
        "feather": (["🪶","🕊️","☁️"], ["·"], ["#f8fafc","#e2e8f0","#cbd5e1"]),
        "mixed": (["🐧","🌹","🧊","🪶","❄"], ["·"], ["#0ea5e9","#f43f5e","#7dd3fc"]),
    }
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("background: rgba(224,242,254, 0.0);")
        self.hide()
        self.penguins = []  # list of (QLabel, x, y, speed, drift, rot)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.setMouseTracking(True)
        self.current_mode = "penguin"

    def mousePressEvent(self, event):
        # click anywhere to stop
        self.stop()

    def start(self, count=18, mode=None):
        if mode:
            self.current_mode = mode
        else:
            # cycle if not specified? keep current
            pass
        # theme
        primaries, secondaries, colors = self.THEMES.get(self.current_mode, self.THEMES["penguin"])
        if self.parent():
            self.setGeometry(self.parent().rect())
            self.raise_()
        self.show()
        # clear old
        for lbl, *_ in self.penguins:
            lbl.deleteLater()
        self.penguins.clear()
        w = self.width() or 1200
        # create primaries
        for i in range(count):
            emoji = random.choice(primaries)
            lbl = QLabel(emoji, self)
            sz = random.randint(22, 34) if self.current_mode=="penguin" else random.randint(18, 30)
            # color via stylesheet if needed (emoji color is fixed, but we can add glow)
            lbl.setStyleSheet(f"font-size: {sz}px; background: transparent;")
            lbl.adjustSize()
            x = random.randint(0, max(0, w-60))
            y = random.randint(-300, -30)
            speed = random.uniform(2.5, 6.5) if self.current_mode=="penguin" else random.uniform(1.8, 5.0)
            drift = random.uniform(-1.2, 1.2)
            lbl.move(int(x), int(y))
            lbl.show()
            self.penguins.append([lbl, float(x), float(y), speed, drift, 0])
        # secondaries
        sec_count = 12 if self.current_mode=="penguin" else 10
        for i in range(sec_count):
            emoji = random.choice(secondaries) if secondaries[0]!="·" else "·"
            if emoji == "·":
                emoji = random.choice(["·","•","❄"]) if self.current_mode in ("ice","feather") else "❄"
            lbl = QLabel(emoji, self)
            sz = random.randint(14, 20)
            col = random.choice(colors) if colors else "#7dd3fc"
            lbl.setStyleSheet(f"font-size: {sz}px; color: {col}; background: transparent;")
            lbl.adjustSize()
            x = random.randint(0, max(0, w-40))
            y = random.randint(-400, -20)
            speed = random.uniform(1.5, 4.0)
            drift = random.uniform(-0.6, 0.6)
            lbl.move(int(x), int(y))
            lbl.show()
            self.penguins.append([lbl, float(x), float(y), speed, drift, 0])
        self.timer.start(32)  # ~30fps

    def stop(self):
        self.timer.stop()
        self.hide()
        for lbl, *_ in self.penguins:
            lbl.deleteLater()
        self.penguins.clear()

    def resizeEvent(self, event):
        # keep overlay full parent
        if self.parent():
            self.setGeometry(self.parent().rect())
        super().resizeEvent(event)

    def _tick(self):
        h = self.height()
        w = self.width()
        alive = []
        for item in self.penguins:
            lbl, x, y, speed, drift, rot = item
            y += speed
            x += drift + random.uniform(-0.3, 0.3)
            # gentle sway
            x += math.sin(y*0.02) * 0.6
            if y > h + 40:
                # recycle to top
                y = random.randint(-120, -30)
                x = random.randint(0, max(0, w-60))
            lbl.move(int(x), int(y))
            item[1], item[2] = x, y
            alive.append(item)
        self.penguins = alive

class RadioPulseWidget(QWidget):
    """Nice radio pulse animation when icon clicked — expanding circles like a radio button."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.hide()
        self._radius = 0
        self._opacity = 1.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._animate)
        self.center = QPoint(0,0)
        self.max_radius = 60
        self.step = 0

    def pulse_at(self, global_pos, parent_widget):
        # map global to parent
        if parent_widget:
            self.setParent(parent_widget)
            self.setGeometry(parent_widget.rect())
            self.raise_()
            local = parent_widget.mapFromGlobal(global_pos)
            self.center = local
        else:
            self.center = QPoint(self.width()//2, self.height()//2)
        self._radius = 10
        self._opacity = 0.9
        self.step = 0
        self.show()
        self.timer.start(16)

    def _animate(self):
        self.step += 1
        self._radius += 3.5
        self._opacity -= 0.04
        if self._radius > self.max_radius or self._opacity <= 0:
            self.timer.stop()
            self.hide()
            self._radius = 0
            self._opacity = 1.0
            self.update()
            return
        self.update()

    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QPen, QColor, QBrush
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # outer ripple
        col = QColor("#0ea5e9")
        col.setAlphaF(max(0, self._opacity*0.35))
        p.setPen(QPen(col, 2))
        p.setBrush(QBrush(QColor(0,0,0,0)))
        p.drawEllipse(self.center, int(self._radius), int(self._radius))
        # inner solid dot
        col2 = QColor("#0284c7")
        col2.setAlphaF(max(0, self._opacity))
        p.setBrush(QBrush(col2))
        p.setPen(Qt.PenStyle.NoPen)
        inner_r = max(4, int(10 - self.step*0.15))
        p.drawEllipse(self.center, inner_r, inner_r)
        # second ripple
        if self.step > 6:
            r2 = self._radius - 12
            if r2 > 10:
                col3 = QColor("#7dd3fc")
                col3.setAlphaF(max(0, (self._opacity*0.25)))
                p.setPen(QPen(col3, 1.5))
                p.setBrush(QBrush(QColor(0,0,0,0)))
                p.drawEllipse(self.center, int(r2), int(r2))
