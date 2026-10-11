#include <WiFi.h>
#include <WebServer.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <math.h>

// HANDSYNC Direct Control: ESP32 + PCA9685 + six servo channels
const char* AP_SSID = "HANDSYNC";
const char* AP_PASSWORD = "12345678";
constexpr int SDA_PIN = 21;
constexpr int SCL_PIN = 22;
constexpr uint8_t PCA_ADDRESS = 0x40;
constexpr int SERVO_COUNT = 6;
constexpr int SERVO_MIN_TICK = 110;  // calibrate to each servo/mechanism
constexpr int SERVO_MAX_TICK = 510;  // calibrate to each servo/mechanism
constexpr float MAX_SPEED_DPS = 24.0f;
constexpr unsigned long UPDATE_INTERVAL_MS = 20;

const char* SERVO_NAMES[SERVO_COUNT] = {"base", "shoulder", "arm", "wrist", "gripper", "finger"};
// Conservative starting bounds; physically verify before full assembly use.
int minAngle[SERVO_COUNT] = {10, 20, 20, 10, 10, 10};
int maxAngle[SERVO_COUNT] = {170, 160, 160, 170, 170, 170};
float currentAngle[SERVO_COUNT] = {90, 90, 90, 90, 30, 30};
int targetAngle[SERVO_COUNT] = {90, 90, 90, 90, 30, 30};

Adafruit_PWMServoDriver pwm(PCA_ADDRESS);
WebServer server(80);
bool pcaReady = false;
bool emergencyStopped = false;
unsigned long lastServoUpdate = 0;

