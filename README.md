# 开发板 IMU 传感数据采集与 Web 展示系统

> 第 1 周任务:把开发板的真实 IMU 传感数据,通过 WiFi 传到自己的电脑(充当服务器),再用浏览器查看。
>
> 本仓库提供**板端代码**(ESP32 + MPU6050)、**服务端代码**(Python 本机服务)、**Web 页面**和 **PC 模拟器**(无传感器时也能联调)。
>
> 验收要点(对照周任务卡):采集值、单位、时间戳、未更新提示、分组来源、页面无写死数值。

---

## ⏬ 三阶段路径(从今天起就能动手)

任务卡要求"先完成一个真实传感源与一种已验证网络,再补足其他"。考虑到**还没拿到传感器**,按下面的阶段推进,每天都有可见成果:

| 阶段 | 你的状态 | 用什么 | 你要做的 | 结果 |
|------|----------|--------|----------|------|
| **A · 现在** | 没板子、没传感器 | PC 模拟器 `send_sim.py` | 第 2 节启服务,第 3 节跑模拟器 | Web 上看到 sin 波形,链条已通 |
| **B · 拿到板子后** | 有 ESP32 但还没接传感器 | 把 `config.h` 里 `USE_MPU6050` 设为 0,烧录 | 接串口看 WiFi OK,Web 显示 `simulated` 蓝色徽章 | 物理板端联通链路,sin 仍是合成 |
| **C · 接传感器后** | 已有 MPU6050(GY-521) | 把 `USE_MPU6050` 改回 1,按 §1.3 接线 | 静止时 `acc_z≈9.8 m/s²`,Web 显示 `ok` | 真实采集链路,触发"采集值核对" |

> 章节对应:阶段 A = §2 + §3;阶段 B = §4;阶段 C = §4.3 + §5。

---

## 0. 整体架构

```
┌─────────────┐    WiFi    ┌──────────────────┐    HTTP     ┌─────────────┐
│  ESP32 板端 │ ─────────▶ │  本机 Flask 服务 │ ──────────▶ │  浏览器页面 │
│  MPU6050    │  POST JSON │  写 data.json    │  GET JSON   │  自动刷新    │
└─────────────┘            └──────────────────┘             └─────────────┘
       ▲                              ▲
       │                              │
   真实传感源                    也可以从 PC 模拟器发送
                            (现在没板子时先验证这条链路)
```

**三端分工**(对照任务卡前 2 学时要求):

| 端 | 职责 | 产物 |
|----|------|------|
| 板端 | 采 IMU 原始值,加时间戳和分组 ID,Wifi HTTP POST | `board/imu_http/imu_http.ino` |
| 服务端 | 收数据 → 落盘 → 提供查询 API 与首页 | `server/app.py` |
| 浏览器 | 拉最新值,显示"无数据/超时/失败"三态 | `server/templates/index.html` |

---

## 1. 准备(课前一次性完成)

### 1.1 工具链
- **Arduino IDE** 或 **PlatformIO**(本仓库用 Arduino 风格)
  - **还没装 / 不会打开 `.ino` 文件?看 [`docs/arduino-ide-setup.md`](docs/arduino-ide-setup.md)**(从下载到烧录逐步截图级说明)
- ESP32 板支持包:在 Arduino IDE 里 `文件 → 首选项 → 附加开发板管理网址` 添加
  `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`,
  然后 `工具 → 开发板 → 开发板管理器` 搜索 `esp32` 安装。
- **ArduinoJson 库必须装 6.x 版本**(代码用 `StaticJsonDocument`,7.x 已移除该 API)。
- **Python 3.10+**(Windows 自带或商店安装),运行 `python --version` 验证。
- 浏览器(Chrome/Edge 即可)

### 1.2 硬件

**本项目硬件:ESP32-S3-EYE**(乐鑫官方 AI 开发板)

| 项目 | 规格 |
|------|------|
| 主控 | ESP32-S3-WROOM-1(8MB Octal PSRAM + 8MB Flash) |
| 加速度计 | **QMA7981 三轴**(板载,I²C 地址 0x12) |
| 摄像头 | OV2640(板载,本任务不用) |
| 麦克风 | MEMS 数字麦(板载,本任务不用) |
| 接口 | Micro-USB ×1(**芯片原生 USB Serial/JTAG,无 UART 桥接芯片**) |

