# 开发板 IMU 传感数据采集与 Web 展示系统

> 课程任务(共 4 周):把开发板的真实 IMU 传感数据经 WiFi 传到本机(充当服务器)再用浏览器查看;随后依次加上远程采集指令、按键触发与本地反馈、自然语言查询。
>
> 本仓库提供 **板端代码**(ESP32-S3-EYE + 板载 **QMA7981**)、**服务端代码**(Python 本机服务)、**Web 页面**和 **PC 模拟器**(无传感器时也能联调)。
>
> **进度**:第 1 周 采集与展示 ✅ · 第 2 周 远程采集指令 ✅ · 第 3 周 按键触发与反馈 ⏳ · 第 4 周 自然语言查询 ⏳

---

## ⏬ 三阶段路径

任务卡要求"先完成一个真实传感源与一种已验证网络,再补足其他"。

| 阶段 | 状态 | 用什么 | 结果 |
|------|------|--------|------|
| **A · PC 模拟器** | ✅ 已通过 | `simulator/send_sim.py` | 无板子时先跑通链路,Web 上看到 sin 波形 |
| **B · 板端演示模式** | ✅ 已通过 | `config.h` 里 `USE_QMA7981=0` | 物理板联通链路,Web 显示 `simulated` 蓝色徽章 |
| **C · 真实传感器** | ✅ **当前阶段** | `USE_QMA7981=1`,板载免接线 | 静止时三轴模长 ≈ 1g,Web 显示 `ok` |

> 章节对应:阶段 A = §2 + §3;阶段 B = §4;阶段 C = §4.3 + §5。

---

## 0. 整体架构

```
上传链路  [ESP32-S3 + 板载 QMA7981] --WiFi POST /api/data--> [本机 Flask] --GET--> [浏览器]

指令链路  [浏览器] --POST /api/task--> [Flask] --GET /api/command 1s 轮询--> [ESP32-S3]
                       request_id            <-------- POST /api/ack 回执 --------
```

**三端分工**:

| 端 | 职责 | 产物 |
|----|------|------|
| 板端 | 采 IMU 原始值,加时间戳和分组 ID,WiFi HTTP POST;**第 2 周**起轮询领取并执行远程指令 | `board/imu_http/imu_http.ino` |
| 服务端 | 收数据 → 落盘 → 提供查询 API 与首页;**第 2 周**起维护任务状态机 | `server/app.py` |
| 浏览器 | 拉最新值,显示"无数据/超时/失败"三态;**第 2 周**起下发采集指令并跟踪 `request_id` | `server/templates/index.html` |

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
- 板端默认 **5Hz 上传**(200ms 一条),前端默认 **200ms 拉取**。
- 静态资源(`/static/*`)禁用缓存,改完 JS/CSS 刷新页面即生效。

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

**第 4 周:自然语言查询**

| 接口 | 说明 |
|------|------|
| `POST /api/nlq` | 一句话进,答案出。体:`{text, group_id, wait}`;返回 `{intent, parsed, answer, data, task}` |

支持的意图:`latest`(当前值)/ `stats`(统计)/ `count`(数据量)/ `device_status`(在线吗)/
`events`(按键次数)/ `sample`(采集一次)/ `pause` / `resume` / `help`。
解析发生在 `server/nlq.py` —— **纯规则匹配,不调用任何大模型 API,断网也能跑**,
并把命中的关键词一并返回,判错了页面上一眼看得出。
动作类(`sample`/`pause`/`resume`)复用第 2 周的 `_new_task()`,与"远程采集任务"卡片同一条代码路径。

**第 2 周:远程采集指令(命令通道)**

| 接口 | 说明 |
|------|------|
| `POST /api/task` | 创建任务(体:`{group_id, action}`,action = `sample`/`pause`/`resume`),返回 `request_id` |
| `GET /api/command` | **板端轮询**领取待执行任务(1s 一次),无任务时返回空 |
| `POST /api/ack` | 板端回执(已接收 / 执行完成 / 失败) |
| `GET /api/task/<request_id>` | 查单个任务状态与耗时 |
| `GET /api/tasks?limit=10` | 任务历史 |

