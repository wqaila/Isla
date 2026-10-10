# 第 2 周当堂验证报告

- 生成时间:2026-10-08 15:27:48
- 服务地址:`http://127.0.0.1:8000`  分组:`G03`  设备:`esp32s3-eye-01`
- 结论:**17/17 项通过**

## 逐项结果

| 项 | 结果 | 明细 |
|---|---|---|
| T0.1 服务在线 | ✅ PASS | /api/health ok, count=1695 |
| T0.2 设备在线 | ✅ PASS | device=esp32s3-eye-01 status=ok age=0s |
| T1.1 周期数据持续到达 | ✅ PASS | 8s 内新增 4 条(其中周期上报 4 条) |
| T2.1 状态流转完整 | ✅ PASS | 轨迹: pending→received→completed |
| T2.2 任务在超时前完成 | ✅ PASS | status=completed elapsed=8085 ms |
| T2.3 产生带 request_id 的新观测 | ✅ PASS | record=有, |a|=0.995 g, received_at=1791444419237 |
| T2.4 新观测晚于任务创建 | ✅ PASS | record.received_at - task.created_at = 8085 ms |
| T3.1 pause 命令被执行 | ✅ PASS | 轨迹: pending→received→completed, note='periodic paused' |
| T3.2 暂停后不再产生周期记录 | ✅ PASS | 9s 内新增周期记录 0 条 |
| T4.1 暂停期间采集任务仍能完成 | ✅ PASS | 轨迹: pending→received→completed, elapsed=7327 ms |
| T4.2 拿到本任务的新观测 | ✅ PASS | |a|=0.981 g |
| T6.1 resume 命令被执行 | ✅ PASS | 轨迹: pending→received→completed, note='periodic resumed' |
| T6.2 周期上报恢复 | ✅ PASS | 9s 内新增周期记录 1 条 |
| T7.1 任务最终判定为超时 | ✅ PASS | 轨迹: pending→timeout |
| T7.2 超时任务没有 completed_at | ✅ PASS | completed_at_ms=None |
| T7.3 超时任务未指向任何记录(旧值未被误标) | ✅ PASS | record_index=None |
| T7.4 没有记录被打上该 request_id | ✅ PASS | 未发现污染记录 |

## 人工配合的验证项(2026-10-10 已执行)

| 项 | 操作 | 结果 |
|---|---|---|
| T5 改变设备状态后采集 | 板子**平放旋转 90°**(不拿起、不翻面,避免冲击)后采集一次 | ✅ 见下方数据 |
| T7 真实设备离线版 | **拔掉板子 USB** 后下发"采集一次" | ✅ 见下方数据 |

### T5 实测数据(2026-10-10 10:10)

| | X | Y | Z | 合加速度 |
|---|---|---|---|---|
| 旋转前 | -2.905 | -5.861 | -7.198 | 9.726 |
| 旋转后 | -4.306 | -2.351 | -8.406 | 9.733 |
| 变化量 | 1.401 | **3.510** | 1.208 | **0.8%** |

- 三轴数值都明显变化(不是复旧值),且新观测**带本次 `request_id`**(`req-1791598220772-4281f0`,记录里可追溯到同一 id)。
- **关键判据**:合加速度几乎不变(偏离 1g 仅 0.8%)。静止时三轴模长恒等于重力,
  姿态改变只改变重力在各轴的**分配**,不改变**总量** —— 这一条反证读数物理正确,
  比单纯"数值变了"更有说服力(数值变也可能是变了错的)。

### T7 实测数据(2026-10-10 10:05)

拔掉 USB 后立即下发采集:

| 观测 | 结果 |
|---|---|
| 服务端确认离线 | 最后一条数据距今 65.5 秒,确认无新数据 |
| 12 秒等待后的即时状态 | `pending`,回答"命令已下发,当前状态 pending(板端还没回执)" |
| 任务最终状态 | `timeout`(见 `/api/tasks` 列表) |
| 是否返回了数据记录 | **否**(`record=None`)—— 旧值没有被标成本次结果 |
| 是否有记录被打上该 request_id | **否** —— 未污染任何历史数据 |

对照:同列表里板子在线时的三次采集均为 `completed`(754 / 1823 / 950 ms)。
说明"离线"与"在线"的区分来自真实回执,而不是时间巧合。

## 复现方式

```bat
cd D:\kechengrenwu\123
python scripts\verify_week2.py          :: 自动项(约 60 秒)
python scripts\verify_week2.py --manual :: 只跑 T5(人工晃动)
python scripts\verify_week2.py --all    :: 全部
```

## 原始输出

```
==============================================================
  第 2 周当堂验证 —— Web 远程采集指令与执行结果反馈
  时间: 2026-10-08 15:26:43   服务: http://127.0.0.1:8000
==============================================================

=== T0 前置检查 ===
  [PASS] T0.1 服务在线: /api/health ok, count=1695
  [PASS] T0.2 设备在线: device=esp32s3-eye-01 status=ok age=0s

=== T1 基线:周期上报 ===
  [PASS] T1.1 周期数据持续到达: 8s 内新增 4 条(其中周期上报 4 条)

=== T2 远程采集一次 ===
  创建任务 request_id=req-1791444411152-c70ef1
  [PASS] T2.1 状态流转完整: 轨迹: pending→received→completed
  [PASS] T2.2 任务在超时前完成: status=completed elapsed=8085 ms
  [PASS] T2.3 产生带 request_id 的新观测: record=有, |a|=0.995 g, received_at=1791444419237
  [PASS] T2.4 新观测晚于任务创建: record.received_at - task.created_at = 8085 ms

=== T3 暂停周期上报 ===
  [PASS] T3.1 pause 命令被执行: 轨迹: pending→received→completed, note='periodic paused'
  [PASS] T3.2 暂停后不再产生周期记录: 9s 内新增周期记录 0 条

=== T4 暂停中命令通道仍可用 ===
  [PASS] T4.1 暂停期间采集任务仍能完成: 轨迹: pending→received→completed, elapsed=7327 ms
  [PASS] T4.2 拿到本任务的新观测: |a|=0.981 g

=== T6 恢复周期上报 ===
  [PASS] T6.1 resume 命令被执行: 轨迹: pending→received→completed, note='periodic resumed'
  [PASS] T6.2 周期上报恢复: 9s 内新增周期记录 1 条

=== T7 设备无响应:等待 / 超时,且旧值不被误标 ===
  创建指向离线设备 ghost-offline-01 的任务 req-1791444453327-b1f071,等待超时(15s 阈值)...
  [PASS] T7.1 任务最终判定为超时: 轨迹: pending→timeout
  [PASS] T7.2 超时任务没有 completed_at: completed_at_ms=None
  [PASS] T7.3 超时任务未指向任何记录(旧值未被误标): record_index=None
  [PASS] T7.4 没有记录被打上该 request_id: 未发现污染记录

==============================================================
  结果: 17/17 项通过
==============================================================
```