> 传感器焊在板上,**无需任何杜邦线接线**。

### 1.3 接线

**不需要接线** —— QMA7981 是板载传感器,I²C 走板内连线(SDA=GPIO4,SCL=GPIO5)。

只需一根 **Micro-USB 数据线**连接电脑(注意:**要能传数据的线**,不是纯充电线)。

> ⚠️ 优先插 **USB 2.0 口**(黑色内芯)。USB 3.0 口与 S3 原生 USB 有兼容性问题,会导致上传 `Write timeout`。

---

## 2. 服务端(本机 Flask)— 立刻就能跑

```bat
cd D:\kechengrenwu\123\server
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

服务监听 `http://0.0.0.0:8000`,本机浏览器打开 `http://127.0.0.1:8000/` 就能看到页面。
要让板子或别的电脑访问,打开 `http://<本机局域网IP>:8000/`(查询本机 IP:在 PowerShell 里跑 `ipconfig`,看 `IPv4 地址`)。

服务说明:
- 数据全部落到 `server/data.json`(自动生成),便于直接打开核对原始记录。
- 板端默认 **5Hz 上传**(200ms 一条),前端默认 **500ms 拉取**。

### 2.1 API 一览

| 接口 | 说明 |
|------|------|
| `POST /api/data` | 接收板端/模拟器上传 |
| `GET /api/latest?group_id=G03` | 最新一条 |
| `GET /api/history?group_id=G03&limit=60&since_ms=...` | 历史记录(支持时间范围过滤) |
| `GET /api/stats?group_id=G03&since_ms=...` | 统计(max/min/avg/标准差/峰峰值)+ 数据质量 |
| `GET /api/export.csv?group_id=G03` | 导出 CSV(带 BOM,Excel 中文不乱码) |
| `GET /api/groups` | 有哪些组在上传 |
| `GET /api/health` | 服务健康检查 |

### 2.2 Web 平台功能

升级为完整的 **IMU 实时监测与数据分析平台**:

- **系统状态栏**:服务状态 / 设备在线-延迟-离线 / 更新时间 / Group ID / 设备 ID
- **数据概览卡片**:X/Y/Z 加速度、合加速度、RSSI、采样数(带趋势与异常高亮)
- **实时图表**:三轴加速度图 + 合加速度图,支持暂停/继续/清空
- **设备状态面板**:设备 ID、传感器型号、运行时长、RSSI、接收间隔、累计数量
- **数据质量**:实际采样率、丢包、最大间隔、重复时间戳、质量分(0-100)
- **异常检测**:数据延迟、加速度异常、RSSI 过低、字段缺失、时间戳异常等
- **历史数据分析**:5 档时间范围(1min/5min/30min/1h/全部)+ 统计表
- **数据导出**:CSV / JSON
- **姿态可视化**:基于重力方向的粗略估计(**仅加速度数据,无法得到准确绝对姿态**)
- **交互**:刷新频率选择、Group ID 持久化、原始 JSON 折叠/复制、曲线显隐

> 阈值等配置集中在 `server/static/js/config.js`,修改阈值不用翻代码。

### 2.3 前端结构

```
server/
├── templates/index.html      页面骨架
├── static/
│   ├── css/style.css         样式
│   ├── js/config.js          集中配置(阈值/频率/配色)
│   ├── js/utils.js           工具函数
│   ├── js/api.js             API 请求层
│   ├── js/charts.js          图表 + 姿态可视化
│   ├── js/app.js             主逻辑(状态/UI/轮询)
│   └── vendor/chart.umd.min.js   Chart.js(本地化,不依赖 CDN)
```

---

## 3. PC 模拟器(没板子时先跑通链路)

两种启动方式,任选一种:

**A. 双窗口脚本(推荐):**
```bat
D:\kechengrenwu\123\scripts\start_demo.bat
```
脚本会先拉起 Flask,等 `/api/health` 通后再开模拟器。两个窗口,关掉任一即停那条链路。

**B. 手工两步:**
```bat
cd D:\kechengrenwu\123\simulator
pip install requests
python send_sim.py --server http://127.0.0.1:8000 --group G03 --device sim-pc-01 --hz 2
```