任务状态机:

```
pending ──> received ──> completed
   │            └──────> failed
   └──(超过 15s 未被领取)──> timeout
```

- 任务持久化在 `server/tasks.json`。
- **超时任务绝不回填旧数据**:`timeout` 时 `completed_at_ms=None`、`record_index=None`,页面上不会把上一次的观测标成本次结果。
- 板端断网时任务停在 `pending`,页面显示"等待设备领取"。

**第 3 周:按键触发事件(事件通道)**

| 接口 | 说明 |
|------|------|
| `POST /api/event` | 板端上报一次本地触发(`event_id` / `local_confirmed_at_ms` / `local_uptime_ms`) |
| `GET /api/events?group_id=G03` | 事件列表(前端"按键触发事件"卡片) |
| `POST /api/event/<id>/ack` | Web 端回应(远端确认) |
| `POST /api/event/<id>/cancel` | Web 端取消 |
| `GET /api/event/pending?device_id=...` | **板端轮询**领取回应/取消命令 |

事件状态机(板端本地视角):

```
EV_IDLE ──按下 BOOT──> EV_LOCAL ──POST 成功──> EV_SENT ──ack──> EV_ACKED
                          │                                 └──cancel─> EV_CANCELLED
                          └──POST 失败(断网)──> 停在 EV_LOCAL
```

- **核心设计**:`local_confirmed_at_ms`(本地确认)与 `received_at_ms`(服务端收到)
  是两个独立字段,实测延迟 93~250 ms,可证明两者分离。
- **断网时停在 `EV_LOCAL`**:屏幕显示黄色 + 红边框 + `NOT delivered`,
  绝不会显示"对方已收到";服务端也不会凭空生成该事件的记录。
- 事件持久化在 `server/events.json`。

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
- **远程采集任务**(第 2 周):
  - 按钮:`🎯 采集一次`、`⏸ 暂停周期上报`、`▶ 恢复周期上报`
  - 当前任务状态区:`request_id` + 状态流转(已提交 → 设备已接收 → 完成/失败/超时)+ 耗时
  - 超时明确提示,**不把旧数据标成本次完成**
  - 最近任务历史列表(含状态与耗时)
- **自然语言查询**(第 4 周):
  - 输入框 + 7 个示例按钮(当前值 / 5 分钟内最大 / 设备在线? / 数据量 / 按键次数 / 🎯 采集一次 / 帮助)
  - 回答区同时显示**意图 + 命中的关键词 + 置信度**,判错了用户一眼看得出
  - 查询类秒回;「采集一次」等动作类真的下发任务,并展示任务状态流转与 `request_id`
  - 最近 5 条问答留痕,便于当场复现
  - 解析在 `server/nlq.py`(纯规则),**不调用大模型 API,断网可用**

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
- 默认每 50ms 采一次(20Hz),每 200ms 算均值并上传一次(5Hz),故 `n_samples` 通常为 4
- 采样用 `while` 补帧:上一轮被 HTTP 拖长时把错过的采样补回,保证采样率不退化
- 上传日志每秒最多打印 1 行(含真实上传频率与 HTTP 耗时),避免 Serial 阻塞主循环
- 上传字段:`ts_ms`、`group_id`、`device_id`、`status`、`acc_*_g`(g)、`acc_*`(m/s²)、`rssi`、`n_samples`
- **启动时自动做重力校准**:静止时三轴模长恒等于 1g,据此反推真实灵敏度(兼容不同批次芯片)
- WiFi 断连自动重连;HTTP 失败打印状态码
- 传感器读不到时 `status="sensor_fail"`;演示模式 `status="simulated"`(Web 显示蓝色徽章)
- **命令通道**(第 2 周):每 1s 轮询 `GET /api/command`,领到任务后执行并 `POST /api/ack` 回执
  - `sample`:立即采一组并上传,带上该 `request_id`(端到端实测约 0.6s)
  - `pause` / `resume`:暂停/恢复周期上报,**命令通道在暂停期间照常工作**,所以暂停时仍可"采集一次"

