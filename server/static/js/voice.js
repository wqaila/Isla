/**
 * voice.js —— 第 5/6 周:语音助手
 *
 * 链路(对照第 5 周任务卡「从说一句话到听到回答的可观察环节」):
 *   录音中 → 识别中(中间结果实时显示)→ 执行中(复用第 4 周 /api/nlq,
 *   与文字入口同一条代码路径)→ 播报中(TTS)→ 空闲
 *
 * 第 6 周规则:
 *   - 取消(⏹ 停止):本地立即停识别/停播报,并通知服务器取消会话与任务;
 *   - 迟到隔离:取消后或开始新任务后才到的结果,一律忽略 —— 不重新播放、不触发动作;
 *   - 新任务不覆盖旧任务:每次交互有独立 session_id,动作类另有 request_id,
 *     右侧「最近会话」与服务器 /api/voice/log 用同一套 ID 关联。
 *
 * 两条识别路径:
 *   A. 实时识别(主):浏览器 SpeechRecognition(需在线识别服务,Chrome/Edge);
 *   B. 授权录音(备用):WAV 文件 → 服务器 Vosk 离线识别(断网/麦克风故障时)。
 * 两条路径最终都汇合到 runTask(),走同一个 /api/nlq。
 */
const Voice = (() => {
  const { $, nowMs, fmtDateTime } = Utils;

  const V = CONFIG.voice;
  const STEPS = [
    { key: "idle", label: "空闲" },
    { key: "recording", label: "录音中" },
    { key: "recognizing", label: "识别中" },
    { key: "executing", label: "执行中" },
    { key: "speaking", label: "播报中" },
  ];

  // ---------------------------------------------------------------- 状态
  const state = {
    phase: "idle",
    phaseTs: {},            // 每个阶段的进入时间(ms)
    session: null,          // 当前会话 {id, text, channel, inputEndMs, requestId, cancelled}
    recog: null,            // SpeechRecognition 实例
    finalText: "",
    interimText: "",
    recStartMs: 0,
    recTimer: null,
    holdTimer: null,
    holding: false,
    micLabel: "",
    lastVoice: null,        // 最近一次语音结果(供「同一句走文字入口对照」)
    lateCount: 0,           // 被忽略的迟到结果计数
  };

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const TTS_OK = "speechSynthesis" in window;

  // ---------------------------------------------------------------- 阶段渲染
  function setPhase(phase, note) {
    state.phase = phase;
    if (phase !== "idle" || !state.phaseTs.idle) {
      state.phaseTs[phase] = nowMs();
    }
    renderState(note || "");
  }

  function renderState(note) {
    const box = $("voiceState");
    if (!box) return;
    const order = STEPS.map((s) => s.key);
    const cur = Math.max(0, order.indexOf(state.phase));
    const chips = STEPS.map((s, i) => {
      const on = i <= cur && state.phase !== "idle" ? "on" : (i === 0 && state.phase === "idle" ? "on" : "");
      const ts = state.phaseTs[s.key];
      const t = ts ? `<i>${fmtDateTime(ts).slice(11, 19)}.${String(ts % 1000).padStart(3, "0")}</i>` : "";
      return `<span class="voice-chip ${on}">${s.label}${t}</span>`;
    }).join('<span class="voice-arrow">→</span>');
    box.innerHTML = `<div class="voice-chips">${chips}</div>` +
      (note ? `<div class="voice-note">${esc(note)}</div>` : "");
  }

  // ---------------------------------------------------------------- 反馈与文本渲染
  /** 可理解的反馈:无声 / 识别失败 / 服务超时 / 权限问题都走这里 */
  function feedback(kind, msg) {
    const box = $("voiceAnswer");
    if (box) {
      box.innerHTML = `<div class="voice-feedback ${esc(kind)}">${esc(msg)}</div>`;
    }
    toast(msg);
  }

  function renderTranscript() {
    const box = $("voiceTranscript");
    if (!box) return;
    const f = state.finalText;
    const i = state.interimText;
    if (!f && !i) {
      box.innerHTML = '<span class="muted">还没有录音。点「🎤 点击说话」开始,再说一遍;再点一次结束。</span>';
      return;
    }
    box.innerHTML =
      (f ? `<div class="voice-final">${esc(f)}</div>` : "") +
      (i ? `<div class="voice-interim">(识别中)${esc(i)}…</div>` : "");
  }

  function setBtns({ mic = true, stop = false, file = true } = {}) {
    const m = $("voiceMicBtn"), s = $("voiceStopBtn"), f = $("voiceFileBtn");
    if (m) m.disabled = !mic;
    if (s) s.disabled = !stop;
    if (f) f.disabled = !file;
  }

  // ---------------------------------------------------------------- 实时识别(主路径)
  function startListening() {
    if (!SR) {
      feedback("error", "这个浏览器不支持语音识别(SpeechRecognition)。请用 Chrome/Edge,或改用下方「授权录音」备用路径、文字入口。");
      return;
    }
    try { window.speechSynthesis && window.speechSynthesis.cancel(); } catch (e) { /* 忽略 */ }
    state.finalText = "";
    state.interimText = "";
    state.recStartMs = nowMs();
    renderTranscript();

    const rec = new SR();
    rec.lang = V.lang;
    rec.continuous = false;
    rec.interimResults = true;
    rec.maxAlternatives = 1;

    rec.onresult = (ev) => {
      let interim = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const r = ev.results[i];
        if (r.isFinal) state.finalText += r[0].transcript;
        else interim += r[0].transcript;
      }
      state.interimText = interim;
      if (interim) setPhase("recognizing", "正在识别(中间结果实时显示)…");
      renderTranscript();
    };
    rec.onerror = (ev) => {
      const map = {
        "not-allowed": "麦克风权限被拒绝 —— 请在地址栏左侧允许麦克风后重试;或用文字入口。",
        "service-not-allowed": "识别服务被浏览器策略拦截 —— 请改用 Chrome/Edge,或用文字入口。",
        "no-speech": "没有听到声音(无声)—— 请靠近麦克风再试一次,或检查系统录音设备。",
        "audio-capture": "没有找到录音设备 —— 请检查麦克风连接,或用下方「授权录音」备用路径。",
        "network": "识别服务网络错误(可能断网)—— 可用下方「授权录音」备用路径(服务器离线识别)。",
        "aborted": "",
      };
      const msg = map[ev.error] || `识别失败:${ev.error}`;
      if (msg) feedback("error", msg);
      cleanupRecognition();
      setPhase("idle", "识别失败,已回到空闲");
    };
    rec.onend = () => {
      cleanupRecognition();
      const text = state.finalText.trim();
      if (text) {
        state.interimText = "";
        renderTranscript();
        runTask(text, "voice");           // 音频 → 文本,进入任务执行
      } else if (state.phase === "recording" || state.phase === "recognizing") {
        feedback("warn", "没有听到声音(无声)。请靠近麦克风重试,或检查系统录音设备;文字入口始终可用。");
        setPhase("idle", "无声,已回到空闲");
      }
    };

    state.recog = rec;
    try {
      rec.start();
      setPhase("recording", "正在录音…(再点一次「🎤 点击说话」或按「⏹ 停止」结束)");
      setBtns({ mic: true, stop: true });
      refreshMicLabel();
      state.recTimer = setTimeout(() => {
        feedback("warn", `录音已达 ${V.maxRecordMs / 1000} 秒上限,自动结束。`);
        stopListening();
      }, V.maxRecordMs);
    } catch (e) {
      feedback("error", `无法开始录音:${e.message || e}`);
      cleanupRecognition();
      setPhase("idle", "无法开始录音");
    }
  }

  function stopListening() {
    if (state.recog) {
      try { state.recog.stop(); } catch (e) { /* 忽略:onend 会收尾 */ }
    } else {
      setPhase("idle", "已停止");
    }
  }

  function cleanupRecognition() {
    if (state.recTimer) { clearTimeout(state.recTimer); state.recTimer = null; }
    state.recog = null;
    setBtns({ mic: true, stop: false });
  }

  /** 点击/按住双模式:短按=切换,按住超过 holdMs=按住说话 */
  function bindMicButton() {
    const btn = $("voiceMicBtn");
    if (!btn) return;
    const down = (e) => {
      if (e.cancelable) e.preventDefault();
      state.holding = true;
      state.holdTimer = setTimeout(() => {
        state.holdTimer = null;
        if (state.phase === "idle") startListening();
      }, V.holdMs);
    };
    const up = () => {
      state.holding = false;
      if (state.holdTimer) {           // 短按 → 点击切换
        clearTimeout(state.holdTimer);
        state.holdTimer = null;
        if (state.phase === "idle") startListening();
        else if (state.phase === "recording" || state.phase === "recognizing") stopListening();
      } else if (state.phase === "recording" || state.phase === "recognizing") {
        stopListening();               // 按住模式:松手结束
      }
    };
    btn.addEventListener("mousedown", down);
    btn.addEventListener("touchstart", down, { passive: false });
    btn.addEventListener("mouseup", up);
    btn.addEventListener("mouseleave", up);
    btn.addEventListener("touchend", up);
    btn.addEventListener("touchcancel", up);
  }

  // ---------------------------------------------------------------- 任务执行(语音/文件/对照共用)
  /**
   * 把识别出的文本变成任务 —— 与第 4 周文字入口**同一个** /api/nlq 接口。
   * channel: "voice"(实时识别)/ "voice-file"(授权录音)/ "text"(对照)
   */
  async function runTask(text, channel) {
    const q = (text || "").trim();
    if (!q) {
      feedback("warn", "没有识别到文字,请重新说。");
      setPhase("idle", "空文本,已回到空闲");
      return;
    }
    const session = {
      id: "vs-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 6),
      text: q,
      channel: channel || "voice",
      inputEndMs: nowMs(),
      requestId: null,
      cancelled: false,
    };
    state.session = session;                 // 新会话立即顶上:旧会话的迟到响应之后会被忽略
    state.lastVoice = channel === "text" ? state.lastVoice : { text: q, sessionId: session.id };
    const cmpBtn = $("voiceCompareBtn");
    if (cmpBtn && channel !== "text") cmpBtn.disabled = false;

    setPhase("executing", "已把任务发给服务器执行(与文字入口同一条 /api/nlq 路径)…");
    setBtns({ mic: false, stop: true, file: false });

    const delayChk = $("voiceDelayChk");
    const delayMs = (delayChk && delayChk.checked) ? V.injectDelayMs : 0;

    const resp = await Api.nlqQuery(q, {
      groupId: window.App ? window.App.groupId() : "",
      wait: true,
      channel,
      sessionId: session.id,
      inputEndMs: session.inputEndMs,
      delayMs,
    });

    // ---- 迟到隔离:响应到达时,当前会话已经换了/取消了 → 一律忽略 ----
    if (!state.session || state.session.id !== session.id || session.cancelled) {
      state.lateCount++;
      renderHistoryNote(`迟到结果已忽略:会话 ${session.id} 已不是当前会话(取消或开始了新任务),不播放、不触发动作。`);
      setBtns({ mic: true, stop: false, file: true });
      return;
    }

    if (!resp.ok) {
      feedback("error", `服务请求失败:${resp.error || "未知错误"}(可能服务超时)。文字入口仍可重试。`);
      setPhase("idle", "服务请求失败");
      setBtns({ mic: true, stop: false, file: true });
      loadHistory();
      return;
    }

    if (resp.task && resp.task.request_id) session.requestId = resp.task.request_id;
    const timing = resp.voice || {};

    // 渲染回答
    const box = $("voiceAnswer");
    const intentText = (window.App && window.App.intentText && window.App.intentText(resp.intent)) || resp.intent;
    let html = `<div class="voice-answer-text">${esc(resp.answer || "")}</div>
      <div class="voice-answer-meta">
        <span class="nlq-chip intent">意图:${esc(intentText)}</span>
        <span class="nlq-chip">入口:${esc(channel === "text" ? "文字(对照)" : channel === "voice-file" ? "授权录音" : "语音")}</span>
        ${session.requestId ? `<span class="nlq-chip">request_id ${esc(session.requestId)}</span>` : ""}
        ${timing.first_feedback_ms != null ? `<span class="nlq-chip">输入结束→首次反馈 ${timing.first_feedback_ms} ms</span>` : ""}
        ${timing.task_completed_ms != null ? `<span class="nlq-chip">输入结束→任务完成 ${timing.task_completed_ms} ms</span>` : ""}
      </div>`;
    if (resp.task && resp.task.status) {
      const st = resp.task.status;
      const cls = { completed: "completed", failed: "failed", timeout: "timeout", cancelled: "failed" }[st] || "pending";
      html += `<div class="voice-task-line"><span class="badge ${cls}">${
        { completed: "已完成", failed: "失败", timeout: "超时", cancelled: "已取消", pending: "待领取", received: "设备已领取" }[st] || esc(st)
      }</span><span class="muted">${resp.task.elapsed_ms != null ? "耗时 " + esc(resp.task.elapsed_ms) + " ms" : ""}</span></div>`;
    }
    if (box) box.innerHTML = html;

    // 任务类结果同步到第 2 周任务卡片(和点按钮看到的一样)
    if (["sample", "pause", "resume"].indexOf(resp.intent) >= 0 && window.App && window.App.reloadTaskHistory) {
      window.App.reloadTaskHistory();
    }

    loadHistory();
    speakAnswer(resp.answer || "", session);
  }

  // ---------------------------------------------------------------- 语音播报(TTS)
  function pickZhVoice() {
    if (!TTS_OK) return null;
    const voices = window.speechSynthesis.getVoices() || [];
    return voices.find((v) => (v.lang || "").toLowerCase().startsWith("zh")) || null;
  }

  function speakAnswer(text, session) {
    if (!text) { setPhase("idle", "完成,回到空闲"); setBtns({ mic: true, stop: false, file: true }); return; }
    if (!TTS_OK) {
      feedback("warn", "这个浏览器不支持语音播报,回答已显示在上方(文字结果不受影响)。");
      setPhase("idle", "完成(无播报)");
      setBtns({ mic: true, stop: false, file: true });
      return;
    }
    window.speechSynthesis.cancel();          // 顶掉旧播报:新任务不被旧任务结果覆盖
    const u = new SpeechSynthesisUtterance(text.length > 300 ? text.slice(0, 300) + "……" : text);
    const v = pickZhVoice();
    if (v) u.voice = v;
    u.lang = V.lang;
    u.rate = 1.05;
    u.onstart = () => setPhase("speaking", "正在语音播报…(点「⏹ 停止」可中断)");
    u.onend = () => {
      if (state.session && state.session.id === session.id && !session.cancelled) {
        setPhase("idle", "完成,回到空闲");
        setBtns({ mic: true, stop: false, file: true });
      }
    };
    u.onerror = () => {
      if (state.session && state.session.id === session.id) {
        feedback("warn", "语音播报出错,回答已显示在上方(文字结果不受影响)。");
        setPhase("idle", "播报出错");
        setBtns({ mic: true, stop: false, file: true });
      }
    };
    window.speechSynthesis.speak(u);
    if (!window.speechSynthesis.speaking && !window.speechSynthesis.pending) {
      // 某些环境 speak 后不触发 onstart(无声音/被拦截):1 秒后兜底回空闲
      setTimeout(() => {
        if (state.phase === "speaking" && !window.speechSynthesis.speaking) {
          setPhase("idle", "播报未开始(可能被浏览器拦截),文字回答已显示");
          setBtns({ mic: true, stop: false, file: true });
        }
      }, 1200);
    }
  }

  // ---------------------------------------------------------------- 第 6 周:取消与澄清
  /** ⏹ 停止:本地立即停识别/停播报 → 通知服务器取消会话与任务 → 回空闲 */
  async function cancelAll() {
    const s = state.session;
    // 1) 本地立即停(不等服务器)
    if (state.recog) { try { state.recog.abort(); } catch (e) { /* 忽略 */ } }
    cleanupRecognition();
    if (TTS_OK) { try { window.speechSynthesis.cancel(); } catch (e) { /* 忽略 */ } }

    if (s) s.cancelled = true;
    setPhase("idle", "已停止,回到空闲");
    setBtns({ mic: true, stop: false, file: true });

    if (!s) {
      feedback("warn", "当前没有进行中的语音任务。");
      return;
    }
    const resp = await Api.voiceCancel(s.id, s.requestId);
    const taskNote = resp.task ? "板端任务已标记取消。" : "";
    feedback("warn",
      `已取消会话 ${s.id}。${taskNote}取消之后迟到的回执只会被记录为「迟到结果」并忽略 —— 不会重新播放或触发动作。`);
    state.session = null;
    loadHistory();
  }

  /** 同一句走文字入口对照:同一句话、同一个 /api/nlq,证明两条入口等价 */
  async function compareWithText() {
    const last = state.lastVoice;
    if (!last || !last.text) { toast("先完成一次语音交互"); return; }
    const btn = $("voiceCompareBtn");
    if (btn) btn.disabled = true;
    const resp = await (window.App && window.App.askNlq
      ? window.App.askNlq(last.text, {
          channel: "text",
          sessionId: last.sessionId + "-text",
          inputEndMs: nowMs(),
        })
      : Api.nlqQuery(last.text, { groupId: window.App ? window.App.groupId() : "", wait: true, channel: "text", sessionId: last.sessionId + "-text", inputEndMs: nowMs() }));
    if (btn) btn.disabled = false;
    if (!resp || !resp.ok) { toast("文字入口对照失败:" + (resp && resp.error || "未知错误")); return; }

    const box = $("voiceCompare");
    if (!box) return;
    const t = resp.voice || {};
    box.style.display = "block";
    box.innerHTML = `
      <div class="voice-block-title">入口对照:同一句「${esc(last.text)}」</div>
      <div class="voice-compare-grid">
        <div class="voice-compare-col">
          <b>语音入口</b>
          <div>意图:${esc(resp.intent)}</div>
          <div>request_id:${esc((resp.task && resp.task.request_id) || "(查询类无任务)")}</div>
          <div>输入结束→首次反馈:${t.first_feedback_ms != null ? esc(t.first_feedback_ms) + " ms" : "—"}</div>
        </div>
        <div class="voice-compare-col">
          <b>文字入口(刚在「自然语言查询」卡片执行)</b>
          <div>意图:${esc(resp.intent)}</div>
          <div>request_id:${esc((resp.task && resp.task.request_id) || "(查询类无任务)")}</div>
          <div>输入结束→首次反馈:${t.first_feedback_ms != null ? esc(t.first_feedback_ms) + " ms" : "—"}</div>
        </div>
      </div>
      <div class="voice-compare-ok">✓ 同一句话、同一条 /api/nlq 代码路径、同一个解析器 —— 两条入口结果一致,可互相印证。</div>`;
    toast("已用文字入口跑同一句,结果见对照区");
    loadHistory();
  }

  // ---------------------------------------------------------------- 授权录音(备用路径)
  async function recognizeFile() {
    const input = $("voiceFile");
    const note = $("voiceFileNote");
    const f = input && input.files && input.files[0];
    if (!f) { if (note) note.textContent = "先选择一个 WAV 文件(16kHz 单声道)"; return; }
    if (note) note.textContent = `识别中(服务器离线识别)… ${f.name}`;
    const btn = $("voiceFileBtn");
    if (btn) btn.disabled = true;
    const r = await Api.voiceAsr(f);
    if (btn) btn.disabled = false;
    if (!r.ok) {
      if (note) note.textContent = "识别失败:" + (r.error || "未知错误");
      feedback("error", `授权录音识别失败:${r.error || "未知错误"}。请确认是 16kHz 单声道 16bit WAV;文字入口仍可用。`);
      return;
    }
    if (!r.text) {
      if (note) note.textContent = "没有识别出内容";
      feedback("warn", "这段录音没有识别出内容(可能太短或环境太吵)。请换一段,或用文字入口。");
      return;
    }
    if (note) note.textContent = `识别完成:${r.engine},${r.duration_ms} ms`;
    runTask(r.text, "voice-file");           // 汇合到同一条任务路径
  }

  // ---------------------------------------------------------------- 最近会话(时序记录)
  function renderHistoryNote(text) {
    const box = $("voiceHistory");
    if (!box) return;
    const div = document.createElement("div");
    div.className = "voice-history-item late";
    div.innerHTML = `<div class="voice-history-q">${esc(text)}</div>`;
    box.prepend(div);
  }

  async function loadHistory() {
    const resp = await Api.voiceLog(V.historyLimit);
    const box = $("voiceHistory");
    if (!box) return;
    if (!resp.ok || !resp.items || !resp.items.length) {
      box.innerHTML = '<div class="muted">暂无</div>';
      return;
    }
    box.innerHTML = resp.items.map((it) => {
      const t = it.created_at_ms ? fmtDateTime(it.created_at_ms).slice(11, 19) : "";
      const ch = { voice: "语音", "voice-file": "授权录音", text: "文字" }[it.channel] || it.channel || "";
      const flags = [];
      if (it.cancelled) flags.push('<span class="badge failed">已取消</span>');
      if (it.late_ack) flags.push('<span class="badge timeout">迟到回执已忽略</span>');
      const fb = it.first_feedback_ms != null ? `首次反馈 ${it.first_feedback_ms}ms` : "";
      const done = it.task_completed_ms != null ? `完成 ${it.task_completed_ms}ms` : "";
      return `<div class="voice-history-item${it.cancelled ? " late" : ""}">
        <div class="voice-history-q">${t} · ${esc(ch)} · ${esc(it.intent || "")} ${flags.join(" ")}</div>
        <div class="voice-history-a">${esc(it.text || "")}</div>
        <div class="voice-history-a muted">${esc([fb, done].filter(Boolean).join(" · "))}</div>
      </div>`;
    }).join("");
  }

  // ---------------------------------------------------------------- 音频来源与运行位置
  async function refreshMicLabel() {
    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
      const devs = await navigator.mediaDevices.enumerateDevices();
      const mics = devs.filter((d) => d.kind === "audioinput");
      state.micLabel = mics.map((m) => m.label || "(未授权,label 隐藏)").join("、") || "(未发现麦克风)";
      renderMeta();
    } catch (e) { /* 忽略:label 拿不到不影响主流程 */ }
  }

  function renderMeta() {
    const box = $("voiceMeta");
    if (!box) return;
    const engine = SR ? "浏览器 SpeechRecognition(在线服务)+ 服务器 Vosk 离线(备用路径)" : "服务器 Vosk 离线(浏览器不支持实时识别)";
    const rows = [
      ["识别引擎", engine],
      ["麦克风", state.micLabel || "(开始录音后显示)"],
      ["运行位置", location.href],
      ["浏览器", (navigator.userAgent || "").slice(0, 60) + "…"],
      ["音频格式", "16kHz 单声道 16bit WAV(两条路径统一)"],
      ["播报", TTS_OK ? "浏览器 SpeechSynthesis" : "不支持(仅文字回答)"],
    ];
    box.innerHTML = rows.map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join("");
  }

  // ---------------------------------------------------------------- 初始化
  function init() {
    bindMicButton();
    $("voiceStopBtn")?.addEventListener("click", cancelAll);
    $("voiceRetryBtn")?.addEventListener("click", () => {
      if (state.phase === "idle") startListening();
      else toast("先点「⏹ 停止」结束当前任务");
    });
    $("voiceCompareBtn")?.addEventListener("click", compareWithText);
    $("voiceFileBtn")?.addEventListener("click", recognizeFile);
    if (TTS_OK) window.speechSynthesis.onvoiceschanged = () => renderMeta();

    if (!SR) {
      feedback("warn", "此浏览器不支持实时语音识别:请用 Chrome/Edge 获得完整体验;当前可用「授权录音」(服务器离线识别)或文字入口。");
    }
    renderMeta();
    renderState("空闲。点「🎤 点击说话」开始;也可以只用下方授权录音或上方文字入口。");
    loadHistory();
  }

  return { init, runTask, cancel: cancelAll, state };
})();
