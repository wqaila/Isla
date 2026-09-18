// ============================================================
//  I2C 扫描 + IMU 型号识别(不依赖 WiFi,不依赖 config.h)
//  用途:传感器型号不确定时,先烧这个,看串口输出即可知道
//        "接在哪个地址" + "大概率是什么芯片"。
//  用法:Arduino IDE 打开本文件 → 选 ESP32 Dev Module → 上传
//        → 串口监视器 115200 → 观察输出(每 3 秒自动重扫)
// ============================================================
#include <Wire.h>

static const int I2C_SDA = 21;   // 默认 SDA
static const int I2C_SCL = 22;   // 默认 SCL

// 常见 IMU 的 (I2C地址, WHO_AM_I 返回值) → 型号
// 绝大多数 6 轴芯片的 WHO_AM_I 寄存器都是 0x75
struct Known {
  uint8_t addr;
  uint8_t whoami;
  const char *name;
};

static const Known KNOWN[] = {
  {0x68, 0x68, "MPU6050"},
  {0x69, 0x68, "MPU6050 (AD0 接了 3V3)"},
  {0x68, 0x70, "MPU6500"},
  {0x68, 0x71, "MPU9250"},
  {0x68, 0x73, "MPU9250 (变体)"},
  {0x68, 0x12, "ICM-20602 / ICM-20608"},
  {0x68, 0x24, "ICM-20689"},
  {0x68, 0xD1, "BMI160"},
  {0x69, 0xD1, "BMI160 (alt)"},
  {0x6A, 0x6A, "LSM6DS3 / LSM6DSO"},
  {0x6B, 0x6A, "LSM6DS3 (alt)"},
  {0x6A, 0x05, "QMI8658"},
  {0x53, 0xE5, "ADXL345 (仅加速度计)"},
  {0x1E, 0x48, "HMC5883L (仅磁力计)"},
  {0x0D, 0x00, "QMC5883L (仅磁力计)"},
};

// 读一个寄存器;失败返回 0xFF
uint8_t readReg(uint8_t addr, uint8_t reg) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return 0xFF;
  if (Wire.requestFrom((int)addr, 1) != 1) return 0xFF;
  return Wire.read();
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(100000);          // 扫描阶段用低速更稳
  Serial.println();
  Serial.println("=== I2C 扫描 + IMU 型号识别 ===");
  Serial.printf("SDA=GPIO%d   SCL=GPIO%d\n", I2C_SDA, I2C_SCL);
  Serial.println("每 3 秒自动重扫,可随时插拔线观察。");
}

void loop() {
  Serial.println("\n--- scan ---");
  int found = 0;
  for (uint8_t a = 0x01; a < 0x7F; ++a) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      found++;
      uint8_t who = readReg(a, 0x75);
      const char *guess = "未知型号";
      for (const auto &k : KNOWN) {
        if (k.addr == a && k.whoami == who) { guess = k.name; break; }
      }
      Serial.printf("  地址 0x%02X   WHO_AM_I(0x75)=0x%02X   -> %s\n",
                    a, who, guess);
    }
  }

  if (found == 0) {
    Serial.println("  ✗ 总线上没有发现任何 I2C 设备");
    Serial.println("  请依次检查:");
    Serial.println("    1) VCC 是否接 3.3V(不要接 5V)");
    Serial.println("    2) GND 是否共地");
    Serial.println("    3) SDA -> GPIO21,SCL -> GPIO22(别接反)");
    Serial.println("    4) 杜邦线是否插紧、模块是否焊好排针");
  } else {
    Serial.printf("  共发现 %d 个设备。\n", found);
    Serial.println("  提示:地址 0x68/0x69 且 WHO_AM_I=0x68 就是 MPU6050,"
                   "可直接用 imu_http 的默认代码。");
  }

  delay(3000);
}