---

## 5. 当堂验证(对照周任务卡"当堂验证")

### 5.1 第 1 周:采集与展示

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

### 5.2 第 2 周:远程采集指令

**自动验证**(17 项,约 60 秒):

```bash
cd D:\kechengrenwu\123
.venv\Scripts\python.exe scripts\verify_week2.py            # 自动项
scripts\verify_week2.py --manual                            # 需人工配合的 T5
```

覆盖:T0 在线 / T1 周期上报 / T2 采集一次 / T3 暂停 / T4 暂停中仍可采集 / T6 恢复 / T7 超时不污染旧值。
结果自动写入 `docs/week2-verification.md`。

**必须人工配合的两项**:

| 项 | 操作 | 期望 |
|----|------|------|
| T5 改变设备状态 | 晃动或翻转板子 → 立刻点"采集一次" | 新观测数值确实变化,且带本次 `request_id` |
| T7 真实设备离线 | **拔掉板子 USB** → 点"采集一次" | 状态走 等待 → **超时**;旧值**不会**被标成本次结果 |

> T7 自动脚本里用的是虚构设备 `ghost-offline-01` 做等效逻辑验证;
> 上面这一项是**真实网络中断**的证据,任务卡要求,建议补一次截图。

### 5.3 第 3 周:按键触发与物理反馈闭环

完整验证报告见 `docs/week3-verification.md`。核心是**本地确认**与**远端收到**分开证明:

| 验证项 | 操作 | 期望 |
|--------|------|------|
| 本地立即确认 | 按 BOOT | 屏幕下半部**变黄** + 红边框,串口 `[EV] key pressed, local confirmed` |
| 送达 | 服务在线时按 BOOT | 随即**变青**(`EV_SENT`),服务端事件延迟 93~250 ms |
| 远端回应闭环 | 页面"按键触发事件"卡片点**回应** | 1~2 秒内屏幕**变绿**,串口 `[EV] remote acked` |
| 取消 | 点**取消** | 屏幕变红(`EV_CANCELLED`) |
| **断网本地确认** | 停掉 Flask 服务后按 BOOT | 屏幕**稳定停在黄色** + 红边框 + `NOT delivered` |
| **不伪造远端证据** | 恢复服务后查 `/api/events` | 离线期间的触发**不在列表里**,事件总数不变 |

**验收要点**:断网时本地仍能确认触发,但**绝不能**显示"对方已收到"。
板端状态只有拿到服务端回执才会越过 `EV_LOCAL`。

### 5.4 第 4 周:自然语言查询与请求采集

完整验证报告见 `docs/week4-verification.md`。

```bash
python scripts/verify_week4.py        # 自动项(17 项,约 20 秒)
python server/nlq.py                  # 只测意图解析,13/13
```

覆盖:12 句话的意图识别、**统计数值与 `/api/stats` 逐位一致**、动作类确实创建任务。

| 验证项 | 操作 | 期望 |
|--------|------|------|
| 查询类 | 页面"自然语言查询"卡片输入「现在加速度是多少」 | 秒回三轴值与"多久之前" |
| 可解释 | 看回答下方的小标签 | 显示意图、命中的关键词、置信度 |
| 统计一致 | 「最近一天合加速度的最大值」 | 与"历史数据分析"卡片同窗口数值**完全相同**(脚本已逐位比对) |
| 没听懂时 | 输入「帮我看看天气」 | 明说没听懂 + 给出能做什么,不瞎猜 |
| **采集一次** | 板子在线时输入「采集一次」 | 真的下发任务并等回执(≤12s),回答里给出本次采样值与耗时 |
| **离线不谎报** | 板子离线时输入「采集一次」 | 如实说"没等到回执",**不会**出现"成功"字样 |

