// ============================================================
//  ESP32 + MPU6050  IMU 传感数据采集 + WiFi HTTP 上传
//  对应周任务卡:真实传感源、单位与时间、来源组号、失败状态
// ============================================================
#include <WiFi.h>
#include <HTTPClient.h>
#if USE_MPU6050
  #include <Wire.h>
#endif
#include <ArduinoJson.h>
#include "config.h"

// ---------- I2C & MPU6050 ----------
static const uint8_t MPU_ADDR = 0x68;  // AD0 悬空为 0x68,接 3V3 改 0x69
static const int I2C_SDA = 21;
static const int I2C_SCL = 22;

struct AccelGyro {
  int16_t ax, ay, az;
  int16_t gx, gy, gz;
  int16_t t_raw;
};

AccelGyro last_sample;
bool sensor_ok = false;
bool sensor_mode_demo = false;   // 当前是否为合成演示模式(USE_MPU6050=0)
unsigned long last_sensor_print = 0;

// ---------- 采样与上传控制 ----------
static const unsigned long SAMPLE_PERIOD_MS = 50;   // 50ms 采一次
static const unsigned long UPLOAD_PERIOD_MS = 1000; // 1s 上传一次
unsigned long last_sample_ms = 0;
unsigned long last_upload_ms = 0;
unsigned long http_fail_count = 0;

// 1s 内均值缓存
struct SumBuf {
  double ax=0, ay=0, az=0, gx=0, gy=0, gz=0;
  int n=0;
} sumbuf;

// ---------- 工具函数 ----------
static int16_t swap16(int16_t v) {
  return (int16_t)(((v & 0x00FF) << 8) | ((v & 0xFF00) >> 8));
}

bool mpu_init() {
#if USE_MPU6050
  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(400000);
  Wire.beginTransmission(MPU_ADDR);
  if (Wire.endTransmission() != 0) {
    Serial.println("[MPU] not found on I2C bus");
    return false;
  }
  // 0x6B PWR_MGMT_1 写 0 唤醒
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B);
  Wire.write(0x00);
  Wire.endTransmission();
  delay(100);
  return true;
#else
  // USE_MPU6050=0 时跳过真实传感器,返回 true 表示"链路层 OK"
  Serial.println("[MPU] USE_MPU6050=0, using synthetic demo data");
  return true;
#endif
}

// 演示模式:按时间 t (秒) 生成与 MPU6050 同量纲的 int16 原始读数
//   量程 ±2g / ±250°/s,后面 build_and_upload 会按 16384 LSB/g 与 131 LSB/(°/s)
//   还原成物理单位(m/s² 和 °/s),Web 上看到的波形与真实 IMU 一致。
static AccelGyro sim_generate(float t) {
  AccelGyro s;
  float ax_ms2 = 0.20f  * sinf(0.7f * t) + 0.03f * (((float)random(1000)) / 1000.0f - 0.5f);
  float ay_ms2 = 0.15f  * cosf(0.5f * t) + 0.03f * (((float)random(1000)) / 1000.0f - 0.5f);
  float az_ms2 = 9.80665f + 0.10f * sinf(1.0f * t) + 0.03f * (((float)random(1000)) / 1000.0f - 0.5f);
  float gx_dps = 0.5f   * sinf(0.4f * t) + 0.10f * (((float)random(1000)) / 1000.0f - 0.5f);
  float gy_dps = 0.5f   * cosf(0.6f * t) + 0.10f * (((float)random(1000)) / 1000.0f - 0.5f);
  float gz_dps = 5.0f   * sinf(0.3f * t) + 0.10f * (((float)random(1000)) / 1000.0f - 0.5f);
  // 反推为 ±2g / ±250°/s 下的 LSB
  s.ax    = (int16_t)((ax_ms2 / 9.80665f) * 16384.0f);
  s.ay    = (int16_t)((ay_ms2 / 9.80665f) * 16384.0f);
  s.az    = (int16_t)((az_ms2 / 9.80665f) * 16384.0f);
  s.gx    = (int16_t)(gx_dps * 131.0f);
  s.gy    = (int16_t)(gy_dps * 131.0f);
  s.gz    = (int16_t)(gz_dps * 131.0f);
  // 室温 26℃,由 MPU 公式反算:t_c = raw/340 + 36.53  →  raw = (t_c - 36.53)*340
  s.t_raw = (int16_t)((26.0f - 36.53f) * 340.0f);
  return s;
}

bool mpu_read(AccelGyro &out) {
#if USE_MPU6050
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);  // ACCEL_XOUT_H
  if (Wire.endTransmission(false) != 0) return false;
  Wire.requestFrom((int)MPU_ADDR, 14);
  if (Wire.available() < 14) return false;
  uint8_t b[14];
  for (int i = 0; i < 14; ++i) b[i] = Wire.read();
  out.ax = (int16_t)((b[0] << 8) | b[1]);
  out.ay = (int16_t)((b[2] << 8) | b[3]);
  out.az = (int16_t)((b[4] << 8) | b[5]);
  out.t_raw = (int16_t)((b[6] << 8) | b[7]);
  out.gx = (int16_t)((b[8] << 8) | b[9]);
  out.gy = (int16_t)((b[10] << 8) | b[11]);
  out.gz = (int16_t)((b[12] << 8) | b[13]);
  return true;
