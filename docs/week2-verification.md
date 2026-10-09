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

## 待人工配合的验证项(尚未执行)

| 项 | 说明 | 命令 |
|---|---|---|
| T5 改变设备状态后采集 | 拿起板子晃动/改变姿态,核对新观测确实更新,而非复旧值 | `python scripts/verify_week2.py --manual` |
| T7 真实设备离线版 | 拔掉板子 USB 后点"采集一次",观察页面显示等待/超时,且旧值不被标为本次结果 | 手动在页面操作,或观察上述 ghost 任务的等效验证 |

> 自动项已用 `ghost-offline-01`(永不轮询命令的离线设备)等效覆盖 T7 的超时与"旧值不误标"逻辑。

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