打开 `http://127.0.0.1:8000/`,把页面里 `Group ID` 填 `G03` 即可看到数据每 0.5s 一条在动。
模拟器会模拟一个轻微摇摆 + 重力 + 噪声的 IMU 信号(包含重力 9.8 m/s²,单位对照任务卡要求的"核对单位")。

**健康自检(可选):** 另开终端 `python scripts/health.py`,会打 `/api/health` 和 `/api/latest` 的状态。

这一步**先把"链路调通"**,等板子到手再切真硬件。

---

## 4. 板端(ESP32-S3-EYE)

> **本项目当前硬件:ESP32-S3-EYE**(乐鑫 AI 开发板,板载 QMA7981 三轴加速度计 + OV2640 摄像头 + 数字麦克风)
> 传感器**焊在板子上,无需任何接线**。

### 4.0 找本机 IP(填进 config.h)

```bat
cd D:\kechengrenwu\123
python scripts\find_local_ip.py
```
输出形如:
```
  192.168.1.100        默认出网网卡(最可能是 WiFi)
  127.0.0.1            本机回环
👉  #define SERVER_HOST  "192.168.1.100"
    #define SERVER_PORT  8000
```

### 4.1 板载硬件(无需接线)

| 项目 | 值 |
|------|-----|
| 加速度计 | **QMA7981** 三轴,I²C 地址 `0x12` |
| I²C 引脚 | **SDA = GPIO4,SCL = GPIO5**(板载连线) |
| 摄像头 | OV2640,I²C 地址 `0x30`(本任务不用) |
| USB | 1 个 Micro-USB,**芯片原生 USB Serial/JTAG**,无 UART 桥接芯片 |

> ⚠️ **S3-EYE 的 I²C 没有外部上拉电阻**,代码里必须 `pinMode(INPUT_PULLUP)`,否则传感器完全读不到。`imu_http.ino` 已处理。

### 4.2 识别传感器型号(可选,排查用)

`board/i2c_scan/i2c_scan.ino` —— 扫描 I²C 总线并识别型号。

正常输出:
```
--- scan ---
  地址 0x12   寄存器0x00=0x90   -> QMA7981 加速度计
  共发现 1 个设备。
```
- `0x12` 有响应 = 传感器正常
- **`寄存器0x00` 的值随批次变化**(实测 0x90,参考文档是 0xE7),不强制校验

### 4.3 配置

`board/imu_http/config.h`(**已被 .gitignore 排除,填密码不会上传 GitHub**):

```cpp
#define WIFI_SSID       "你的WiFi名"          // ← 必改(ESP32 仅支持 2.4GHz)
#define WIFI_PASS       "你的WiFi密码"        // ← 必改
#define SERVER_HOST     "192.168.x.x"        // 本机 IP,见 §4.0
#define SERVER_PORT     8000
#define GROUP_ID        "G03"
#define DEVICE_ID       "esp32s3-eye-01"
#define USE_QMA7981     1                    // 1=读板载传感器;0=合成演示数据
```

### 4.4 烧录 & 验证

**方式 A:命令行(推荐,本项目实际使用)**

```bash
CLI="/c/Program Files/Arduino CLI/arduino-cli.exe"

# 1) 编译(必须带 CDCOnBoot=cdc,否则串口输出走 UART0,USB 口看不到)
"$CLI" compile --fqbn "esp32:esp32:esp32s3:CDCOnBoot=cdc" board/imu_http

# 2) 上传(端口是烧录口,通常 COM5)
"$CLI" upload -p COM5 --fqbn "esp32:esp32:esp32s3:CDCOnBoot=cdc" board/imu_http

# 3) ⚠️ 必须复位!否则程序不会启动(S3-EYE 无 UART 桥接,自动复位信号传不到)
ESPTOOL="/c/Users/user/AppData/Local/Arduino15/packages/esp32/tools/esptool_py/5.3.1/esptool.exe"
"$ESPTOOL" --port COM5 --after watchdog-reset chip-id
```

**方式 B:Arduino IDE**
- 开发板选 **`ESP32S3 Dev Module`**
- 工具菜单里把 **`USB CDC On Boot` 设为 `Enabled`**
- 上传后**手动按一下板子上的 RST 键**

**库依赖**:`ArduinoJson` **必须 6.x**(代码用 `StaticJsonDocument`,7.x 已移除)。
命令行装:`"$CLI" lib install "ArduinoJson@6.21.5"`

