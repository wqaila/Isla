# 第 3 周验证报告：按键触发与物理反馈闭环

> 验证时间：2026-10-09
> 设备：ESP32-S3-EYE（`esp32s3-eye-01`，分组 G03）
> 任务卡核心要求：**本地确认** 与 **远端收到** 必须分开证明 ——
> 断网时本地仍能确认触发；没有远端证据时不得显示"对方已收到"。

---

## 一、结论

| 验证项 | 结果 | 关键证据 |
|--------|------|----------|
| 按键触发 → 本地立即确认 | ✅ | 串口 `[EV] key pressed, local confirmed: ...-15871-1` |
| 一次按键 = 一条事件 | ✅ | `[DBG] isr=3 key=3`（3 次按下 → 3 条，修复前是 13 条） |
| 本地 → 服务端送达延迟 | ✅ | **250 / 93 / 152 ms**（修复前是荒谬的 1791001362866 ms） |
| 远端回应 → 回到板端 | ✅ | 服务端 ack → `[EV] remote acked` → 状态 `对方已回应(3)` |
| **断网时本地仍能确认** | ✅ | `[EV] key pressed, local confirmed` + `[EV] post failed code=-1, stay LOCAL` |
| **无远端证据不得显示"已收到"** | ✅ | 状态停在 `本地已确认(1)`，屏幕黄色 + 红边框 + `NOT delivered` |
| **服务端不伪造"收到"记录** | ✅ | 离线期间 2 条事件，服务端事件总数 **仍为 31**，未新增 |

---

## 二、状态机设计（本地视角与远端视角分离）

板端维护 5 个状态，**只有拿到服务端回执才能越过 `EV_LOCAL`**：

```
EV_IDLE        待触发（深蓝）
   │ 按下 BOOT
   ▼
EV_LOCAL       本地已确认（黄色 + 红边框，"NOT delivered"）
   │ POST /api/event 成功
   ▼
EV_SENT        已送达，等回应（青色）
   │ 轮询到 ack / cancel
   ▼
EV_ACKED       对方已回应（绿色）      EV_CANCELLED  已取消（红色）
```

服务端事件记录里，`local_confirmed_at_ms`（板端本地确认时刻）与
`received_at_ms`（服务端真正收到的时刻）是**两个独立字段**，
可算出真实延迟，用来证明"本地确认"确实早于"远端收到"。

---

## 三、实测数据

### 3.1 在线路径（服务正常）

```
[EV] key pressed, local confirmed: esp32s3-eye-01-15871-1
[EV] delivered esp32s3-eye-01-15871-1
[EV] key pressed, local confirmed: esp32s3-eye-01-16644-2
[EV] delivered esp32s3-eye-01-16644-2
[EV] key pressed, local confirmed: esp32s3-eye-01-17205-3
[EV] delivered esp32s3-eye-01-17205-3
[DBG] IO0=1 isr=3 poll_low=1 key=3 state=已送达(2)
```

服务端对应记录：

| event_id | status | local_confirmed_at_ms | received_at_ms | 延迟 |
|---|---|---|---|---|
| `esp32s3-eye-01-17205-3` | acked | 1791516372694 | 1791516372944 | **250 ms** |
| `esp32s3-eye-01-16644-2` | received | 1791516372312 | 1791516372405 | **93 ms** |
| `esp32s3-eye-01-15871-1` | received | 1791516371539 | 1791516371691 | **152 ms** |

远端回应（服务端 → 板端）：

```
POST /api/event/esp32s3-eye-01-17205-3/ack  → status: acked
GET  /api/event/pending?device_id=...       → 板端领走，队列清空
[EV] remote acked
[DBG] state=对方已回应(3)
```

### 3.2 离线路径（停掉 Flask 服务，板子仍通电）

```
[EV] key pressed, local confirmed: esp32s3-eye-01-105038-1
[EV] post failed code=-1, stay LOCAL
[DBG] IO0=1 isr=3 poll_low=0 key=1 state=本地已确认(1) up=101s
[EV] key pressed, local confirmed: esp32s3-eye-01-111151-2
[EV] post failed code=-1, stay LOCAL
[DBG] IO0=1 isr=3 poll_low=0 key=2 state=本地已确认(1) up=107s
```