> **最关键的一条**:「命令已下发」≠「已采集成功」。
> 板子离线时任务停在 `pending`,答案里绝不出现"成功",旧数据也不会被标成本次结果。

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
| **静止时模长只有 0.23g,但数值很稳定** | ⚠️ **校准被污染**:插 USB / 拿放板子时板子在动,启动校准把"晃动时的模长"当成了 1g,灵敏度被高估数倍(实测约 4500 LSB/g,标称 1024)。**表面稳定、实则整体错 4 倍,极难发现** | 板子**静止放好后按 RST 复位**重校准。新版固件已加三重保护:静止判定(波动 <3% 才算稳)+ 取中位数 + 合理区间(标称 0.5~2 倍,越界则退回标称值并报警) |
| **`arduino-cli board list` 看不到 ESP32**(只有 COM1/COM2) | 插的那根线/那个口**只供电不传数据** | 换一根确认能传数据的线,或换 USB 口;烧录必须能枚举到 ESP32 的 USB CDC 端口 |
| **上传只有 0.5Hz**(代码明明写了 200ms) | S3-EYE 是**原生 USB CDC**,主机没打开串口监视器时 `Serial` 写入会**阻塞等待主机取数据**,把主循环卡住 ~1.8s。表现很反直觉:**开着串口监视器反而是 5Hz,关掉就掉到 0.5Hz** | `setup()` 里加 `Serial.setTxTimeoutMs(0)`(写不进就丢弃,绝不阻塞);并对高频日志做**每秒 1 条**的节流 |
| **烧录后 COM 口从系统消失** | S3-EYE 偶发 USB 枚举失败 | **拔插 USB**;不行就手动进下载模式:按住 BOOT → 按 RST → 松 RST → 松 BOOT |
| **屏幕背光不亮**(内容其实已画出) | 背光由 **AO3401A(P 沟道 MOS)** 驱动,栅极接 GPIO48,**低电平才导通点亮**,与直觉相反 | `BL_ON()` 定义为 `digitalWrite(LCD_BL, LOW)` |
| **按一下 BOOT 产生多条事件** | 用 `if (key_low && 已过防抖时间)` 判断,**按住不放会反复触发** | 改成**下降沿触发**(`key_low && !key_last`) |
| **时间戳算出几十亿毫秒的荒谬延迟** | ESP32 的 `long` 是**32 位**(最大 21 亿),而墙上时钟毫秒约 **1.79e12**,`(long)(server_time_ms - millis())` 直接溢出 | 偏移量与时间戳一律用 `long long` / `unsigned long long` |

### 6.2 通用排错

