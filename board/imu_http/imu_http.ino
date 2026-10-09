// ============================================================
//  ESP32-S3-EYE 板载 QMA7981 加速度计 → WiFi HTTP 上传
//  对应周任务卡:真实传感源、单位与时间、来源组号、失败状态
//
//  硬件:ESP32-S3-EYE 板载 QMA7981(三轴加速度计)
//        I2C: SDA=GPIO4  SCL=GPIO5  地址=0x12
//        注意:S3-EYE 无外部上拉电阻,必须启用芯片内部上拉
//  寄存器依据:QST《QMA7981 Datasheet Rev.A》
// ============================================================
#include "config.h"          // 必须最先包含:USE_QMA7981 宏在这里定义
#include <WiFi.h>
#include <HTTPClient.h>
#if USE_QMA7981
  #include <Wire.h>
#endif
#include <ArduinoJson.h>

// ---------- QMA7981 定义 ----------
static const uint8_t QMA_ADDR    = 0x12;   // 7 位 I2C 地址
static const int     I2C_SDA     = 4;      // S3-EYE 板载 I2C
static const int     I2C_SCL     = 5;
static const uint8_t REG_CHIP_ID = 0x00;   // CHIP_ID(默认值由 NVM 决定)
static const uint8_t REG_X_LSB   = 0x01;   // 0x01~0x06 三轴数据
static const uint8_t REG_FSR     = 0x0F;   // 量程
static const uint8_t REG_PM      = 0x11;   // 电源模式

// ±8g 量程 → 标称 1024 LSB/g(手册值,实际会用重力校准覆盖)
static const float   LSB_PER_G   = 1024.0f;
// 校准后的真实灵敏度(LSB/g),由 qma_calibrate() 用重力测定
static float         g_lsb_per_g = LSB_PER_G;
static const float   G_TO_MS2    = 9.80665f;

bool sensor_ok = false;
uint8_t chip_id_seen = 0;

// ---------- 采样与上传控制 ----------
static const unsigned long SAMPLE_PERIOD_MS = 50;   // 50ms 采一次(20Hz)
static const unsigned long UPLOAD_PERIOD_MS = 200;  // 200ms 上传一次(5Hz),曲线更密更流畅
unsigned long last_sample_ms = 0;
unsigned long last_upload_ms = 0;
unsigned long http_fail_count = 0;

// 1s 内均值缓存(单位:g)
struct SumBuf {
  double ax = 0, ay = 0, az = 0;
  int n = 0;
} sumbuf;

// ---------- I2C 底层 ----------
#if USE_QMA7981
static bool i2c_write_reg(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(QMA_ADDR);
  Wire.write(reg);
  Wire.write(val);
  return Wire.endTransmission() == 0;
}

static bool i2c_read_regs(uint8_t reg, uint8_t *buf, size_t len) {
  Wire.beginTransmission(QMA_ADDR);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((int)QMA_ADDR, (int)len) != (int)len) return false;
  for (size_t i = 0; i < len; ++i) buf[i] = Wire.read();
  return true;
}

// 14 位二进制补码还原:MSB=ACC<13:6>, LSB=ACC<5:0> 在 bit7~bit2
static inline int16_t compose14(uint8_t lsb, uint8_t msb) {
  uint16_t u = (uint16_t)(((uint16_t)msb << 8) | ((uint16_t)lsb & 0xFC)) >> 2;
  if (u & 0x2000) return (int16_t)(u | 0xC000);  // 负数符号扩展
  return (int16_t)u;
}

bool qma_init() {
  // 【关键】S3-EYE 无外部上拉,必须开内部上拉
  pinMode(I2C_SDA, INPUT_PULLUP);
  pinMode(I2C_SCL, INPUT_PULLUP);
  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(400000);

  // 1) 读 CHIP_ID 自检
  if (!i2c_read_regs(REG_CHIP_ID, &chip_id_seen, 1)) {
    Serial.println("[QMA] I2C 无响应!检查开发板型号与引脚(应为 SDA=4/SCL=5)");
    return false;
  }
  Serial.printf("[QMA] CHIP_ID = 0x%02X (常见 0xE7;随批次变化,通信正常即可)\n", chip_id_seen);

  // 2) 设量程 ±8g
  if (!i2c_write_reg(REG_FSR, 0x04)) {
    Serial.println("[QMA] 设置量程失败");
    return false;
  }
  // 3) 退出 standby,进入 Active(上电默认 standby)
  uint8_t pm = 0;
  if (!i2c_read_regs(REG_PM, &pm, 1)) return false;
  if (!i2c_write_reg(REG_PM, pm | 0x80)) return false;

  delay(20);  // 唤醒约 1ms,留余量
  return true;
}

