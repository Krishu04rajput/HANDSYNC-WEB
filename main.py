import sys
import json
from pathlib import Path
from datetime import datetime

import requests
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QSlider, QSpinBox, QLineEdit,
    QGroupBox, QMessageBox, QListWidget, QListWidgetItem, QInputDialog,
    QSplitter, QFrame
)

APP_DIR = Path(__file__).resolve().parent
POSES_FILE = APP_DIR / "saved_poses.json"
SERVO_NAMES = ["Base", "Shoulder", "Arm / Elbow", "Wrist", "Gripper", "Finger"]
DEFAULT_ANGLES = [90, 90, 90, 90, 30, 30]
DEFAULT_HOST = "192.168.4.1"

STYLE = """
QMainWindow, QWidget { background: #0b1220; color: #e5eefb; font-family: Segoe UI, Arial; font-size: 10pt; }
QGroupBox { border: 1px solid #26354c; border-radius: 12px; margin-top: 12px; padding: 14px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #67e8f9; }
QLabel#muted { color: #9aaec7; }
QLabel#angle { color: #67e8f9; font-size: 17pt; font-weight: 700; min-width: 50px; }
QPushButton { background: #123047; border: 1px solid #23506a; border-radius: 8px; padding: 9px 12px; color: #e9faff; font-weight: 600; }
QPushButton:hover { background: #16445d; }
QPushButton:disabled { background: #1c2938; color: #6b7a8e; border-color: #293647; }
QPushButton#primary { background: #0891b2; border-color: #06b6d4; color: white; }
QPushButton#danger { background: #991b1b; border-color: #ef4444; color: white; }
QPushButton#safe { background: #14532d; border-color: #22c55e; }
QLineEdit, QSpinBox, QListWidget { background: #111d2e; border: 1px solid #30425b; border-radius: 7px; padding: 7px; color: #edf6ff; }
QSlider::groove:horizontal { height: 6px; background: #29394e; border-radius: 3px; }
QSlider::sub-page:horizontal { background: #06b6d4; border-radius: 3px; }
QSlider::handle:horizontal { background: #a5f3fc; width: 16px; margin: -6px 0; border-radius: 8px; }
QFrame#statusDot { background: #f59e0b; border-radius: 6px; }
"""

class NetworkWorker(QObject):
    status_result = Signal(dict)
    command_result = Signal(bool, str)
    connected_result = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.host = DEFAULT_HOST
        self.session = requests.Session()

    def base_url(self):
        host = self.host.strip().replace("http://", "").replace("https://", "").strip(" /")
        return f"http://{host}"

    @Slot(str)
    def set_host(self, host):
        self.host = host.strip()
        self.check_status()

    @Slot()
    def check_status(self):
        try:
            response = self.session.get(self.base_url() + "/status", timeout=2.0)
            response.raise_for_status()
            data = response.json()
            self.status_result.emit(data)
            self.connected_result.emit(True, f"Connected · {self.base_url()}")
        except Exception as exc:
            self.connected_result.emit(False, f"Not connected · {exc}")

    @Slot(list)
    def send_angles(self, angles):
        try:
            params = {f"ch{i}": int(a) for i, a in enumerate(angles)}
            response = self.session.get(self.base_url() + "/set", params=params, timeout=2.5)
            if response.status_code == 423:
                self.command_result.emit(False, "ESP32 is STOPPED. Press RESUME before moving.")
                return
            response.raise_for_status()
            self.command_result.emit(True, "Six servo targets sent")
        except Exception as exc:
            self.command_result.emit(False, f"Command failed: {exc}")

    @Slot(str)
    def command(self, endpoint):
        try:
            response = self.session.get(self.base_url() + "/" + endpoint, timeout=2.5)
            response.raise_for_status()
            self.command_result.emit(True, response.text.strip() or f"/{endpoint} OK")
            if endpoint in ("home", "open", "close", "resume", "stop"):
                self.check_status()
        except Exception as exc:
            self.command_result.emit(False, f"/{endpoint} failed: {exc}")

class ServoCard(QGroupBox):
    changed = Signal(int, int)

    def __init__(self, index, name, initial):
        super().__init__(f"CH {index} · {name}")
        self.index = index
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 180)
        self.slider.setValue(initial)
        self.spin = QSpinBox()
        self.spin.setRange(0, 180)
        self.spin.setSuffix("°")
        self.spin.setValue(initial)
        self.angle = QLabel(f"{initial}°")
        self.angle.setObjectName("angle")
        self.angle.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top = QHBoxLayout()
        top.addWidget(QLabel("Target angle"))
        top.addStretch(1)
        top.addWidget(self.angle)
        controls = QHBoxLayout()
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.spin)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(controls)
        self.slider.valueChanged.connect(self.spin.setValue)
        self.spin.valueChanged.connect(self.slider.setValue)
        self.slider.valueChanged.connect(self.on_value)

    @Slot(int)
    def on_value(self, value):
        self.angle.setText(f"{value}°")
        self.changed.emit(self.index, value)

    def value(self):
        return self.slider.value()

    def set_value(self, value):
        self.slider.setValue(max(0, min(180, int(value))))

