# -*- coding: utf-8 -*-
"""第 5 周当堂验证:接通按键说话与语音播报(自动部分)。

用法:
    python server/app.py               # 先起服务(用 server/.venv,已装 vosk/pyttsx3)
    server/.venv/Scripts/python.exe scripts/verify_week5.py

覆盖(对照任务卡)
----------------
W5-1 授权录音识别(备用路径):系统 TTS 生成"现在加速度是多少" → 服务器离线识别,
     必须识别出文本(证明"音频 → 文本"环节真实工作,不依赖云端)。
W5-2 识别 → 任务全链路:识别文本进 /api/nlq(voice-file 入口)→ 真实答案 + 计时。
W5-3 语音动作类:「采集一次」走语音入口,真的下发任务;板子在线→completed,
     离线→如实 timeout,绝不把"已下发"说成"已采集成功"。
W5-4 文字/语音入口对照:同一句话两条入口 → 同一 intent、同一答案(同一条代码路径)。
W5-5 格式可理解反馈:非 WAV / 格式不符 → 明确错误,不是 500。
W5-6 无声可理解反馈:1 秒静音 → text 为空 + note,不猜、不编。
W5-7 交互日志:channel/计时(request_id 关联)落在 /api/voice/log。

需要人工确认(麦克风实时识别、TTS 播报听感、页面状态机)见 docs/week5-verification.md。
"""

import json
import sys
import tempfile
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_tts_wav import synth_to_wav  # noqa: E402

BASE = "http://127.0.0.1:8000"
TIMEOUT = 40
ASR_TEXT = "现在加速度是多少"

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))
    return ok