// 读一次三轴原始值(LSB)
static void qma_read_raw(int16_t &x, int16_t &y, int16_t &z) {
  uint8_t raw[6] = {0};
  i2c_read_regs(REG_X_LSB, raw, 6);
  x = compose14(raw[0], raw[1]);
  y = compose14(raw[2], raw[3]);
  z = compose14(raw[4], raw[5]);
}

// 读一次三轴,输出单位 g(使用校准后的灵敏度)
bool qma_read(float &ax_g, float &ay_g, float &az_g) {
  int16_t x, y, z;
  qma_read_raw(x, y, z);
  ax_g = (float)x / g_lsb_per_g;
  ay_g = (float)y / g_lsb_per_g;
  az_g = (float)z / g_lsb_per_g;
  return true;
}

// 用重力自动校准:静止时三轴模长恒等于 1g,据此反推真实灵敏度。
// 不依赖数据手册的标称值,兼容 QMA7981 / QMA6100P 等不同批次芯片。
bool qma_calibrate() {
  const int N = 60;
  double sum = 0;
  int ok = 0;
  for (int i = 0; i < N; i++) {
    int16_t x, y, z;
    qma_read_raw(x, y, z);
    double m = sqrt((double)x * x + (double)y * y + (double)z * z);
    if (m > 10) { sum += m; ok++; }
    delay(15);
  }
  if (ok < N / 2) {
    Serial.println("[QMA] 校准失败(数据异常),改用标称值 1024");
    g_lsb_per_g = 1024.0f;
    return false;
  }
  g_lsb_per_g = (float)(sum / ok);
  Serial.printf("[QMA] 重力校准完成: 1g = %.1f LSB (采样 %d 次, 标称 1024)\n",
                g_lsb_per_g, ok);
  return true;
}
#endif

// ---------- 演示模式:合成"轻微摇晃+重力"信号 ----------
static void sim_generate(float t, float &ax_g, float &ay_g, float &az_g) {
  ax_g = 0.020f * sinf(0.7f * t) + 0.003f * (((float)random(1000)) / 1000.0f - 0.5f);
  ay_g = 0.015f * cosf(0.5f * t) + 0.003f * (((float)random(1000)) / 1000.0f - 0.5f);
  az_g = 1.000f + 0.010f * sinf(1.0f * t) + 0.003f * (((float)random(1000)) / 1000.0f - 0.5f);
}

// ---------- WiFi ----------
void wifi_connect() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.printf("[WiFi] connecting to %s ", WIFI_SSID);
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - t0 > 20000) {
      Serial.println(" TIMEOUT, retry...");
      WiFi.disconnect();
      delay(500);
      WiFi.begin(WIFI_SSID, WIFI_PASS);
      t0 = millis();
    }
    delay(300);
    Serial.print(".");
  }
  Serial.printf("\n[WiFi] OK, IP=%s, RSSI=%d\n",
                WiFi.localIP().toString().c_str(), WiFi.RSSI());
}

bool upload_payload(const String &json_body) {
  if (WiFi.status() != WL_CONNECTED) wifi_connect();
  HTTPClient http;
  http.setTimeout(2500);          // 限制单次请求耗时,避免阻塞主循环
  http.setConnectTimeout(2000);
  String url = String("http://") + SERVER_HOST + ":" + SERVER_PORT + "/api/data";
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(json_body);
  bool ok = false;
  if (code > 0) {
    ok = (code == 200);
    if (!ok) Serial.printf("[HTTP] %d\n", code);
  } else {
    Serial.printf("[HTTP] err %s\n", http.errorToString(code).c_str());
  }
  http.end();
  return ok;
}

