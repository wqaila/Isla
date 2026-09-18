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

### 1.2 硬件(等老师发放或自备)
- ESP32-DevKitC(任何 ESP32 都行)
- MPU6050 模块(GY-521),I2C 接口
- 杜邦线 4 根

### 1.3 接线(MPU6050 → ESP32)
| MPU6050 | ESP32 |
|---------|-------|
| VCC     | 3.3V  |
| GND     | GND   |
| SDA     | GPIO21(默认 I2C SDA) |
| SCL     | GPIO22(默认 I2C SCL) |

> AD0 留空(地址 0x68);若接 3.3V 则地址 0x69,代码里改 `MPU_ADDR`。

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
- `POST /api/data` 接收板端上传;
- `GET /api/latest?group_id=G03` 查最新一条;
- `GET /api/history?group_id=G03&limit=60` 查最近 60 条;
- `GET /api/groups` 看都有哪些组在上传。

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

## 4. 板端(拿到 ESP32 + MPU6050 后)

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

### 4.1 接线(ESP32 ← IMU 模块)

先物理接上,才能识别型号。绝大多数 I²C 的 6 轴模块引脚定义相同:

| 传感器模块引脚 | ESP32 引脚 | 说明 |
|--------------|------------|------|
| VCC          | 3.3V       | **不要接 5V**,多数 IMU 是 3.3V 供电 |
| GND          | GND        | 必须共地 |
| SDA          | GPIO21     | 默认 I²C SDA |
| SCL          | GPIO22     | 默认 I²C SCL |
| AD0 / SA0    | 悬空       | 决定地址 0x68 / 0x69;悬空通常是 0x68 |

> 模块上有的标 `SCL/SDA`,有的标 `SCK/SDI`,含义相同。**接线前先断电**。

### 4.2 识别传感器型号(型号不确定时必做)

用 Arduino IDE 打开 **`board/i2c_scan/i2c_scan.ino`** → 选 `ESP32 Dev Module` → 上传 → 打开串口监视器(115200)。

它每 3 秒扫一次 I²C 总线,打印地址和型号线索:
```
--- scan ---
  地址 0x68   WHO_AM_I(0x75)=0x68   -> MPU6050
```
- 出现 `-> MPU6050`:型号标准,后续直接用项目默认代码。
- 出现别的型号(如 `ICM-20602`、`BMI160`):把结果告诉我,我帮你改驱动寄存器。
- **什么都没扫到**:查 VCC 是否 3.3V、SDA/SCL 是否接反、杜邦线是否插紧。

### 4.3 配置 & 模式开关

1. `board/imu_http/config.h` 已自动生成,**只需改两处 WiFi**:
   ```cpp
   #define WIFI_SSID       "改成你的WiFi名"      // ← 必改(ESP32 仅支持 2.4GHz)
   #define WIFI_PASS       "改成你的WiFi密码"    // ← 必改
   #define SERVER_HOST     "10.1.41.110"        // 已自动填好你的电脑 IP
   #define SERVER_PORT     8000
   #define GROUP_ID        "G03"
   #define DEVICE_ID       "esp32-imu-01"
   #define USE_MPU6050     1                    // 1=读真实传感器
   ```
2. **`USE_MPU6050` 决定数据来源**(对应三阶段路径 B/C):
   ```cpp
   #define USE_MPU6050     1   // 接了传感器:读真实 IMU,status="ok"
   // #define USE_MPU6050  0  // 还没接:用 sin 合成,status="simulated"
   ```

### 4.4 烧录 & 验证

1. Arduino IDE 打开 `board/imu_http/imu_http.ino`,选开发板 `ESP32 Dev Module`,端口选实际 COM 口,点击"上传"。
2. 打开 `工具 → 串口监视器`(115200 波特),看到 `HTTP 200` 表示成功。
3. 把传感器平放静止,串口应打印 `acc≈(0.0, 0.0, 9.8)`,Web 页面状态显示 `ok`。

**库依赖(Arduino IDE → 工具 → 管理库):**
- `ArduinoJson` **必须选 6.x 版本**(代码用的是 `StaticJsonDocument`,7.x 已移除该 API)。
- `Wire` 随 ESP32 板支持包自带,无需另装。

**板端逻辑要点**:
- 默认每 50ms 采一次(20Hz),每 1s 算均值并上传一次。
- 每次上传带 `ts_ms`(本地毫秒时间戳)、`group_id`、`device_id`、`status`。
- WiFi 断连自动重连;HTTP 失败打印状态码便于排错。
- 真实模式没接传感器时 `status="sensor_fail"`,Web 显示**失败**。
- 演示模式 `status="simulated"`,Web 显示**蓝色徽章** + "正常(板端演示数据)"。

---

## 5. 当堂验证(对照周任务卡"当堂验证")

| 验证项 | 操作 | 期望 |
|--------|------|------|
| 采集值 | 看串口监视器 | 静止时 acc_z ≈ 9.8,acc_x/acc_y ≈ 0 |
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

| 现象 | 排查点 |
|------|--------|
| 板子串口反复 `WiFi disconnected` | SSID/密码错;2.4G/5G 频段;WiFi 信号弱 |
| `HTTP -1` / `connect fail` | 服务端 IP 是否对;PC 防火墙是否放行 8000;板子和 PC 是否同网段 |
| `I2C scan` 扫不到设备 | 先烧 `board/i2c_scan` 确认;查 VCC 是否 3.3V、SDA/SCL 是否反、线是否插紧 |
| 数值全是 0 | 传感器没初始化成功;I²C 引脚错;或型号不是 MPU6050 兼容 |
| 编译报 `StaticJsonDocument` 不存在 | ArduinoJson 装成了 7.x,降级到 6.x |
| 页面一直是"无数据" | 浏览器 `Network` 看 `/api/latest`;`Group ID` 是否与上传一致 |

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
│   │   ├── imu_http.ino       # ESP32 采集 + WiFi 上传(支持 USE_MPU6050=0 演示模式)
│   │   ├── config.h           # 你的实际配置(已生成,含 WiFi 密码,不进 git)
│   │   └── config.h.example   # 配置模板
│   └── i2c_scan\
│       └── i2c_scan.ino       # I2C 扫描 + IMU 型号识别(型号不确定时先烧这个)
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
    └── health.py              # 探测 /api/health 和 /api/latest
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