// QMA7981 诊断:读寄存器原始值,确认量程与换算系数
#include <Wire.h>

static const uint8_t QMA = 0x12;
static const int SDA_PIN = 4;
static const int SCL_PIN = 5;

uint8_t rd(uint8_t reg) {
  Wire.beginTransmission(QMA);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return 0xFF;
  if (Wire.requestFrom((int)QMA, 1) != 1) return 0xFF;
  return Wire.read();
}

void wr(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(QMA);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission();
}

// 右对齐 14 位(2026-10-10 实测修正):拼成 16 位后取低 14 位再符号扩展。
// 旧写法 >>2 会让读数系统性小 4 倍。
int16_t compose14(uint8_t lsb, uint8_t msb) {
  uint16_t u = ((uint16_t)msb << 8) | (uint16_t)lsb;
  u &= 0x3FFF;
  if (u & 0x2000) return (int16_t)(u | 0xC000);
  return (int16_t)u;
}

void setup() {
  Serial.begin(115200);
  delay(2000);
  pinMode(SDA_PIN, INPUT_PULLUP);
  pinMode(SCL_PIN, INPUT_PULLUP);
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);

  Serial.println();
  Serial.println("=== QMA7981 诊断 ===");
  Serial.printf("CHIP_ID(0x00) = 0x%02X\n", rd(0x00));

  // 读当前量程
  uint8_t fsr = rd(0x0F);
  Serial.printf("FSR(0x0F)     = 0x%02X  (低4位=量程, 0x04=+-8g)\n", fsr);

  // 主动设置量程 +-8g 并回读
  wr(0x0F, 0x04);
  delay(50);
  Serial.printf("写入 0x04 后回读 = 0x%02X\n", rd(0x0F));

  // 进入 Active
  uint8_t pm = rd(0x11);
  wr(0x11, pm | 0x80);
  Serial.printf("PM(0x11)      = 0x%02X -> 0x%02X\n", pm, rd(0x11));
  delay(100);

  Serial.println();
  Serial.println("静止测量 5 组(原始值 + 两种换算):");
  Serial.println("--------------------------------------------------");
}

void loop() {
  // 先回读量程寄存器
  Serial.printf("[FSR 0x0F] = 0x%02X    [PM 0x11] = 0x%02X\n", rd(0x0F), rd(0x11));

  for (int i = 0; i < 3; i++) {
    Wire.beginTransmission(QMA);
    Wire.write(0x01);
    Wire.endTransmission(false);
    Wire.requestFrom((int)QMA, 6);
    uint8_t r[6] = {0};
    for (int k = 0; k < 6 && Wire.available(); k++) r[k] = Wire.read();

    int16_t x = compose14(r[0], r[1]);
    int16_t y = compose14(r[2], r[3]);
    int16_t z = compose14(r[4], r[5]);
    float m = sqrt((float)x*x + (float)y*y + (float)z*z);

    Serial.printf("  raw=(%6d,%6d,%6d)  |a|=%6.1f  ->  /512=%.2fg /1024=%.2fg /2048=%.2fg\n",
                  x, y, z, m, m/512.0f, m/1024.0f, m/2048.0f);
    delay(300);
  }

  // 扫描所有量程设置,看哪个让模长接近 1g
  Serial.println("  --- 量程扫描(每档测一次,看哪档 |a|≈1g) ---");
  const uint8_t ranges[] = {0x01, 0x02, 0x04, 0x08, 0x0F};
  const char *names[] = {"+-2g", "+-4g", "+-8g", "+-16g", "+-32g"};
  for (int k = 0; k < 5; k++) {
    wr(0x0F, ranges[k]);
    delay(120);
    Wire.beginTransmission(QMA);
    Wire.write(0x01);
    Wire.endTransmission(false);
    Wire.requestFrom((int)QMA, 6);
    uint8_t r[6] = {0};
    for (int m2 = 0; m2 < 6 && Wire.available(); m2++) r[m2] = Wire.read();
    int16_t x = compose14(r[0], r[1]);
    int16_t y = compose14(r[2], r[3]);
    int16_t z = compose14(r[4], r[5]);
    float mag = sqrt((float)x*x + (float)y*y + (float)z*z);
    Serial.printf("    %-6s (写0x%02X,回读0x%02X): raw|a|=%6.1f\n",
                  names[k], ranges[k], rd(0x0F), mag);
  }
  // 恢复 +-8g
  wr(0x0F, 0x04);

  Serial.println("--------------------------------------------------");
  delay(3000);
}