def post(path, body, timeout=TIMEOUT, raw=None):
    if raw is not None:
        data = raw
        ctype = "application/octet-stream"
    else:
        data = json.dumps(body).encode("utf-8")
        ctype = "application/json"
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": ctype}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path, timeout=TIMEOUT):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def post_file(path, file_path, field="audio", timeout=60):
    boundary = "----verify5boundary"
    with open(file_path, "rb") as f:
        payload = f.read()
    body = (f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{field}"; filename="{Path(file_path).name}"\r\n'
            f"Content-Type: audio/wav\r\n\r\n").encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(BASE + path, data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 服务端的"可理解反馈"本来就是 4xx + JSON 错误体,读出来继续断言
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            raise


def norm(s):
    return (s or "").replace(" ", "").replace(",", "").replace("。", "")


def main():
    print("=" * 62)
    print("  第 5 周当堂验证 —— 按键说话与语音播报(自动部分)")
    print(f"  时间:{time.strftime('%Y-%m-%d %H:%M:%S')}   服务:{BASE}")
    print("=" * 62)

    tmp = Path(tempfile.mkdtemp(prefix="verify_w5_"))
    wav = tmp / "tts_now.wav"
    silence = tmp / "silence.wav"
    bad = tmp / "bad.wav"

    # ---------- W5-1 授权录音识别 ----------
    print("\n=== W5-1 授权录音识别(备用路径,服务器离线 Vosk)===")
    try:
        synth_to_wav(ASR_TEXT, str(wav))
        check("W5-1a TTS 授权录音生成", wav.exists() and wav.stat().st_size > 1000,
              f"{wav.stat().st_size if wav.exists() else 0} bytes")
        r = post_file("/api/voice/asr", wav)
        text = r.get("text", "")
        check("W5-1b 离线识别出文本", norm(text) == norm(ASR_TEXT) or "加速度" in norm(text),
              f"识别:{text!r}(期望含「加速度」)")
        check("W5-1c 识别引擎标注", "vosk" in (r.get("engine") or "").lower(), r.get("engine", ""))
        check("W5-1d 时长合理", 1000 <= (r.get("duration_ms") or 0) <= 15000, f"{r.get('duration_ms')} ms")
    except Exception as e:
        check("W5-1 授权录音识别", False, f"异常:{e}")
        text = ASR_TEXT  # 后续用例用原文继续,不阻塞

    # ---------- W5-2 识别 → 任务全链路 ----------
    print("\n=== W5-2 识别文本 → 任务执行(voice-file 入口)===")
    try:
        ie = int(time.time() * 1000)
        r = post("/api/nlq", {"text": text, "channel": "voice-file",
                              "session_id": f"vs-w5-{int(time.time())}", "input_end_ms": ie})
        v = r.get("voice") or {}
        check("W5-2a 意图正确(查询类)", r.get("intent") == "latest", r.get("intent"))
        check("W5-2b 答案含真实数值", "m/s" in (r.get("answer") or ""), (r.get("answer") or "")[:46])
        check("W5-2c 入口标记 voice-file", v.get("channel") == "voice-file", v.get("channel"))
        check("W5-2d 计时:输入结束→首次反馈", v.get("first_feedback_ms") is not None,
              f"{v.get('first_feedback_ms')} ms")
    except Exception as e:
        check("W5-2 全链路", False, f"异常:{e}")

    # ---------- W5-3 语音动作类 ----------
    print("\n=== W5-3 语音动作类:「采集一次」真的下发 ===")
    try:
        r = post("/api/nlq", {"text": "采集一次", "channel": "voice",
                              "session_id": f"vs-w5-act-{int(time.time())}",
                              "input_end_ms": int(time.time() * 1000)})
        task = r.get("task") or {}
        st = task.get("status")
        if st == "completed":
            check("W5-3a 板子在线:任务完成", True, f"elapsed={task.get('elapsed_ms')} ms")
            check("W5-3b 答案报告成功且带数值", "已采集成功" in (r.get("answer") or ""),
                  (r.get("answer") or "")[:46])
        elif st in ("timeout", "pending"):
            # 板子离线:12s 等待窗口内可能还没到 15s 的任务超时,状态停在 pending。
            # 两种状态都必须"如实说没等到",绝不出现成功字样。
            ans = r.get("answer") or ""
            check("W5-3a 板子离线:如实说没等到(不谎报成功)",
                  "没等到" in ans and "已采集成功" not in ans, f"status={st} | {ans[:40]}")
        else:
            check("W5-3a 动作类终态", False, f"status={st}")
    except Exception as e:
        check("W5-3 动作类", False, f"异常:{e}")

    # ---------- W5-4 文字/语音入口对照 ----------
    print("\n=== W5-4 同一句话:语音入口 vs 文字入口 ===")
    try:
        s_id = f"vs-w5-cmp-{int(time.time())}"
        q = "设备还在线吗"
        r1 = post("/api/nlq", {"text": q, "channel": "voice", "session_id": s_id,
                               "input_end_ms": int(time.time() * 1000)})
        r2 = post("/api/nlq", {"text": q, "channel": "text", "session_id": s_id + "-text",
                               "input_end_ms": int(time.time() * 1000)})
        check("W5-4a 两条入口意图一致", r1.get("intent") == r2.get("intent"),
              f"{r1.get('intent')} vs {r2.get('intent')}")
        # 查询类答案可能因数据流动而略不同,比较关键字段:是否都明确给出在线/离线判断
        a1, a2 = r1.get("answer") or "", r2.get("answer") or ""
        check("W5-4b 两条入口都给出明确判断", ("在线" in a1 or "离线" in a1) and ("在线" in a2 or "离线" in a2))
        check("W5-4c 入口标记正确", (r1["voice"]["channel"], r2["voice"]["channel"]) == ("voice", "text"))
    except Exception as e:
        check("W5-4 入口对照", False, f"异常:{e}")

    # ---------- W5-5 格式校验 ----------
    print("\n=== W5-5 错误格式的可理解反馈 ===")
    try:
        bad.write_bytes(b"NOT-A-WAV-FILE" * 100)
        r = post_file("/api/voice/asr", bad)
        check("W5-5a 非 WAV 明确拒绝", r.get("ok") is False and "WAV" in (r.get("error") or ""),
              (r.get("error") or "")[:40])
        # 格式不符的 WAV(8k 立体声)
        with wave.open(str(tmp / "wrong_fmt.wav"), "wb") as wf:
            wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(8000)
            wf.writeframes(b"\x00\x00" * 8000)
        r2 = post_file("/api/voice/asr", tmp / "wrong_fmt.wav")
        check("W5-5b 格式不符明确拒绝", r2.get("ok") is False and "16000" in (r2.get("error") or ""),
              (r2.get("error") or "")[:40])
    except Exception as e:
        check("W5-5 格式校验", False, f"异常:{e}")

    # ---------- W5-6 无声 ----------
    print("\n=== W5-6 无声的可理解反馈 ===")
    try:
        with wave.open(str(silence), "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
            wf.writeframes(b"\x00\x00" * 16000)  # 1 秒静音
        r = post_file("/api/voice/asr", silence)
        check("W5-6a 静音 → 空文本", r.get("ok") is True and not (r.get("text") or "").strip(),
              f"text={r.get('text')!r}")
        check("W5-6b 静音 → 明确 note(不猜)", bool(r.get("note")), r.get("note", "")[:40])
    except Exception as e:
        check("W5-6 无声反馈", False, f"异常:{e}")

    # ---------- W5-7 交互日志 ----------
    print("\n=== W5-7 交互日志(request_id 关联 + 计时)===")
    try:
        items = get("/api/voice/log?limit=20").get("items", [])
        vf = [i for i in items if i.get("channel") == "voice-file"]
        check("W5-7a voice-file 会话已记录", len(vf) >= 1, f"共 {len(vf)} 条")
        check("W5-7b 日志带计时", any(i.get("first_feedback_ms") is not None for i in vf))
        check("W5-7c 日志带 session_id", all(i.get("session_id") for i in vf))
    except Exception as e:
        check("W5-7 交互日志", False, f"异常:{e}")

    # ---------- 汇总 ----------
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print("\n" + "=" * 62)
    print(f"  结果:{passed}/{total} 项通过")
    print("=" * 62)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