// req_id 非空时表示这是响应某个采集任务,数据里会带上 request_id
void build_and_upload(const char *req_id = nullptr) {
  double ax = sumbuf.n ? sumbuf.ax / sumbuf.n : 0;
  double ay = sumbuf.n ? sumbuf.ay / sumbuf.n : 0;
  double az = sumbuf.n ? sumbuf.az / sumbuf.n : 0;
  int n_in_buf = sumbuf.n;
  sumbuf = SumBuf{};

  StaticJsonDocument<512> doc;
  doc["group_id"]  = GROUP_ID;
  doc["device_id"] = DEVICE_ID;
  doc["ts_ms"]     = (uint64_t)millis();
  doc["uptime_s"]  = millis() / 1000.0;
  doc["n_samples"] = n_in_buf;
  doc["sensor"]    = "QMA7981";
  if (req_id && req_id[0]) doc["request_id"] = req_id;
#if USE_QMA7981
  doc["status"]    = sensor_ok ? "ok" : "sensor_fail";
#else
  doc["status"]    = "simulated";
  doc["mode"]      = "demo";
#endif
  // 加速度:同时给 g 和 m/s²,便于核对单位
  doc["acc_x_g"]   = ax;
  doc["acc_y_g"]   = ay;
  doc["acc_z_g"]   = az;
  doc["acc_x"]     = ax * G_TO_MS2;
  doc["acc_y"]     = ay * G_TO_MS2;
  doc["acc_z"]     = az * G_TO_MS2;
  doc["rssi"]      = WiFi.RSSI();

  String body;
  serializeJson(doc, body);

  // 单次 HTTP 往返耗时(用于诊断上传是否成为瓶颈)
  unsigned long t_http = millis();
  if (!upload_payload(body)) http_fail_count++;
  t_http = millis() - t_http;

  // 日志节流:每秒最多打印 1 行。
  // 既保留可观测性(能看出真实上传频率),又避免大量 Serial 写入拖慢主循环。
  static unsigned long last_log_ms = 0;
  static int up_since_log = 0;
  static unsigned long last_http_ms = 0;
  up_since_log++;
  last_http_ms = t_http;
  if (millis() - last_log_ms >= 1000) {
    Serial.printf("[UP] %d 条/秒  http=%lums  n=%d  acc=(%.3f, %.3f, %.3f) g\n",
                  up_since_log, last_http_ms, n_in_buf, ax, ay, az);
    last_log_ms = millis();
    up_since_log = 0;
  }
}

// ============================================================
//  第 2 周:命令通道(Web 远程采集指令)
// ============================================================
static bool periodic_paused = false;   // 暂停周期上报(命令通道保持)
static unsigned long last_cmd_poll_ms = 0;
// 命令轮询间隔:太短会频繁阻塞主循环(每次 HTTP 约数百 ms),影响 5Hz 上传
// 命令轮询周期。实测 2s 时"采集一次"端到端要 7~8s 才完成,
// 缩到 1s 可把等待领取的时间减半(配合 20Hz 采样 + 5Hz 上传的周期上报)
static const unsigned long CMD_POLL_PERIOD_MS = 1000;

// 立即采一次并上传(带 request_id)
static void sample_now_and_upload(const char *req_id) {
  sumbuf = SumBuf{};
#if USE_QMA7981
  for (int i = 0; i < 5; i++) {
    float ax, ay, az;
    if (qma_read(ax, ay, az)) {
      sumbuf.ax += ax; sumbuf.ay += ay; sumbuf.az += az; sumbuf.n++;
      sensor_ok = true;
    }
    delay(20);
  }
#else
  float ax, ay, az;
  sim_generate(millis() / 1000.0f, ax, ay, az);
  sumbuf.ax += ax; sumbuf.ay += ay; sumbuf.az += az; sumbuf.n = 1;
#endif
  build_and_upload(req_id);
}

// 回执:告诉服务器"我收到了"或"执行失败"
static void send_ack(const char *req_id, const char *stage, const char *note = "") {
  StaticJsonDocument<256> doc;
  doc["request_id"] = req_id;
  doc["device_id"]  = DEVICE_ID;
  doc["stage"]      = stage;
  if (note && note[0]) doc["note"] = note;
  String body;
  serializeJson(doc, body);

  HTTPClient http;
  http.setTimeout(2500);
  http.setConnectTimeout(2000);
  String url = String("http://") + SERVER_HOST + ":" + SERVER_PORT + "/api/ack";
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(body);
  Serial.printf("[ACK] %s -> %s : %d\n", req_id, stage, code);
  http.end();
}