int angleToTick(int angle) {
  angle = constrain(angle, 0, 180);
  return map(angle, 0, 180, SERVO_MIN_TICK, SERVO_MAX_TICK);
}
void writeServo(int channel, int angle) {
  if (!pcaReady || channel < 0 || channel >= SERVO_COUNT) return;
  angle = constrain(angle, minAngle[channel], maxAngle[channel]);
  pwm.setPWM(channel, 0, angleToTick(angle));
}
void setTarget(int channel, int angle) {
  if (channel < 0 || channel >= SERVO_COUNT) return;
  targetAngle[channel] = constrain(angle, minAngle[channel], maxAngle[channel]);
}
void updateServos() {
  const unsigned long now = millis();
  if (now - lastServoUpdate < UPDATE_INTERVAL_MS) return;
  float dt = (now - lastServoUpdate) / 1000.0f;
  lastServoUpdate = now;
  if (dt > 0.08f) dt = 0.08f;
  const float maxStep = MAX_SPEED_DPS * dt;
  for (int i = 0; i < SERVO_COUNT; ++i) {
    const float diff = targetAngle[i] - currentAngle[i];
    if (diff > maxStep) currentAngle[i] += maxStep;
    else if (diff < -maxStep) currentAngle[i] -= maxStep;
    else currentAngle[i] = targetAngle[i];
    writeServo(i, (int)roundf(currentAngle[i]));
  }
}
String statusJson() {
  String s = "{\"connected\":true,\"pca9685\":";
  s += pcaReady ? "true" : "false";
  s += ",\"stopped\":";
  s += emergencyStopped ? "true" : "false";
  for (int i = 0; i < SERVO_COUNT; ++i) {
    s += ",\""; s += SERVO_NAMES[i]; s += "\":";
    s += String((int)roundf(currentAngle[i]));
  }
  s += "}";
  return s;
}
void handleRoot() {
  const char html[] PROGMEM = R"HTML(<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>HANDSYNC</title><style>body{font-family:Arial;background:#101827;color:#eef4ff;max-width:680px;margin:24px auto;padding:16px}button{padding:12px;margin:4px;border:0;border-radius:8px;background:#0891b2;color:white;font-weight:bold}.card{background:#1e293b;padding:14px;margin:12px 0;border-radius:12px}pre{white-space:pre-wrap}</style></head><body><h1>HANDSYNC ARM</h1><p>ESP32 direct Wi-Fi controller</p><div class="card"><button onclick="fetch('/home')">HOME</button><button onclick="fetch('/open')">OPEN</button><button onclick="fetch('/close')">CLOSE</button><button onclick="fetch('/resume')">RESUME</button><button onclick="fetch('/stop')">STOP</button></div><div class="card"><h3>Status</h3><pre id="s">Loading…</pre></div><script>async function r(){try{let x=await fetch('/status');document.getElementById('s').textContent=JSON.stringify(await x.json(),null,2)}catch(e){document.getElementById('s').textContent=e}}setInterval(r,1000);r()</script></body></html>)HTML";
  server.send(200, "text/html", html);
}
void handleStatus() { server.send(200, "application/json", statusJson()); }
void handleSet() {
  if (emergencyStopped) { server.send(423, "text/plain", "STOPPED: call /resume first"); return; }
  bool found = false;
  // Validate all supplied channels before changing any target.
  int proposed[SERVO_COUNT]; bool supplied[SERVO_COUNT] = {false, false, false, false, false, false};
  for (int i = 0; i < SERVO_COUNT; ++i) proposed[i] = targetAngle[i];
  for (int i = 0; i < SERVO_COUNT; ++i) {
    String key = "ch" + String(i);
    if (!server.hasArg(key)) continue;
    String value = server.arg(key);
    if (value.length() == 0) { server.send(400, "text/plain", "Empty angle parameter"); return; }
    for (unsigned int j = 0; j < value.length(); ++j) {
      if (!isDigit(value[j])) { server.send(400, "text/plain", "Angles must be integers"); return; }
    }
    int angle = value.toInt();
    if (angle < 0 || angle > 180) { server.send(400, "text/plain", "Angles must be 0-180"); return; }
    proposed[i] = angle; supplied[i] = true; found = true;
  }
  if (!found) { server.send(400, "text/plain", "Supply ch0 through ch5"); return; }
  for (int i = 0; i < SERVO_COUNT; ++i) if (supplied[i]) setTarget(i, proposed[i]);
  server.send(200, "text/plain", "Six-servo targets accepted");
}
void handleMove() {
  if (emergencyStopped) { server.send(423, "text/plain", "STOPPED: call /resume first"); return; }
  if (!server.hasArg("servo") || !server.hasArg("angle")) { server.send(400, "text/plain", "Missing servo or angle"); return; }
  String cs = server.arg("servo"), as = server.arg("angle");
  if (!cs.length() || !as.length()) { server.send(400, "text/plain", "Empty parameter"); return; }
  for (unsigned int i=0; i<cs.length(); ++i) if (!isDigit(cs[i])) { server.send(400, "text/plain", "Invalid servo"); return; }
  for (unsigned int i=0; i<as.length(); ++i) if (!isDigit(as[i])) { server.send(400, "text/plain", "Invalid angle"); return; }
  int ch = cs.toInt(), angle = as.toInt();
  if (ch < 0 || ch >= SERVO_COUNT || angle < 0 || angle > 180) { server.send(400, "text/plain", "servo 0-5; angle 0-180"); return; }
  setTarget(ch, angle); server.send(200, "text/plain", "Target accepted");
}
void handleHome() {
  if (emergencyStopped) { server.send(423, "text/plain", "STOPPED: call /resume first"); return; }
  for (int i=0; i<SERVO_COUNT; ++i) setTarget(i, i >= 4 ? 30 : 90);
  server.send(200, "text/plain", "Home targets accepted");
}
void handleOpen() {
  if (emergencyStopped) { server.send(423, "text/plain", "STOPPED: call /resume first"); return; }
  setTarget(4, 110); setTarget(5, 110); server.send(200, "text/plain", "Open targets accepted");
}
void handleClose() {
  if (emergencyStopped) { server.send(423, "text/plain", "STOPPED: call /resume first"); return; }
  setTarget(4, 35); setTarget(5, 35); server.send(200, "text/plain", "Close targets accepted");
}
void handleStop() {
  emergencyStopped = true;
  for (int i=0; i<SERVO_COUNT; ++i) targetAngle[i] = (int)roundf(currentAngle[i]);
  server.send(200, "text/plain", "STOPPED: targets frozen; this is not a physical power cut");
}
void handleResume() { emergencyStopped = false; server.send(200, "text/plain", "Resumed; waiting for commands"); }
void setup() {
  Serial.begin(115200); delay(400); Serial.println("\n=== HANDSYNC DIRECT CONTROL ===");
  Wire.begin(SDA_PIN, SCL_PIN);
  pcaReady = pwm.begin();
  if (pcaReady) {
    pwm.setOscillatorFrequency(27000000); pwm.setPWMFreq(50); delay(250);
    for (int i=0; i<SERVO_COUNT; ++i) writeServo(i, (int)currentAngle[i]);
    Serial.println("PCA9685 detected at 0x40");
  } else Serial.println("ERROR: PCA9685 not detected; check SDA/SCL and logic power");
  WiFi.mode(WIFI_AP); WiFi.setSleep(false);
  if (!WiFi.softAP(AP_SSID, AP_PASSWORD)) Serial.println("ERROR: Wi-Fi access point failed");
  Serial.print("Wi-Fi SSID: "); Serial.println(AP_SSID);
  Serial.print("Password: "); Serial.println(AP_PASSWORD);
  Serial.print("Controller URL: http://"); Serial.println(WiFi.softAPIP());
  server.on("/", HTTP_GET, handleRoot); server.on("/status", HTTP_GET, handleStatus);
  server.on("/set", HTTP_GET, handleSet); server.on("/move", HTTP_GET, handleMove);
  server.on("/home", HTTP_GET, handleHome); server.on("/open", HTTP_GET, handleOpen);
  server.on("/close", HTTP_GET, handleClose); server.on("/stop", HTTP_GET, handleStop);
  server.on("/resume", HTTP_GET, handleResume); server.begin();
  lastServoUpdate = millis(); Serial.println("HTTP server ready on port 80");
}
void loop() {
  server.handleClient();
  if (!emergencyStopped) updateServos();
  delay(1);
}
