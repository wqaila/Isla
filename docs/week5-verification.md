# 第 5 周验证记录 — 接通按键说话与语音播报

> 日期:2026-10-23
> 范围:`server/app.py` 的 `/api/voice/asr`(授权录音离线识别)、`/api/nlq` 语音入口扩展(channel/session_id/计时)、
> 前端 `static/js/voice.js`(语音助手卡片)、`scripts/make_tts_wav.py`(授权录音生成)
> 自动脚本:`scripts/verify_week5.py` → **20/20 通过**

---

## 一、本周问题与实现

**从"说一句话"到"听到回答",可观察的环节(状态机):**

```
空闲 → 录音中 → 识别中(中间结果实时显示)→ 执行中(复用第 4 周 /api/nlq)→ 播报中(TTS)→ 空闲
```

每个环节在页面上都有时间戳;两条识别路径最终汇合到同一个 `runTask()`:

| 路径 | 识别引擎 | 适用场景 | 结果 |
|---|---|---|---|
| **实时识别(主)** | 浏览器 SpeechRecognition(zh-CN) | 麦克风正常、有网 | 中间结果实时显示,说完即执行 |
| **授权录音(备用)** | 服务器 Vosk `vosk-model-small-cn-0.22`(**离线**) | 录音设备故障 / 断网 / 共享音频站补验 | 选 WAV(16kHz 单声道)→ 识别 → 同一条任务路径 |

关键取舍:**不把麦克风硬件当前提**(任务卡要求)。浏览器侧零依赖;备用路径用离线模型,
整条"音频 → 文本"链路不依赖任何云端服务,可复现、可自动验证。

## 二、自动验证结果(20/20)

| 项 | 结果 | 关键证据 |
|---|---|---|
| W5-1 授权录音识别 | ✅ | TTS 生成"现在加速度是多少"(2.7s)→ Vosk 识别为 `现在 加速度 是 多少` |
| W5-2 识别→任务全链路 | ✅ | intent=latest,答案带真实板端数值;channel=voice-file;输入结束→首次反馈 **26 ms** |
| W5-3 语音动作类 | ✅ | 「采集一次」语音入口 → 任务 completed,elapsed=2172 ms,答案带 X/Y/Z 数值 |
| W5-4 文字/语音入口对照 | ✅ | 同一句「设备还在线吗」两条入口 → 同一 intent(device_status)、都给出明确判断 |
| W5-5 错误格式反馈 | ✅ | 非 WAV → "请提交 WAV(PCM 16kHz 单声道 16bit)";8k 立体声 → "需要 16000Hz/单声道/16bit" |
| W5-6 无声反馈 | ✅ | 1 秒静音 → text 为空 + note "没有识别出内容",不猜不编 |
| W5-7 交互日志 | ✅ | voice-file 会话带 session_id 与计时落 `/api/voice/log` |

复现:`server/.venv/Scripts/python.exe scripts/verify_week5.py`(约 40 秒,含 TTS 生成与真实识别)

## 三、计时(输入结束 → 首次反馈 → 任务完成)

- 查询类:首次反馈 ≈ **26 ms**(服务端处理,局域网)
- 动作类:输入结束 → 任务完成 ≈ 2.2 s(板端轮询 2s + 采集上传)
- 三项计时均由服务器打戳(`voice.request_at_ms / respond_at_ms / first_feedback_ms / task_completed_ms`),
  客户端只提供 `input_end_ms`(用户"说完话"的时刻),避免两台机器时钟不一致导致的口径混乱。

## 四、待人工配合(当堂)

| 项 | 操作 | 预期 |
|---|---|---|
| 麦克风实时识别 | 点「🎤 点击说话」说"现在加速度是多少" | 识别中实时显示中间结果 → 回答 + 语音播报 |
| 按住说话 | 按住按钮 >0.4s 说话,松手结束 | 松手即识别执行 |
| 无声反馈 | 不说话直接点停止 | "没有听到声音(无声)…文字入口始终可用" |
| 播报中停止 | 回答播报中点「⏹ 停止」 | 立即静音,回到空闲 |
| 音频来源记录 | 看卡片右侧表格 | 麦克风 label、运行位置 URL、引擎、音频格式 |
| 授权录音补验 | 共享音频站导出 WAV → 选文件 → 识别并执行 | 与实时识别同一任务路径 |

## 五、文件清单

- `server/app.py`:`/api/voice/asr`、`/api/nlq` 语音扩展、`voice_log.jsonl` 交互日志
- `server/static/js/voice.js`:状态机、双路径识别、TTS、取消(与第 6 周共用)
- `server/static/js/{config,api}.js`、`templates/index.html`、`static/css/style.css`:语音卡片
- `scripts/make_tts_wav.py`:系统 TTS 生成授权录音(16kHz 单声道 WAV)
- `scripts/verify_week5.py`:自动验证
- `server/models/vosk-model-small-cn-0.22/`:离线识别模型(约 40MB,git 忽略)
