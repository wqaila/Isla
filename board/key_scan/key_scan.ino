// ============================================================
//  按键探针:确认 BOOT(GPIO0) 与 4 键 ADC 阵列(GPIO1) 哪个真的可用
//
//  原理图(ESP32-S3-EYE MB V2.2)Buttons 区:
//    SW2 "Download" -> IO0(按下接地)
//    SW3~SW6 "4-Keys: ADC1_CH0" -> IO1,分压 1.98V / 0.82V / 0.38V
//
//  串口:心跳 2s 一行 + 状态变化立即打印
//  LCD :GPIO0 实时电平(GREEN=HIGH / RED=LOW)、ADC 毫伏、按下计数
// ============================================================
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>

#define LCD_SCLK 21
#define LCD_MOSI 47
#define LCD_DC   43
#define LCD_CS   44
#define LCD_BL   48
#define LCD_RST  -1

#define KEY_BOOT 0     // 数字按键(BOOT / Download)
#define KEY_ADC  1     // 4 键 ADC 阵列 (ADC1_CH0)

Adafruit_ST7789 tft(&SPI, LCD_CS, LCD_DC, LCD_RST);

int  boot_count = 0;
int  adc_count  = 0;
bool last_boot  = true;
int  last_mv    = -1;
unsigned long last_hb_ms  = 0;
unsigned long last_lcd_ms = 0;
int  adc_min = 9999, adc_max = -1;   // 观察窗口内的极值
int  boot_low_seen = 0;              // GPIO0 出现过多少次低电平

void lcd_show(bool boot_lvl, int mv) {
  tft.fillScreen(ST77XX_BLACK);

  tft.setTextSize(2);
  tft.setTextColor(ST77XX_WHITE);
  tft.setCursor(8, 10);
  tft.print("KEY SCAN");

  // GPIO0 电平
  tft.setTextSize(2);
  tft.setTextColor(boot_lvl ? ST77XX_GREEN : ST77XX_RED);
  tft.setCursor(8, 50);
  tft.print("IO0: ");
  tft.print(boot_lvl ? "HIGH" : "LOW ");

  tft.setTextSize(1);
  tft.setTextColor(ST77XX_YELLOW);
  tft.setCursor(8, 78);
  tft.print("boot presses: ");
  tft.print(boot_count);

  // GPIO1 ADC
  tft.setTextSize(2);
  tft.setTextColor(ST77XX_CYAN);
  tft.setCursor(8, 100);
  tft.print("ADC: ");
  tft.print(mv);
  tft.print("mV");

  tft.setTextSize(1);
  tft.setTextColor(ST77XX_YELLOW);
  tft.setCursor(8, 128);
  tft.print("adc presses: ");
  tft.print(adc_count);

  tft.setTextSize(1);
  tft.setTextColor(ST77XX_WHITE);
  tft.setCursor(8, 150);
  tft.print("ADC min/max: ");
  tft.print(adc_min);
  tft.print("/");
  tft.print(adc_max);

  tft.setCursor(8, 168);
  tft.print("IO0 low seen: ");
  tft.print(boot_low_seen);

  tft.setTextSize(1);
  tft.setTextColor(0x8410);   // 灰
  tft.setCursor(8, 200);
  tft.print("PRESS ANY KEY...");
}

void setup() {
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);
  delay(300);
  Serial.println();
  Serial.println("=== KEY SCAN PROBE ===");

  pinMode(LCD_BL, OUTPUT);
  digitalWrite(LCD_BL, LOW);          // P-MOS 低电平点亮

  pinMode(KEY_BOOT, INPUT_PULLUP);
  analogSetPinAttenuation(KEY_ADC, ADC_11db);   // 量程到 ~3.3V

  SPI.begin(LCD_SCLK, -1, LCD_MOSI);
  tft.init(240, 240);
  tft.setRotation(0);
  tft.fillScreen(ST77XX_BLACK);
  tft.setTextSize(2);
  tft.setTextColor(ST77XX_GREEN);
  tft.setCursor(10, 110);
  tft.print("READY");

  Serial.println("[PROBE] ready. press any key.");
}

void loop() {
  unsigned long now = millis();

  bool boot = digitalRead(KEY_BOOT);
  int  mv   = analogReadMilliVolts(KEY_ADC);

  if (mv < adc_min) adc_min = mv;
  if (mv > adc_max) adc_max = mv;

  // ---- GPIO0 下降沿 ----
  if (last_boot && !boot) {
    boot_count++;
    boot_low_seen++;
    Serial.printf("[KEY] BOOT(GPIO0) pressed, count=%d\n", boot_count);
  }
  last_boot = boot;

  // ---- ADC 键:电压明显偏离空闲值即认为按下 ----
  // 空闲通常接近 3300mV 或 0mV,这里用"相对基线变化 > 300mV"判定
  static int baseline_mv = -1;
  if (baseline_mv < 0) baseline_mv = mv;
  int delta = mv - baseline_mv;
  if (delta < 0) delta = -delta;
  if (delta > 300) {
    adc_count++;
    Serial.printf("[KEY] ADC(GPIO1) pressed, mv=%d (baseline=%d, delta=%d), count=%d\n",
                  mv, baseline_mv, delta, adc_count);
    delay(250);                      // 简单去抖
    baseline_mv = analogReadMilliVolts(KEY_ADC);
  }
  last_mv = mv;

  // ---- 心跳 ----
  if (now - last_hb_ms >= 2000) {
    last_hb_ms = now;
    Serial.printf("[HB] IO0=%s boot=%d  ADC=%dmV (min=%d max=%d) adc=%d\n",
                  boot ? "HIGH" : "LOW ", boot_count, mv, adc_min, adc_max, adc_count);
  }

  // ---- LCD 5Hz ----
  if (now - last_lcd_ms >= 200) {
    last_lcd_ms = now;
    lcd_show(boot, mv);
  }
}