| 现象 | 排查点 |
|------|--------|
| 板子串口反复 `WiFi disconnected` | SSID/密码错;2.4G/5G 频段;WiFi 信号弱 |
| `HTTP -1` / `connect fail` | 服务端 IP 是否对;PC 防火墙是否放行 8000;板子和 PC 是否同网段 |
| `I2C scan` 扫不到设备 | 先烧 `board/i2c_scan`;S3-EYE 需确认代码里有 `pinMode(INPUT_PULLUP)` |
| 编译报 `'Wire' was not declared` | `#include "config.h"` 必须在 `#if USE_*` **之前**(否则宏未定义) |
| 编译报 `StaticJsonDocument` 不存在 | ArduinoJson 装成了 7.x,降到 6.x |
| 页面一直是"无数据" | 浏览器 `Network` 看 `/api/latest`;`Group ID` 是否与上传一致 |
| **改了 JS/CSS 但页面没变化** | 浏览器缓存了旧静态资源。已加 `no-store` 响应头;仍不生效就 `Ctrl+F5` 强刷 |
| **历史曲线一跳一跳** | 窗口滑动时旧点被挤出、新点进入,全体左移,而 x 轴动画被设为 `duration:0` → 硬瞬移;叠加每 200ms 整体替换 `datasets` 触发入场动画重放。已改为:真实时间轴 + 按绝对时间网格分桶 + 复用 dataset 对象 + 历史图独立降频到 1s |
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
│   ├── arduino-ide-setup.md   # Arduino IDE 安装 + 打开 .ino + 烧录全流程(新手看这个)
│   ├── week2-verification.md  # 第 2 周验证报告(脚本自动生成,含原始输出)
│   └── week3-verification.md  # 第 3 周验证报告(按键闭环 + 离线本地确认)
│   └── week4-verification.md  # 第 4 周验证报告(自然语言查询 + 不谎报成功)
│   └── 项目完整记录.md         # 开发全过程记录:功能/验证/排错/待办
├── board\
│   ├── imu_http\              # 主 sketch(文件夹名必须与 .ino 同名)
│   │   ├── imu_http.ino       # S3-EYE 采集 + WiFi 上传 + 重力自动校准
│   │   ├── config.h           # 你的实际配置(含 WiFi 密码,已被 gitignore)
│   │   └── config.h.example   # 配置模板
│   ├── lcd_key_probe\         # 探针:LCD 引脚 + 背光极性 + BOOT 键(第 3 周排错用)
│   └── key_scan\              # 探针:扫描板载按键实际 GPIO(确认 BOOT=GPIO0)
│   ├── i2c_scan\
│   │   └── i2c_scan.ino       # I2C 扫描 + 传感器识别(排查用)
│   ├── qma_diag\
│   │   └── qma_diag.ino       # QMA7981 诊断:量程扫描 + 原始值(排查数值不对时用)
│   └── serial_test\
│       └── serial_test.ino    # 最小串口测试(排查 USB CDC 是否正常)
├── build\                     # 编译产物(.bin/.elf/.map),已 gitignore
├── server\
│   ├── app.py                 # Flask 接收 + 查询 + 任务指令 + 事件 + 自然语言查询
│   ├── nlq.py                 # 第 4 周:意图解析(纯规则,可离线单测)
│   ├── requirements.txt
│   ├── templates\index.html    # Web 页面(第 2 周远程采集 + 第 3 周事件 + 第 4 周自然语言查询卡片)
│   ├── static\
│   │   ├── css\style.css      # 样式
│   │   ├── js\                # config / utils / api / charts / app
│   │   └── vendor\chart.umd.min.js  # Chart.js 本地化,不依赖 CDN
│   ├── tasks.json             # 第 2 周任务持久化(运行时生成)
│   ├── events.json            # 第 3 周事件持久化(运行时生成)
│   └── data.json              # 运行时生成,落盘原始记录(**JSONL,每行一条**)
├── simulator\
│   └── send_sim.py            # PC 端模拟器(无板子时先用)
└── scripts\
    ├── start_server.bat       # 一键起服务(自动 venv + 端口检查)
    ├── start_demo.bat         # 一键起服务 + 模拟器(双窗口)
    ├── start_simulator.bat    # 仅起模拟器
    ├── find_local_ip.py       # 列本机 IPv4 + 给出 config.h 写法
    ├── health.py              # 探测 /api/health 和 /api/latest
    ├── verify_week2.py        # 第 2 周自动验证(17 项,--manual 跑人工项)
    └── verify_week4.py        # 第 4 周自动验证(意图 + 数值一致性 + 动作类不谎报)
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
| `python scripts/verify_week2.py` | 第 2 周验收 | 自动跑 17 项并生成 `docs/week2-verification.md`;`--manual` 只跑需人工配合的 T5 |
| `python scripts/verify_week4.py` | 第 4 周验收 | 17 项:意图识别 + 统计数值与 `/api/stats` 逐位比对 + 动作类不谎报成功 |

---

