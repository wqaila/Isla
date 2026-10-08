// 最小串口测试:验证 USB CDC 是否正常输出
void setup() {
  Serial.begin(115200);
  delay(2000);   // 等 USB 枚举完成
  Serial.println();
  Serial.println("=== SERIAL TEST OK ===");
  Serial.println("如果你看到这行,说明 USB CDC 工作正常");
}

void loop() {
  static int n = 0;
  Serial.printf("[%d] alive, millis=%lu\n", ++n, millis());
  delay(1000);
}