#else
  out = sim_generate(millis() / 1000.0f);
  return true;
#endif
}

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
  if (WiFi.status() != WL_CONNECTED) {
    wifi_connect();
  }
  HTTPClient http;
  String url = String("http://") + SERVER_HOST + ":" + SERVER_PORT + "/api/data";
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(json_body);
  if (code > 0) {
    Serial.printf("[HTTP] %d, resp=%s\n", code, http.getString().c_str());
    if (code == 200) { http.end(); return true; }
  } else {
    Serial.printf("[HTTP] err %s\n", http.errorToString(code).c_str());
  }
  http.end();
  return false;
}

void build_and_upload() {
  // 1s 内均值
  double ax = sumbuf.n ? sumbuf.ax / sumbuf.n : 0;
  double ay = sumbuf.n ? sumbuf.ay / sumbuf.n : 0;
  double az = sumbuf.n ? sumbuf.az / sumbuf.n : 0;
  double gx = sumbuf.gx / max(1, sumbuf.n);
  double gy = sumbuf.gy / max(1, sumbuf.n);
  double gz = sumbuf.gz / max(1, sumbuf.n);
  // 温度(MPU6050 内部温度,℃)
  double temp_c = (sumbuf.t_raw / 340.0) + 36.53;
  // MPU6050 量程默认 ±2g / ±250°/s,换算成物理单位
  //   accel  : 16384 LSB/g
  //   gyro   : 131.0 LSB/(°/s)
  double ax_ms2 = (ax / 16384.0) * 9.80665;
  double ay_ms2 = (ay / 16384.0) * 9.80665;
  double az_ms2 = (az / 16384.0) * 9.80665;
  double gx_dps = gx / 131.0;
  double gy_dps = gy / 131.0;
  double gz_dps = gz / 131.0;
  int n_in_buf = sumbuf.n;

  // 清空缓存
  sumbuf = SumBuf{};

  StaticJsonDocument<512> doc;
  doc["group_id"]  = GROUP_ID;
  doc["device_id"] = DEVICE_ID;
  doc["ts_ms"]     = (uint64_t)millis();
  doc["uptime_s"]  = millis() / 1000.0;
  doc["n_samples"] = n_in_buf;
#if USE_MPU6050
  doc["status"]    = sensor_ok ? "ok" : "sensor_fail";
#else
  doc["status"]    = "simulated";   // 演示模式,数据由板内合成,链路真实
  doc["mode"]      = "demo";        // 给 Web 用,UI 可显示"演示数据"
#endif
  doc["acc_x"]     = ax_ms2;
  doc["acc_y"]     = ay_ms2;
  doc["acc_z"]     = az_ms2;
  doc["gyro_x"]    = gx_dps;
  doc["gyro_y"]    = gy_dps;
  doc["gyro_z"]    = gz_dps;
  doc["temp_c"]    = temp_c;
  doc["rssi"]      = WiFi.RSSI();

  String body;
  serializeJson(doc, body);

  Serial.printf("[UP] n=%d  acc=(%.2f,%.2f,%.2f)  gyro=(%.2f,%.2f,%.2f)  T=%.1f\n",
                n_in_buf, ax_ms2, ay_ms2, az_ms2,
                gx_dps, gy_dps, gz_dps, temp_c);
  bool ok = upload_payload(body);
  if (!ok) http_fail_count++;
}

// ============================================================
//  setup / loop
// ============================================================
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println();
  Serial.println("=== ESP32 IMU HTTP Uploader ===");
  Serial.printf("Group=%s  Device=%s  Server=%s:%d\n",
                GROUP_ID, DEVICE_ID, SERVER_HOST, SERVER_PORT);

  wifi_connect();
  sensor_ok = mpu_init();
#if USE_MPU6050
  Serial.println(sensor_ok ? "[MPU] init OK" : "[MPU] init FAIL (will keep retrying each sample)");
#else
  sensor_mode_demo = true;
  Serial.println("[MPU] demo mode, every sample will succeed");
#endif
}

void loop() {
  unsigned long now = millis();

  // ---- 周期性采样 ----
  if (now - last_sample_ms >= SAMPLE_PERIOD_MS) {
    last_sample_ms = now;
    AccelGyro s;
    if (mpu_read(s)) {
      last_sample = s;
      sumbuf.ax += s.ax; sumbuf.ay += s.ay; sumbuf.az += s.az;
      sumbuf.gx += s.gx; sumbuf.gy += s.gy; sumbuf.gz += s.gz;
      sumbuf.t_raw += s.t_raw;
      sumbuf.n++;
      sensor_ok = true;
    } else {
      sensor_ok = false;
    }
  }

  // ---- 周期上传 ----
  if (now - last_upload_ms >= UPLOAD_PERIOD_MS) {
    last_upload_ms = now;
    if (sumbuf.n > 0) {
      build_and_upload();
    } else {
      Serial.println("[UP] skip (no samples in last 1s)");
    }
  }

  // ---- 看门狗:WiFi 掉线重连 ----
  static unsigned long last_wifi_check = 0;
  if (now - last_wifi_check > 5000) {
    last_wifi_check = now;
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("[WiFi] lost, reconnecting...");
      wifi_connect();
    }
  }
}
