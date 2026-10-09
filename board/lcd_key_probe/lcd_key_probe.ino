// ============================================================
//  第 3 周硬件探针:验证板载 LCD(ST7789)与 BOOT 按键是否可用
//
//  目的:写完整逻辑之前先确认引脚对不对。屏幕能亮、按键有反应,
//        再动手写第 3 周闭环。
//
//  ESP32-S3-EYE 引脚(官方 BSP):
//    LCD ST7789  SCLK=21  MOSI=47  DC=43  CS=44  BL(背光)=48
//    按键       BOOT = GPIO0(按下为低电平)
//
//  预期:屏幕显示彩色色块 + 中文/英文提示;按 BOOT 键屏幕计数递增。
// ============================================================
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>

#define TFT_SCLK 21
#define TFT_MOSI 47
#define TFT_DC   43
#define TFT_CS   44
#define TFT_BL   48
#define TFT_RST  -1          // 未连接,交给 init() 软件复位

#define KEY_BOOT 0           // BOOT 按键

Adafruit_ST7789 tft = Adafruit_ST7789(&SPI, TFT_CS, TFT_DC, TFT_RST);

int press_count = 0;
bool bl_on = true;           // 背光状态(低电平点亮)
bool last_key = true;        // 上拉,未按下 = HIGH
unsigned long last_print_ms = 0;

void showScreen() {
  tft.fillScreen(ST77XX_BLACK);

  // 顶部色条,确认 RGB 正常
  tft.fillRect(0, 0, 240, 30, ST77XX_RED);
  tft.fillRect(0, 30, 240, 30, ST77XX_GREEN);
  tft.fillRect(0, 60, 240, 30, ST77XX_BLUE);

  tft.setTextSize(2);
  tft.setTextColor(ST77XX_WHITE);
  tft.setCursor(10, 100);
  tft.print("LCD OK");

  tft.setTextSize(1);
  tft.setTextColor(ST77XX_YELLOW);
  tft.setCursor(10, 130);
  tft.print("SCLK21 MOSI47 DC43");
  tft.setCursor(10, 145);
  tft.print("CS44 BL48");

  tft.setTextSize(2);
  tft.setTextColor(ST77XX_CYAN);
  tft.setCursor(10, 175);
  tft.print("KEY: ");
  tft.print(press_count);

  tft.setTextSize(1);
  tft.setTextColor(bl_on ? ST77XX_GREEN : ST77XX_RED);
  tft.setCursor(10, 205);
  tft.print(bl_on ? "BL ON" : "BL OFF");
}

void setup() {
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);   // S3-EYE 原生 USB:写不进就丢弃,绝不阻塞
  delay(400);

  // 背光:原理图上背光由 AO3401A(P 沟道 MOS)驱动,栅极经电阻接 GPIO48。
  // P-MOS 是 Vgs<0 导通,所以 **低电平点亮、高电平熄灭** —— 与直觉相反。
  pinMode(TFT_BL, OUTPUT);
  digitalWrite(TFT_BL, LOW);

  // 按键(上拉,按下接地)
  pinMode(KEY_BOOT, INPUT_PULLUP);

  // 自定义 SPI 引脚:MISO 不用(-1)
  SPI.begin(TFT_SCLK, -1, TFT_MOSI);

  tft.init(240, 240);
  tft.setRotation(0);

  showScreen();

  Serial.println("[PROBE] setup done");
  Serial.println("[PROBE] LCD init attempted, KEY_BOOT=GPIO0");
}

void loop() {
  bool key = digitalRead(KEY_BOOT);

  // 按下沿:切换背光(并打印当前电平),方便判断背光极性
  if (last_key && !key) {
    press_count++;
    bl_on = !bl_on;
    digitalWrite(TFT_BL, bl_on ? LOW : HIGH);
    Serial.printf("[PROBE] key pressed, count=%d, backlight=%s\n",
                  press_count, bl_on ? "ON" : "OFF");
    showScreen();
    delay(200);               // 简单去抖
  }
  last_key = key;

  // 每 3 秒报一次存活
  if (millis() - last_print_ms > 3000) {
    last_print_ms = millis();
    Serial.printf("[PROBE] alive %lu ms, key=%s, count=%d\n",
                  millis(), key ? "UP" : "DOWN", press_count);
  }

  delay(20);
}
