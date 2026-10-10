// QMA7981 卡死诊断:读取寄存器现场 + 尝试各种恢复手段
// 现象:板子受机械冲击(翻转/放下)后,Z 轴读数卡在异常值(实测 60 m/s² ≈ 6.2g),
//      且非常稳定,不是噪声。本工具用来定位原因并找到有效的恢复方法。
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

int16_t compose14(uint8_t lsb, uint8_t msb) {
  uint16_t u = ((uint16_t)msb << 8) | (uint16_t)lsb;
  u &= 0x3FFF;
  if (u & 0x2000) return (int16_t)(u | 0xC000);
  return (int16_t)u;
}

void read3(int16_t &x, int16_t &y, int16_t &z) {
  Wire.beginTransmission(QMA);
  Wire.write(0x01);
  Wire.endTransmission(false);
  Wire.requestFrom((int)QMA, 6);
  uint8_t r[6] = {0};
  for (int k = 0; k < 6 && Wire.available(); k++) r[k] = Wire.read();
  x = compose14(r[0], r[1]);
  y = compose14(r[2], r[3]);
  z = compose14(r[4], r[5]);
}

void show(const char *tag) {
  int16_t x, y, z;
  read3(x, y, z);
  float m = sqrt((float)x * x + (float)y * y + (float)z * z);
  Serial.printf("  %-22s raw=(%6d,%6d,%6d) |a|=%6.1f LSB = %5.2f g (按1024)\n",
                tag, x, y, z, m, m / 1024.0f);
}

void setup() {
  Serial.begin(115200);
  delay(2000);
  pinMode(SDA_PIN, INPUT_PULLUP);
  pinMode(SCL_PIN, INPUT_PULLUP);
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);

  Serial.println();
  Serial.println("=== QMA 卡死诊断 ===");
  Serial.printf("CHIP_ID(0x00) = 0x%02X\n", rd(0x00));

  // ---- 1) 寄存器现场 dump(0x00~0x3F) ----
  Serial.println("--- 寄存器现场 0x00~0x3F ---");
  for (uint8_t base = 0; base < 0x40; base += 16) {
    Serial.printf("  %02X:", base);
    for (uint8_t i = 0; i < 16; i++) Serial.printf(" %02X", rd(base + i));
    Serial.println();
  }

  // ---- 2) 进入 Active 后的当前值 ----
  uint8_t pm = rd(0x11);
  wr(0x11, pm | 0x80);
  delay(100);
  Serial.println("--- 当前读数 ---");
  show("初始");

  // ---- 3) 尝试恢复手段 1:重新写量程 + 电源模式 ----
  wr(0x0F, 0x04);   // ±8g
  delay(10);
  wr(0x11, 0x80);   // Active
  delay(200);
  show("手段1:重写FSR+PM");

  // ---- 4) 尝试恢复手段 2:standby -> active 切换 ----
  wr(0x11, 0x00);   // standby
  delay(200);
  wr(0x11, 0x80);   // active
  delay(200);
  show("手段2:standby->active");

  // ---- 5) 尝试恢复手段 3:软复位(0x36 = 0xB6,常见于 QMA 系列) ----
  wr(0x36, 0xB6);
  delay(300);
  wr(0x0F, 0x04);
  delay(10);
  wr(0x11, 0x80);
  delay(300);
  show("手段3:0x36=0xB6软复位");

  // ---- 6) 尝试恢复手段 4:0x11 写 0xB6 ----
  wr(0x11, 0xB6);
  delay(300);
  wr(0x0F, 0x04);
  delay(10);
  wr(0x11, 0x80);
  delay(300);
  show("手段4:0x11=0xB6");

  // ---- 7) 尝试恢复手段 5:复位后静置更久 ----
  wr(0x36, 0xB6);
  delay(1000);
  wr(0x0F, 0x04);
  delay(10);
  wr(0x11, 0x80);
  delay(1000);
  show("手段5:软复位+等1s");

  Serial.println("--- 复位后寄存器 0x0F/0x11 ---");
  Serial.printf("  FSR=0x%02X  PM=0x%02X\n", rd(0x0F), rd(0x11));
  Serial.println("================================================");
}

void loop() {
  show("loop持续观测");
  delay(2000);
}