// 轮询服务器有没有派给自己的任务
static void poll_command() {
  HTTPClient http;
  http.setTimeout(2500);          // 避免长时间阻塞主循环
  http.setConnectTimeout(2000);
  String url = String("http://") + SERVER_HOST + ":" + SERVER_PORT +
               "/api/command?device_id=" + DEVICE_ID;
  http.begin(url);
  int code = http.GET();
  if (code != 200) {
    http.end();
    return;
  }
  String payload = http.getString();
  http.end();

  StaticJsonDocument<512> doc;
  DeserializationError err = deserializeJson(doc, payload);
  if (err) return;

  JsonObject cmd = doc["command"];
  if (cmd.isNull()) return;

  const char *req_id = cmd["request_id"] | "";
  const char *action = cmd["action"] | "sample";
  if (!req_id[0]) return;

  Serial.printf("[CMD] 收到任务 %s action=%s\n", req_id, action);

  if (strcmp(action, "pause") == 0) {
    periodic_paused = true;
    send_ack(req_id, "completed", "periodic paused");   // 无需采集数据,直接完成
    Serial.println("[CMD] 已暂停周期上报(命令通道保持)");
  } else if (strcmp(action, "resume") == 0) {
    periodic_paused = false;
    send_ack(req_id, "completed", "periodic resumed");
    Serial.println("[CMD] 已恢复周期上报");
  } else {
    // 默认 sample:先回执"已接收",再立即采一次并带上 request_id 上传
    send_ack(req_id, "received");
    sample_now_and_upload(req_id);
  }
}

// ============================================================
void setup() {
  Serial.begin(115200);
  // ⚠️ 关键:S3-EYE 是原生 USB CDC。主机没打开串口监视器时,
  // Serial 写入会阻塞等待主机取数据(实测把 5Hz 上传拖成 0.5Hz)。
  // 设为 0 = 写不进去就直接丢弃,绝不阻塞主循环。
  Serial.setTxTimeoutMs(0);
  delay(200);
  Serial.println();
  Serial.println("=== ESP32-S3-EYE QMA7981 Uploader ===");
  Serial.printf("Group=%s  Device=%s  Server=%s:%d\n",
                GROUP_ID, DEVICE_ID, SERVER_HOST, SERVER_PORT);

  wifi_connect();
#if USE_QMA7981
  sensor_ok = qma_init();
  Serial.println(sensor_ok ? "[QMA] init OK" : "[QMA] init FAIL");
  if (sensor_ok) {
    Serial.println("[QMA] 请保持板子静止 1 秒,正在做重力校准...");
    qma_calibrate();
  }
#else
  Serial.println("[QMA] demo mode (USE_QMA7981=0), using synthetic data");
#endif
}

void loop() {
  unsigned long now = millis();

  // ---- 周期采样 ----
  // 用 while 补帧:上一轮若被 HTTP 等耗时操作拖长,把错过的采样补回来,
  // 保证 20Hz 采样率不退化(上限 8 次,避免长时间阻塞后一次性爆发)
  int catchup = 0;
  while (now - last_sample_ms >= SAMPLE_PERIOD_MS && catchup < 8) {
    last_sample_ms += SAMPLE_PERIOD_MS;
    catchup++;
    float ax, ay, az;
    bool got = false;
#if USE_QMA7981
    got = qma_read(ax, ay, az);
#else
    sim_generate(now / 1000.0f, ax, ay, az);
    got = true;
#endif
    if (got) {
      sumbuf.ax += ax; sumbuf.ay += ay; sumbuf.az += az;
      sumbuf.n++;
      sensor_ok = true;
    } else {
      sensor_ok = false;
    }
  }

  // ---- 周期上传(被暂停时跳过,但命令通道继续工作) ----
  if (!periodic_paused && (now - last_upload_ms >= UPLOAD_PERIOD_MS)) {
    last_upload_ms = now;
    if (sumbuf.n > 0) build_and_upload();
  }

  // ---- 命令轮询(第 2 周:接收 Web 下发的采集任务) ----
  if (now - last_cmd_poll_ms >= CMD_POLL_PERIOD_MS) {
    last_cmd_poll_ms = now;
    if (WiFi.status() == WL_CONNECTED) poll_command();
  }

  // ---- WiFi 掉线重连 ----
  static unsigned long last_wifi_check = 0;
  if (now - last_wifi_check > 5000) {
    last_wifi_check = now;
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("[WiFi] lost, reconnecting...");
      wifi_connect();
    }
  }
}