屏幕表现：**整块黄色 + 红色双边框 + `Local confirmed / NOT delivered`**，
持续保持，没有变成青色或绿色。

恢复服务后核对：事件总数 **31 → 31**，两条离线事件 `105038-1`、`111151-2`
**均不在服务端** —— 没有伪造任何"远端已收到"的记录。

---

## 四、过程中修复的 4 个真实缺陷

### 1. 背光极性反了（屏幕全黑）
S3-EYE 背光由 **AO3401A（P 沟道 MOS）** 驱动，栅极接 GPIO48，
**低电平才导通点亮**。初版给了 `HIGH`，背光一直灭 —— 内容其实早画出来了，只是看不见。

### 2. 按住 BOOT 会重复触发
旧逻辑 `if (key_low && now - ev_key_ms > 300)`，按住不放每 300ms 触发一次
（按 3~5 下却产生 13 条事件）。改为**下降沿触发**，实测 3 次按下 = 3 条事件。

### 3. 时间戳 32 位溢出（会让验收翻车）
ESP32 的 `long` 是 **32 位**（最大 21 亿），而墙上时钟毫秒约 **1.79e12**。
`time_offset_ms = (long)(server_time_ms - millis())` 直接溢出，
导致"本地确认 → 收到"的延迟算出 `1791001362866 ms` 这种荒谬值，
**本地确认时刻无法与远端收到时刻对比** —— 恰好违背第 3 周核心要求。

修法：`time_offset_ms` 改 `long long`、`ev_local_wall_ms` 改 `unsigned long long`，
赋值处显式转 64 位。修复后延迟变为 93~250 ms。

### 4. "本地反馈"做成了故障
初版用**关背光闪烁**做触发反馈，效果就是整屏一黑一黑，看起来像死机。
改为**状态色块在本色 ↔ 白色之间闪动**（150ms），背光始终常亮。

---

## 五、硬件事实（S3-EYE 实测）

| 项 | 结论 |
|---|---|
| LCD | ST7789，SCLK21 / MOSI47 / DC43 / CS44 / **BL48（低电平点亮）** |
| BOOT 键 | GPIO0，`INPUT_PULLUP` + 下降沿，实测灵敏（`key_scan` 探针 24 次全中） |
| 4 键 ADC 阵列 | 原理图标 GPIO1（分压 1.98/0.82/0.38V），实测浮空噪声大，**大概率未焊接，不可用** |
| 触摸 | 无 |
| 独立用户 LED | 无（只有 LCD 背光 BL48 可作光源） |

---

## 六、复现命令

```bash
# 1) 启动服务
cd server && .venv/Scripts/python.exe app.py > server.log 2>&1

# 2) 在线路径：按 BOOT → 页面"按键触发事件"卡片出现 received → 点"回应"
#    观察屏幕：黄 → 青 → 绿

# 3) 离线路径：停掉服务（taskkill 占用 8000 的 PID）
#    按 BOOT → 屏幕必须停在黄色 + 红边框 + NOT delivered

# 4) 抓板端日志（注意：monitor 连接会让 S3-EYE 复位）
arduino-cli monitor -p COM5 -c baudrate=115200
```

---

## 七、已知边界

- **离线期间的事件不会补报**：当前设计下，POST 失败即丢弃，恢复网络后也不会重发。
  好处是绝不伪造"已收到"；代价是离线期间的触发在服务端查不到。
  若任务卡要求"恢复后补传"，需要另加本地待发队列（并明确标注 `delivered_late`）。
- 串口监视器连接会让 S3-EYE 复位，`ev_state` 回到"待触发"。
- 每次 HTTP 上传实测耗时 150~350ms，主循环大半时间卡在 HTTP 里，
  所以按键必须走**中断置位 + 轮询兜底**，纯轮询会漏掉短按键。