## 9. 提交清单(对应周任务卡"提交与迁移")

- ✅ `board/imu_http/imu_http.ino` + `board/imu_http/config.h`(Wi-Fi 密码等敏感信息已剥离,改用 `config.h` 本地配置)
- ✅ `board/i2c_scan/i2c_scan.ino`(传感器识别记录:扫出 I²C 地址 `0x12` → QMA7981)
- ✅ `server/app.py` 等(含第 2 周任务 API)
- ✅ `server/data.json` 真实观测记录(已累计 1 万+ 条 `G03` 真实数据)
- ⚠️ **串口日志 / 页面截图** —— 待补,建议放在 `docs\` 下
- ✅ 个人修改说明 —— 见下
- ✅ 个人项目选定的设备数据 —— **QMA7981 三轴加速度**(非 6 轴,无陀螺仪;**无温度传感器**)

### 9.1 个人修改说明

相对课程原始模板,本项目做了这些改动:

**板端**(`board/imu_http/`)
1. **换传感器驱动**:板载是 **QMA7981**(I²C `0x12`),不是模板默认的 MPU6050(`0x68`)。自行实现驱动与量程换算。
2. **启动时重力自动校准**:静止时三轴模长恒等于 1g,据此反推真实 LSB 灵敏度(实测 414.2 LSB/g,标称 1024),兼容不同批次芯片的差异。
3. **采样/上传频率**:50ms 采样(20Hz)、200ms 上传(5Hz),`n_samples` 通常为 4;采样用 `while` 补帧,被 HTTP 拖长时把错过的采样补回。
4. **双单位上传**:同时发 `acc_*_g`(g)与 `acc_*`(m/s²),前端不用再换算。
5. **扩展字段**:增加 `rssi`、`n_samples`、`uptime_s`、`sensor` 型号。
6. **修复 USB CDC 串口阻塞**(关键):S3-EYE 主机未开串口监视器时 `Serial` 写入会阻塞主循环约 1.8s,导致上传从 5Hz 掉到 0.5Hz。加 `Serial.setTxTimeoutMs(0)` + 日志限流解决,详见 §6.1。
7. **命令通道**(第 2 周):轮询 `GET /api/command` 执行 `sample`/`pause`/`resume`,回执 `POST /api/ack`;端到端响应约 0.6s。

**服务端**(`server/app.py`)
8. 第 2 周任务 API 与状态机(`pending→received→completed/failed/timeout`),持久化到 `tasks.json`;**超时任务不回填旧数据**。
9. 静态资源返回 `no-store`,改完 JS/CSS 刷新即生效(否则浏览器一直用旧文件)。
10. `data.json` 采用 **JSONL**(每行一条)追加写,抗进程强杀、便于流式核对。
11. **第 4 周自然语言查询**:`server/nlq.py` 做规则式意图解析 —— 不调用大模型 API、断网可跑,
    并把命中的关键词一并返回(页面展示成标签),判错了用户一眼看得出而不是黑箱。
    执行端 `/api/nlq` 的动作类(`sample`/`pause`/`resume`)复用第 2 周的 `_new_task()`,
    与"点按钮"完全同一条代码路径;统计口径与 `/api/stats` 共用 `_describe_all()`,
    保证"问一句话"和"看统计表"永远是两个相同的数字。
12. 统计逻辑从 `/api/stats` 里抽成 `_filter_rows()` + `_describe_all()` 两个函数,
    `scripts/verify_week4.py` 会逐位比对两条路径的输出,改歪了立刻变红。

**前端**(`server/static/`)
11. Chart.js **本地化**到 `vendor/`,不依赖 CDN。
12. 刷新频率默认 200ms,实时窗口 300 点、历史 800 点,渲染帧率 144fps。
13. 历史图改用**真实时间轴** + 按绝对时间网格分桶聚合 + 复用 dataset 对象,消除窗口滑动时的跳格与闪烁(详见 §6.2)。