**验证成功**:
```
[QMA] init OK
[QMA] 重力校准完成: 1g = 414.2 LSB (采样 60 次, 标称 1024)
[UP] n=19  acc=(-0.296, -0.710, -0.645) g = (-2.91, -6.96, -6.36) m/s2
[HTTP] 200, resp={"count":57,"ok":true}
```

**板端逻辑要点**:
- 默认每 50ms 采一次(20Hz),每 1s 算均值并上传一次
- 上传字段:`ts_ms`、`group_id`、`device_id`、`status`、`acc_*_g`(g)、`acc_*`(m/s²)、`rssi`、`n_samples`
- **启动时自动做重力校准**:静止时三轴模长恒等于 1g,据此反推真实灵敏度(兼容不同批次芯片)
- WiFi 断连自动重连;HTTP 失败打印状态码
- 传感器读不到时 `status="sensor_fail"`;演示模式 `status="simulated"`(Web 显示蓝色徽章)

---

## 5. 当堂验证(对照周任务卡"当堂验证")

| 验证项 | 操作 | 期望 |
|--------|------|------|
| 采集值 | 看串口监视器 | 静止时**三轴模长 ≈ 1g**;某个轴 ≈ ±1g,另两轴 ≈ 0 |
| 服务端原始记录 | 打开 `server/data.json` | 有新条目,timestamp 单调递增 |
| 页面变化 | 板子动一动 | Web 数字实时变化,曲线跳动 |
| 停采后保留旧时间 | 拔板子电源或停模拟器 | "最后更新"冻结在停止那一刻,标题变**未更新** |
| 数据来自本组 | 把 group 改成 G99 | 页面显示 "无数据"(不与 G03 混) |
| 页面未写死数值 | F12 查看元素 | 数字格文本每 1s 都在变,不是常量 |

**失败判定**:
- 服务端超过 10s 没收到 → 页面顶部变黄,文字显示 "已超时 N 秒"。
- 完全没数据 → 灰色 **无数据**。
- 上传 `status != "ok"` → 数字变灰 + **失败**。

---

## 6. 排错(嵌入式开发排错过程)

### 6.1 ESP32-S3-EYE 专属坑(实测踩过)

| 现象 | 原因 | 解决 |
|------|------|------|
| **上传报 `Write timeout`** | 用了 USB 3.0 口,与 S3 原生 USB 兼容性差 | **换到 USB 2.0 口**(黑色内芯) |
| **烧录成功但串口 0 输出** | S3-EYE **无 UART 桥接芯片**,esptool 自动复位信号传不到,程序停在 bootloader 没启动 | 烧录后执行 `esptool --after watchdog-reset chip-id`,或**手动按 RST 键** |
| **串口完全没反应**(复位后) | 没设 `CDCOnBoot=cdc`,Serial 输出到 UART0,USB 口看不到 | 编译时加 `CDCOnBoot=cdc` |
| **端口号会变** | 程序运行时创建自己的 USB CDC 设备 | 烧录口(如 COM5)和运行口(如 COM6)可能不同,`arduino-cli board list` 查看 |
| **数值偏小/偏大**(如静止模长 0.44g) | 芯片灵敏度与手册标称不符(批次/型号差异) | 已内置**重力自动校准**,启动时静止 1 秒即可;也可用 `board/qma_diag` 诊断 |
| **烧录后无法再烧录** | 程序不停重启(官方已知问题) | 按住 BOOT → 按 RST → 松 RST → 松 BOOT,进入下载模式 |

### 6.2 通用排错

| 现象 | 排查点 |
|------|--------|
| 板子串口反复 `WiFi disconnected` | SSID/密码错;2.4G/5G 频段;WiFi 信号弱 |
| `HTTP -1` / `connect fail` | 服务端 IP 是否对;PC 防火墙是否放行 8000;板子和 PC 是否同网段 |
| `I2C scan` 扫不到设备 | 先烧 `board/i2c_scan`;S3-EYE 需确认代码里有 `pinMode(INPUT_PULLUP)` |
| 编译报 `'Wire' was not declared` | `#include "config.h"` 必须在 `#if USE_*` **之前**(否则宏未定义) |
| 编译报 `StaticJsonDocument` 不存在 | ArduinoJson 装成了 7.x,降到 6.x |
| 页面一直是"无数据" | 浏览器 `Network` 看 `/api/latest`;`Group ID` 是否与上传一致 |
| **核心下载极慢/失败** | 见 §6.3 |

