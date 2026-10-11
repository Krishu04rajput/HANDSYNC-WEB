# HANDSYNC — Direct Manual Servo Control

Camera-free Windows desktop controller for an ESP32 + PCA9685 single robotic arm. Controls six PCA9685 channels over the ESP32's Wi-Fi access point.

## Features
- Six independent angle sliders and numeric controls: Base, Shoulder, Arm/Elbow, Wrist, Gripper, Finger.
- Debounced synchronized six-angle target updates to `/set`.
- Home, open gripper, close gripper, resume and software stop controls.
- Save/load/delete named poses in `saved_poses.json`.
- Live connection and ESP32 angle status.
- No camera, MediaPipe, Bluetooth, or COM port needed during normal use.

## Files
- `main.py` — PySide6 Windows desktop app
- `HANDSYNC_ESP32.ino` — ESP32 Arduino firmware
- `requirements.txt` — Python dependencies
- `saved_poses.json` — created automatically when you save a pose

## A. Upload ESP32 firmware
1. Install Arduino IDE.
2. In **Tools → Board → Boards Manager**, install **esp32 by Espressif Systems** if needed.
3. In **Sketch → Include Library → Manage Libraries**, install **Adafruit PWM Servo Driver Library** (allow dependency installation).
4. Open `HANDSYNC_ESP32.ino`.
5. Select the actual ESP32 board and its USB COM port. This COM port is only for firmware upload/Serial Monitor.
6. Upload, then open Serial Monitor at **115200 baud**. Expected output includes `Wi-Fi SSID: HANDSYNC`, the IP `192.168.4.1`, and `HTTP server ready`.

## B. Wire the controller
- ESP32 GPIO 21 SDA → PCA9685 SDA
- ESP32 GPIO 22 SCL → PCA9685 SCL
- ESP32 3V3 → PCA9685 logic VCC (confirm your module's logic requirements)
- ESP32 GND → PCA9685 GND
- External regulated 5–6 V servo supply positive → PCA9685 V+ terminal
- External servo supply negative → PCA9685 GND; common ground with ESP32 is essential
- Servo signal leads to PCA9685 channels 0–5 in this order: Base, Shoulder, Arm/Elbow, Wrist, Gripper, Finger

**Do not power six servos from the ESP32 5V/3V3 pins.** Size the external supply for the combined stall current of your servos. Start with the arm unloaded and physically clear of obstacles. Confirm the PCA9685 V+ polarity before powering it.

## C. Install and run on Windows PowerShell
Open PowerShell in this extracted folder (the folder containing `main.py`), then run:

```powershell
py --list
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

Python 3.10–3.12 (64-bit) should work with these dependencies; Python 3.11 is recommended. If `py -3.11` is unavailable, install Python 3.11 x64, then retry. If you see `No module named PySide6` or `requests`, ensure `(.venv)` appears in your prompt and rerun `pip install -r requirements.txt`.

## D. Connect and use
1. Power the ESP32 and PCA9685 logic. Ensure servo power is wired correctly.
2. On Windows, connect Wi-Fi to **HANDSYNC**, password **12345678**. Windows may say “No internet”; stay connected.
3. In a browser open `http://192.168.4.1/status`. It should return JSON with `connected`, `pca9685`, `stopped`, and servo angle fields.
4. Run `python main.py`, use IP `192.168.4.1`, and click **CONNECT / CHECK**.
5. Move one slider slightly and confirm only the expected joint moves. The app sends all six target angles together. Firmware eases the servos toward targets at 24 degrees/second.
6. Save poses from the current slider values. Saved poses remain in `saved_poses.json` beside the app.

## API endpoints
- `GET /status` — JSON connection and angle status
- `GET /set?ch0=90&ch1=90&ch2=90&ch3=90&ch4=30&ch5=30` — synchronized targets
- `GET /move?servo=0&angle=90` — single-channel test (0–5)
- `GET /home`, `/open`, `/close`, `/stop`, `/resume`

## Troubleshooting
### Browser `/status` times out
- Reconnect to `HANDSYNC`; do not use the home Wi-Fi simultaneously if Windows switches away from the ESP32 network.
- Check Serial Monitor for the IP address and `HTTP server ready`.
- Temporarily disconnect VPNs and allow Python through Windows Defender Firewall on private networks.
- Test `ipconfig` and verify the Wi-Fi adapter has an address on the ESP32 subnet. The ESP32 AP default is `192.168.4.1`.

### App says connection failed
- First confirm the status URL works in a browser on the same PC.
- Enter the IP printed by Serial Monitor into the app.
- Run `python -m pip show requests PySide6` in the activated `.venv`.

### PCA9685 reports false / servos don't move
- Check SDA=21, SCL=22, PCA9685 address jumper (default 0x40), logic VCC and common GND.
- Check external servo supply, polarity, current capacity and servo signal channel mapping.
- Don't connect/disconnect servos with power on. Test one servo at a time with mechanical links unloaded.

### Servo direction or travel is wrong
- The sketch uses shared pulse ticks 110–510 and conservative per-channel angle limits as starting values, not universal calibration. Different servos may require different pulse limits. Adjust `SERVO_MIN_TICK`, `SERVO_MAX_TICK`, and per-channel `minAngle`/`maxAngle` only after testing. Reverse a joint's angle mapping in firmware if its mounting direction is opposite. Never force a servo against a hard stop.

### Emergency Stop behavior
- `/stop` freezes commanded target positions in software. It is **not** a physical emergency-stop or servo power disconnect; the servo may continue holding torque. Keep a suitable physical power cut switch accessible.

### Port/COM issues
- A COM port is needed by Arduino IDE to flash the firmware and use Serial Monitor, not by this desktop app. Close Serial Monitor if another program needs the same COM port. For Wi-Fi control, use `http://192.168.4.1/status` and leave the ESP32 powered.

## Safety notes
- Initial servo angles and pulse widths are not guaranteed safe for your specific build.
- Secure the arm, remove loads, keep fingers clear of pinch points, and test slowly.
- A Wi-Fi link can drop. Do not rely on the software stop as a safety-rated function.
