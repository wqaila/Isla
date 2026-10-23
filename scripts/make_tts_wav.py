# -*- coding: utf-8 -*-
"""第 5 周辅助:用系统 TTS 生成「授权录音」WAV(16kHz 单声道 16bit)。

用途
----
1. 当堂验证的**备用路径**:麦克风故障时,用这段授权录音走完整的
   「音频 → 文本 → 任务」链路,证明识别环节真的在工作;
2. `verify_week5.py` 的自动验证:不依赖真人在场,也能真实识别一次。

依赖:pyttsx3(调系统 SAPI 语音,中文需系统装有中文语音包,如 Huihui)。
格式:统一输出 16kHz / 单声道 / 16bit PCM —— 与 /api/voice/asr 要求一致,
      浏览器端 WebAudio 重采样后也提交这个格式,两条路径才能互相对照。

用法:
    python scripts/make_tts_wav.py "现在加速度是多少" out.wav
"""
import sys
import wave
import array
from pathlib import Path


def synth_to_wav(text: str, out_path: str, rate: int = 16000) -> str:
    import pyttsx3

    engine = pyttsx3.init()
    # 优先选中文语音;没有就用系统默认
    for v in engine.getProperty("voices"):
        langs = [str(x).lower() for x in (getattr(v, "languages", None) or [])]
        if any("zh" in x for x in langs):
            engine.setProperty("voice", v.id)
            break
    engine.setProperty("rate", 150)          # 慢一点,识别更稳
    tmp = str(out_path) + ".raw.wav"
    engine.save_to_file(text, tmp)
    engine.runAndWait()
    engine.stop()

    # SAPI 出来的 WAV 采样率不一定是 16k,这里统一重采样(线性插值,语音够用)
    with wave.open(tmp, "rb") as wf:
        src_rate = wf.getframerate()
        ch = wf.getnchannels()
        width = wf.getsampwidth()
        n = wf.getnframes()
        raw = wf.readframes(n)

    if width != 2:
        Path(tmp).unlink(missing_ok=True)
        raise RuntimeError(f"TTS 输出不是 16bit(width={width}),无法处理")

    samples = array.array("h")
    samples.frombytes(raw)
    if ch > 1:  # 混成单声道
        mono = array.array("h", [0] * (len(samples) // ch))
        for i in range(len(mono)):
            s = 0
            for c in range(ch):
                s += samples[i * ch + c]
            mono[i] = s // ch
        samples = mono

    if src_rate != rate:
        ratio = src_rate / rate
        out_n = int(len(samples) / ratio)
        resampled = array.array("h", [0] * out_n)
        for i in range(out_n):
            pos = i * ratio
            i0 = int(pos)
            i1 = min(i0 + 1, len(samples) - 1)
            frac = pos - i0
            resampled[i] = int(samples[i0] * (1 - frac) + samples[i1] * frac)
        samples = resampled

    with wave.open(out_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())

    Path(tmp).unlink(missing_ok=True)
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    text, out = sys.argv[1], sys.argv[2]
    p = synth_to_wav(text, out)
    with wave.open(p, "rb") as wf:
        dur = wf.getnframes() / wf.getframerate()
    print(f"OK {p}  {dur:.2f}s  ({text})")