class MainWindow(QMainWindow):
    send_requested = Signal(list)
    command_requested = Signal(str)
    status_requested = Signal()
    host_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("HANDSYNC · Direct Servo Control")
        self.resize(1120, 820)
        self.angles = DEFAULT_ANGLES.copy()
        self.pending_send = False
        self.last_status = {}
        self.cards = []

        self.thread = QThread(self)
        self.worker = NetworkWorker()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.check_status)
        self.host_requested.connect(self.worker.set_host)
        self.send_requested.connect(self.worker.send_angles)
        self.command_requested.connect(self.worker.command)
        self.status_requested.connect(self.worker.check_status)
        self.worker.status_result.connect(self.on_status)
        self.worker.connected_result.connect(self.on_connection)
        self.worker.command_result.connect(self.on_command_result)
        self.thread.start()

        self.send_timer = QTimer(self)
        self.send_timer.setSingleShot(True)
        self.send_timer.setInterval(100)
        self.send_timer.timeout.connect(self.flush_angles)
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(1800)
        self.poll_timer.timeout.connect(self.status_requested.emit)
        self.poll_timer.start()

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)

        header = QHBoxLayout()
        title_col = QVBoxLayout()
        title = QLabel("HANDSYNC")
        title.setFont(QFont("Segoe UI", 23, QFont.Weight.Bold))
        title.setStyleSheet("color:#67e8f9; letter-spacing:2px")
        subtitle = QLabel("DIRECT MANUAL CONTROL  /  SIX-AXIS SERVO ARM")
        subtitle.setObjectName("muted")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col, 1)
        self.status_dot = QFrame()
        self.status_dot.setObjectName("statusDot")
        self.status_dot.setFixedSize(12, 12)
        self.status_label = QLabel("Checking ESP32…")
        self.status_label.setObjectName("muted")
        header.addWidget(self.status_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(header)

        conn = QGroupBox("ESP32 CONNECTION")
        connrow = QHBoxLayout(conn)
        connrow.addWidget(QLabel("ESP32 IP"))
        self.host_input = QLineEdit(DEFAULT_HOST)
        self.host_input.setMaximumWidth(210)
        self.host_input.setPlaceholderText("192.168.4.1")
        connrow.addWidget(self.host_input)
        self.connect_btn = QPushButton("CONNECT / CHECK")
        self.connect_btn.setObjectName("primary")
        self.connect_btn.clicked.connect(self.connect_esp)
        connrow.addWidget(self.connect_btn)
        self.network_hint = QLabel("Join Wi-Fi HANDSYNC · password 12345678")
        self.network_hint.setObjectName("muted")
        connrow.addWidget(self.network_hint, 1)
        root.addWidget(conn)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        servo_panel = QWidget()
        servo_layout = QVBoxLayout(servo_panel)
        servo_layout.setContentsMargins(0, 0, 0, 0)
        servo_layout.setSpacing(10)
        grid = QGridLayout()
        grid.setSpacing(12)
        for i, name in enumerate(SERVO_NAMES):
            card = ServoCard(i, name, self.angles[i])
            card.changed.connect(self.on_servo_changed)
            self.cards.append(card)
            grid.addWidget(card, i // 2, i % 2)
        servo_layout.addLayout(grid)
        self.actual_label = QLabel("ESP32 reported angles: waiting for status…")
        self.actual_label.setObjectName("muted")
        servo_layout.addWidget(self.actual_label)
        splitter.addWidget(servo_panel)

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        action_box = QGroupBox("QUICK ACTIONS")
        actions = QVBoxLayout(action_box)
        for label, endpoint, obj in [
            ("⌂  HOME POSITION", "home", "primary"),
            ("OPEN GRIPPER + FINGER", "open", ""),
            ("CLOSE GRIPPER + FINGER", "close", ""),
            ("RESUME MOTION", "resume", "safe"),
            ("■  EMERGENCY STOP", "stop", "danger"),
        ]:
            btn = QPushButton(label)
            if obj:
                btn.setObjectName(obj)
            btn.clicked.connect(lambda checked=False, ep=endpoint: self.run_command(ep))
            actions.addWidget(btn)
        side_layout.addWidget(action_box)

        pose_box = QGroupBox("SAVED POSES")
        pose_layout = QVBoxLayout(pose_box)
        self.pose_list = QListWidget()
        pose_layout.addWidget(self.pose_list)
        pose_buttons = QHBoxLayout()
        save_btn = QPushButton("SAVE CURRENT")
        load_btn = QPushButton("LOAD SELECTED")
        delete_btn = QPushButton("DELETE")
        save_btn.clicked.connect(self.save_pose)
        load_btn.clicked.connect(self.load_pose)
        delete_btn.clicked.connect(self.delete_pose)
        pose_buttons.addWidget(save_btn)
        pose_buttons.addWidget(load_btn)
        pose_layout.addLayout(pose_buttons)
        pose_layout.addWidget(delete_btn)
        side_layout.addWidget(pose_box, 1)
        splitter.addWidget(side)
        splitter.setSizes([760, 310])
        root.addWidget(splitter, 1)

        footer = QHBoxLayout()
        self.message = QLabel("Ready. Test each joint carefully with the arm clear of obstructions.")
        self.message.setObjectName("muted")
        footer.addWidget(self.message, 1)
        self.send_now_btn = QPushButton("SEND ALL ANGLES")
        self.send_now_btn.setObjectName("primary")
        self.send_now_btn.clicked.connect(self.flush_angles)
        footer.addWidget(self.send_now_btn)
        root.addLayout(footer)
        self.load_poses()

    def connect_esp(self):
        host = self.host_input.text().strip()
        if not host:
            QMessageBox.warning(self, "Missing IP", "Enter the ESP32 IP address, usually 192.168.4.1.")
            return
        self.host_requested.emit(host)
        self.message.setText("Checking ESP32 connection…")

    @Slot(int, int)
    def on_servo_changed(self, index, value):
        self.angles[index] = value
        self.send_timer.start()

    @Slot()
    def flush_angles(self):
        self.send_timer.stop()
        self.send_requested.emit(self.angles.copy())

    def run_command(self, endpoint):
        if endpoint == "stop":
            self.send_timer.stop()
        self.command_requested.emit(endpoint)

    @Slot(dict)
    def on_status(self, data):
        self.last_status = data
        if data.get("stopped"):
            self.message.setText("ESP32 motion is STOPPED. Press RESUME before sending movements.")
        values = []
        for i, key in enumerate(["base", "shoulder", "arm", "wrist", "gripper", "finger"]):
            if key in data:
                values.append(f"{SERVO_NAMES[i]}: {data[key]}°")
        self.actual_label.setText("ESP32 reported angles: " + ("   ·   ".join(values) if values else "no servo values returned"))
        if data.get("pca9685") is False:
            self.message.setText("WARNING: ESP32 cannot detect PCA9685. Check I²C wiring and power.")

    @Slot(bool, str)
    def on_connection(self, ok, message):
        self.status_dot.setStyleSheet("background:#22c55e;border-radius:6px" if ok else "background:#ef4444;border-radius:6px")
        self.status_label.setText(message if len(message) < 58 else ("Connected · " + self.host_input.text() if ok else "Connection failed — check Wi-Fi/IP"))
        if ok:
            self.message.setText("Connected. Slider changes send all six target angles together.")
        else:
            self.message.setText("Connection failed. Join HANDSYNC Wi-Fi and check http://192.168.4.1/status.")

    @Slot(bool, str)
    def on_command_result(self, ok, message):
        self.message.setText(("✓ " if ok else "⚠ ") + message)
        if not ok and "STOPPED" in message:
            self.status_label.setText("ESP32 STOPPED")
            self.status_dot.setStyleSheet("background:#ef4444;border-radius:6px")

    def load_poses(self):
        self.pose_list.clear()
        try:
            data = json.loads(POSES_FILE.read_text(encoding="utf-8")) if POSES_FILE.exists() else []
            for pose in data:
                item = QListWidgetItem(pose["name"])
                item.setData(Qt.ItemDataRole.UserRole, pose)
                self.pose_list.addItem(item)
        except Exception as exc:
            self.message.setText(f"Could not read saved_poses.json: {exc}")

    def save_poses_to_disk(self):
        poses = []
        for i in range(self.pose_list.count()):
            pose = self.pose_list.item(i).data(Qt.ItemDataRole.UserRole)
            if pose:
                poses.append(pose)
        POSES_FILE.write_text(json.dumps(poses, indent=2), encoding="utf-8")

    def save_pose(self):
        name, ok = QInputDialog.getText(self, "Save pose", "Pose name:")
        if not ok or not name.strip():
            return
        pose = {"name": name.strip(), "angles": self.angles.copy(), "saved_at": datetime.now().isoformat(timespec="seconds")}
        item = QListWidgetItem(pose["name"])
        item.setData(Qt.ItemDataRole.UserRole, pose)
        self.pose_list.addItem(item)
        self.save_poses_to_disk()
        self.message.setText(f"Saved pose: {pose['name']}")

    def load_pose(self):
        item = self.pose_list.currentItem()
        if not item:
            QMessageBox.information(self, "Select a pose", "Choose a saved pose first.")
            return
        pose = item.data(Qt.ItemDataRole.UserRole)
        angles = pose.get("angles", DEFAULT_ANGLES)
        for i, card in enumerate(self.cards):
            card.set_value(angles[i])
        self.angles = [int(a) for a in angles]
        self.flush_angles()
        self.message.setText(f"Pose target loaded: {pose['name']}")

    def delete_pose(self):
        row = self.pose_list.currentRow()
        if row < 0:
            return
        self.pose_list.takeItem(row)
        self.save_poses_to_disk()

    def closeEvent(self, event):
        self.poll_timer.stop()
        self.send_timer.stop()
        self.thread.quit()
        self.thread.wait(1800)
        super().closeEvent(event)

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