### 6.3 ESP32 核心下载(国内网络)

ESP32 核心有 **1.5GB+**(工具链 394MB + riscv32 616MB + 8 个 libs 包),从 GitHub 拉经常失败。

**方法:改写本地索引走加速镜像**
```python
# 把 Arduino15/package_esp32_index.json 里的 GitHub URL 加镜像前缀
p = r'C:\Users\<你>\AppData\Local\Arduino15\package_esp32_index.json'
s = open(p, encoding='utf-8').read()
s = s.replace('"https://github.com/', '"https://ghproxy.net/https://github.com/')
open(p, 'w', encoding='utf-8').write(s)
```
大文件用 `curl -C -` 断点续传,放进 `Arduino15/staging/packages/` 让 arduino-cli 识别。

---

## 7. 目录结构

```
D:\kechengrenwu\123\
├── README.md                  # 本文件
├── .gitignore                 # 排除 config.h / data.json / venv
├── docs\
│   └── arduino-ide-setup.md   # Arduino IDE 安装 + 打开 .ino + 烧录全流程(新手看这个)
├── board\
│   ├── imu_http\              # 主 sketch(文件夹名必须与 .ino 同名)
│   │   ├── imu_http.ino       # S3-EYE 采集 + WiFi 上传 + 重力自动校准
│   │   ├── config.h           # 你的实际配置(含 WiFi 密码,已被 gitignore)
│   │   └── config.h.example   # 配置模板
│   ├── i2c_scan\
│   │   └── i2c_scan.ino       # I2C 扫描 + 传感器识别(排查用)
│   ├── qma_diag\
│   │   └── qma_diag.ino       # QMA7981 诊断:量程扫描 + 原始值(排查数值不对时用)
│   └── serial_test\
│       └── serial_test.ino    # 最小串口测试(排查 USB CDC 是否正常)
├── build\                     # 编译产物(.bin/.elf/.map),已 gitignore
├── server\
│   ├── app.py                 # Flask 接收 + 查询 + 页面
│   ├── requirements.txt
│   ├── templates\index.html    # Web 页面(自动刷新,蓝色 simulated 徽章)
│   ├── static\style.css       # 样式
│   └── data.json              # 运行时生成,落盘原始记录
├── simulator\
│   └── send_sim.py            # PC 端模拟器(无板子时先用)
└── scripts\
    ├── start_server.bat       # 一键起服务(自动 venv + 端口检查)
    ├── start_demo.bat         # 一键起服务 + 模拟器(双窗口)
    ├── start_simulator.bat    # 仅起模拟器
    ├── find_local_ip.py       # 列本机 IPv4 + 给出 config.h 写法
    ├── health.py              # 探测 /api/health 和 /api/latest
    └── push_to_github.bat     # 一键推送到 GitHub
```

---

## 8. 辅助脚本速查

| 脚本 | 何时用 | 关键行 |
|------|--------|--------|
| `python scripts/find_local_ip.py` | 决定 `SERVER_HOST` 填啥时 | 列举本机 IPv4,给你一行 `#define` |
| `scripts\start_server.bat` | 想跑 Web 但不跑模拟器 | 自动 venv / 端口检查 |
| `scripts\start_demo.bat`     | "我啥都没但想看页面动起来" | 自动拉双窗口 |
| `scripts\start_simulator.bat` | 服务已起,只想加模拟器 | 启动 1 个窗口 |
| `python scripts/health.py`   | 怀疑服务挂了 / 配置错 | 打印 `/api/health` 与 `/api/latest`,给出 last_seen 时长 |

---

## 9. 提交清单(对应周任务卡"提交与迁移")

- ✅ `board/imu_http/imu_http.ino` + `board/imu_http/config.h`(去敏感信息)
- ✅ `board/i2c_scan/i2c_scan.ino`(传感器识别记录)
- ✅ `server/app.py` 等
- ✅ 一条真实观测日志(打印的串口 + data.json 截屏 + 页面截屏)
- ✅ 个人修改说明(比如改了采样率、字段名、加了温度)
- ✅ 个人项目选定的设备数据(本仓库展示 IMU 6 轴 + 温度)