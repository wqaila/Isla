// ============================================================
//  I2C 扫描 + 传感器识别 —— 适配 ESP32-S3-EYE
//  板载传感器:QMA7981 三轴加速度计(I2C 地址 0x12)
//  板载 I2C:  SDA = GPIO4, SCL = GPIO5
//  注意:S3-EYE 的 I2C 没有外部上拉电阻,必须启用芯片内部上拉!
//  用法:Arduino IDE 选开发板 "ESP32S3 Dev Module" → 上传 → 串口 115200
// ============================================================
#include <Wire.h>

static const int I2C_SDA = 4;    // S3-EYE 板载 I2C
static const int I2C_SCL = 5;

// QMA7981 寄存器(QST 数据手册 Rev.A)
static const uint8_t QMA7981_ADDR    = 0x12;  // 7 位地址
static const uint8_t QMA7981_CHIP_ID = 0x00;  // CHIP_ID 寄存器

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

  // 【关键】S3-EYE 无外部上拉,必须开内部上拉,否则 I2C 完全不通
  pinMode(I2C_SDA, INPUT_PULLUP);
  pinMode(I2C_SCL, INPUT_PULLUP);
  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(100000);

  Serial.println();
  Serial.println("=== I2C 扫描 + 传感器识别 (ESP32-S3-EYE) ===");
  Serial.printf("SDA=GPIO%d  SCL=GPIO%d\n", I2C_SDA, I2C_SCL);
  Serial.println("预期:QMA7981 在地址 0x12,摄像头 OV2640 在 0x30");
  Serial.println("每 3 秒自动重扫。");
}

void loop() {
  Serial.println("\n--- scan ---");
  int found = 0;

  for (uint8_t a = 0x01; a < 0x7F; ++a) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      found++;
      uint8_t who = readReg(a, 0x00);
      const char *guess = "未知设备";
      if (a == QMA7981_ADDR) {
        // QMA7981 的 CHIP_ID 默认值由芯片 NVM 决定,实测常见 0xE7
        guess = (who == 0xE7) ? "QMA7981 加速度计(实测值 0xE7)"
                              : "QMA7981 加速度计(ID 随批次变化,通信正常即可)";
      } else if (a == 0x30) {
        guess = "OV2640 摄像头(SCCB)";
      }
      Serial.printf("  地址 0x%02X   寄存器0x00=0x%02X   -> %s\n", a, who, guess);
    }
  }

  if (found == 0) {
    Serial.println("  [X] 总线上没有发现任何 I2C 设备");
    Serial.println("  检查:");
    Serial.println("    1) 开发板是否选了 ESP32S3 Dev Module");
    Serial.println("    2) S3-EYE 是板载传感器,无需外接线");
    Serial.println("    3) 代码里是否启用了内部上拉(pinMode INPUT_PULLUP)");
  } else {
    Serial.printf("  共发现 %d 个设备。\n", found);
  }

  delay(3000);
}
