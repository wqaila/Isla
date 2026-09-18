# Arduino IDE 安装 & 打开 .ino 文件(Windows)

> 你电脑上还没装 Arduino IDE。`.ino` 是 Arduino 专用格式,**必须用 IDE 打开**,不能双击当文本看。
> 本文从"下载"一路讲到"能成功烧录 `i2c_scan.ino` 并看到扫描结果"。

---

## 一、下载

1. 打开官网:<https://www.arduino.cc/en/software>
2. 在 **Arduino IDE 2.x** 一栏,点 **Windows Win 10 and newer (64-bit)**
   - 直链(官网慢时用):`https://downloads.arduino.cc/arduino-ide/arduino-ide_latest_Windows_64bit.exe`
3. 文件约 150 MB,存到桌面即可

> 如果公司/学校网络下载慢,也可以在浏览器搜 "Arduino IDE 下载",认准 `arduino.cc` 域名。

---

## 二、安装

1. 双击下载的 `.exe`
2. 一路 **Next → Install → Finish**
3. 若弹出"Windows 已保护你的电脑"(SmartScreen):
   点 **更多信息** → **仍要运行**
4. 首次启动若提示安装 USB 驱动,选 **允许 / 安装**

---

## 三、打开 `i2c_scan.ino`(三种方式,任选)

**方式 1(推荐):在 IDE 里打开**
- 启动 Arduino IDE
- 菜单 `File → Open...`(文件 → 打开)
- 定位到 `D:\kechengrenwu\123\board\i2c_scan\`
- 选中 `i2c_scan.ino` → 打开

**方式 2:右键打开**
- 在文件资源管理器里找到 `i2c_scan.ino`
- 右键 → 打开方式 → 选 **Arduino IDE**

**方式 3:拖拽**
- 把 `i2c_scan.ino` 直接拖进 Arduino IDE 窗口

打开成功后:标题栏显示 `i2c_scan`,编辑区能看到代码。

> 为什么是打开文件夹里的 `.ino` 而不是别的?因为 Arduino 规定:**sketch 文件夹名必须和主 `.ino` 同名**。
> 我们这里 `board/i2c_scan/i2c_scan.ino` 已经符合规范,直接打开即可。

---

## 四、烧录前要配的环境

> **两项不是都要现在做,按你要烧哪个 sketch 决定:**
> - 烧 `i2c_scan.ino`(识别传感器型号)→ **只需要 ESP32 板支持**,不需要 ArduinoJson
> - 烧 `imu_http.ino`(上传数据到服务器)→ 才需要 **ArduinoJson 6.x**

### 1. 装 ESP32 板支持

- `File → Preferences`(文件 → 首选项)
- 在 **Additional boards manager URLs**(附加开发板管理器网址)里粘贴:
  ```
  https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
  ```
- 确定后:`Tools → Board → Boards Manager`(工具 → 开发板 → 开发板管理器)
- 搜 `esp32`,安装 **esp32 by Espressif Systems**(约 200 MB,要等几分钟)

### 2. 装 ArduinoJson 6.x 库

- `Tools → Manage Libraries`(工具 → 管理库)
- 搜 `ArduinoJson`
- **务必选 6.x 版本**(如 6.21.5)安装
- ⚠️ 装成 7.x 会报错 `StaticJsonDocument does not name a type`(主程序 `imu_http.ino` 用到它)

---

## 五、烧录 & 看串口输出

1. 用 **USB 数据线**连上 ESP32(必须是能传数据的那根,不是纯充电线)
2. `Tools → Board` 选 **ESP32 Dev Module**
3. `Tools → Port` 选出现的 COM 口(如 COM5)
4. 点左上角 **→**(Upload 上传按钮),等 `Done uploading`
5. `Tools → Serial Monitor`(串口监视器),右下角波特率选 **115200**
6. 就能看到扫描结果:

```
=== I2C 扫描 + IMU 型号识别 ===
SDA=GPIO21   SCL=GPIO22

--- scan ---
  地址 0x68   WHO_AM_I(0x75)=0x68   -> MPU6050
  共发现 1 个设备。
```

看到 `-> MPU6050` 就说明传感器标准可用;是别的型号就把结果发我。

---

## 六、常见问题

| 现象 | 原因 / 解决 |
|------|-------------|
| `Port` 列表里没有 COM 口 | 换根 USB 数据线;装 CP210x / CH340 驱动;换 USB 口 |
| 上传卡在 `Connecting...` | 按住板子上的 **BOOT** 键再点上传;或换线 |
| 编译报 `StaticJsonDocument does not name a type` | ArduinoJson 装成了 7.x,卸载后装 6.x |
| `Tools → Board` 里找不到 ESP32 | 附加开发板管理器网址没填对,或板支持包还没装完 |
| 串口监视器里是乱码 | 波特率没选 115200 |
| 扫描不到任何设备 | 查 VCC 是否接 3.3V、SDA/SCL 是否接反、线是否插紧 |

---

## 七、装完之后

回到主文档 `README.md` 的 **§4** 继续:
1. 改 `board/imu_http/config.h` 里的 WiFi 名和密码
2. 起服务 `scripts\start_server.bat`
3. 烧 `board/imu_http/imu_http.ino`
4. 浏览器打开 <http://127.0.0.1:8000/>
