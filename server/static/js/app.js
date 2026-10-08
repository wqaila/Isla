/**
 * app.js —— 主逻辑
 * 状态管理、UI 更新、轮询调度、事件绑定。
 */
(() => {
  const { $, nowMs, fmtNum, fmtWithUnit, fmtTime, fmtDateTime, fmtAgo,
          toNum, accOf, magnitude, magOf, describe, downloadText, copyText } = Utils;
  const T = CONFIG.thresholds;
  const DS = CONFIG.deviceState;

  // ---------- 应用状态 ----------
  const state = {
    groupId: CONFIG.defaultGroupId,
    refreshMs: CONFIG.defaultRefreshMs,
    paused: false,
    timer: null,
    lastRecord: null,
    lastRecords: [],        // 最近一次 history 结果
    historyRangeMs: CONFIG.defaultHistoryRange,
    serverOk: false,
    serverCount: 0,
    apiFailStreak: 0,
    recvTimes: [],          // 用于估算实际接收频率
  };

  // ---------- 状态指示 ----------
  function setSystemStatus(level, text) {
    const dot = $("sysDot");
    const txt = $("sysText");
    if (dot) dot.className = "dot " + level;
    if (txt) txt.textContent = text;
  }

  function setBanner(kind, text) {
    const b = $("banner");
    if (!b) return;
    if (!text) { b.style.display = "none"; return; }
    b.style.display = "flex";
    b.className = "banner " + kind;
    b.querySelector(".banner-text").textContent = text;
  }

  // ---------- 概览卡片 ----------
  function setMetric(id, value, unit, opts = {}) {
    const el = $(id);
    if (!el) return;
    el.textContent = (value === null || value === undefined) ? "--" :
                     (unit ? `${fmtNum(value)} ${unit}` : fmtNum(value));
    // 异常高亮
    const card = el.closest(".metric");
    if (card) card.classList.toggle("alert", !!opts.alert);
  }

  function updateOverview(rec) {
    if (!rec) {
      ["mX", "mY", "mZ", "mMag", "mRssi", "mHz"].forEach((id) => setMetric(id, null));
      return;
    }
    const a = accOf(rec);
    const mag = magnitude(a.x, a.y, a.z);
    const d = rec.data || {};

    setMetric("mX", a.x, "m/s²", { alert: a.x !== null && Math.abs(a.x) > T.axisMax });
    setMetric("mY", a.y, "m/s²", { alert: a.y !== null && Math.abs(a.y) > T.axisMax });
    setMetric("mZ", a.z, "m/s²", { alert: a.z !== null && Math.abs(a.z) > T.axisMax });
    setMetric("mMag", mag, "m/s²", { alert: mag !== null && (mag > T.magMax || mag < T.magMin) });

    const rssi = toNum(d.rssi);
    setMetric("mRssi", rssi, "dBm", { alert: rssi !== null && rssi < T.rssiWeak });

    // 采样频率:优先用板端 n_samples / 上传周期(1s),否则用接收频率估算
    const n = toNum(d.n_samples);
    const hz = n !== null ? n : null;
    setMetric("mHz", hz, "Hz", { alert: hz !== null && (hz < T.hzMin || hz > T.hzMax) });

    // 趋势提示(与上一次比较)
    if (state.lastRecord) {
      const prevMag = magOf(state.lastRecord);
      if (mag !== null && prevMag !== null) {
        const diff = mag - prevMag;
        const trendEl = $("magTrend");
        if (trendEl) {
          const arrow = Math.abs(diff) < 0.05 ? "→" : (diff > 0 ? "↑" : "↓");
          trendEl.textContent = `${arrow} ${diff >= 0 ? "+" : ""}${diff.toFixed(3)}`;
          trendEl.className = "trend " + (Math.abs(diff) < 0.05 ? "" : (diff > 0 ? "up" : "down"));
        }
      }
    }
  }

  // ---------- 设备状态 ----------
  function deviceStateOf(rec) {
    if (!rec) return { level: "offline", text: "离线", ageMs: null };
    const age = nowMs() - Number(rec.received_at_ms || 0);
    if (age < DS.onlineMs) return { level: "online", text: "在线", ageMs: age };
    if (age < DS.delayedMs) return { level: "delayed", text: "数据延迟", ageMs: age };
    return { level: "offline", text: "离线", ageMs: age };
  }

  function updateDevicePanel(rec) {
    const st = deviceStateOf(rec);
    const el = $("devState");
    if (el) {
      el.innerHTML = `<span class="pill ${st.level}">${st.text}</span>`;
    }
    if (!rec) {
      ["devId", "devSensor", "devUptime", "devRssi", "devLastTime",
       "devInterval", "devCount", "devHz", "devDelay"].forEach((id) => {
        const e = $(id); if (e) e.textContent = "--";
      });
      return;
    }
    const d = rec.data || {};
    const set = (id, v) => { const e = $(id); if (e) e.textContent = v; };

    set("devId", rec.device_id || "--");
    set("devSensor", d.sensor || "--");

    const up = toNum(d.uptime_s);
    set("devUptime", up === null ? "--" : `${Math.floor(up / 60)} 分 ${Math.floor(up % 60)} 秒`);

    const rssi = toNum(d.rssi);
    set("devRssi", rssi === null ? "--" : `${rssi} dBm`);

    set("devLastTime", fmtDateTime(rec.received_at_ms));

    // 数据间隔:最近两次接收时间差
    const recv = state.recvTimes;
    if (recv.length >= 2) {
      const iv = recv[recv.length - 1] - recv[recv.length - 2];
      set("devInterval", `${iv} ms`);
    } else {
      set("devInterval", "--");
    }

    set("devCount", state.serverCount || "--");

    const n = toNum(d.n_samples);
    set("devHz", n === null ? "--" : `${n} Hz`);

    // 通信延迟:需要板端与服务器时间基准一致才能算
    // 板端 ts_ms 是"开机以来的毫秒数"(非绝对时间),与服务器绝对时间不同基准 → 不能直接相减
    const delayEl = $("devDelay");
    if (delayEl) {
      delayEl.textContent = "时间基准不同,无法准确计算";
      delayEl.classList.add("muted");
    }
  }

  // ---------- 异常检测 ----------
  function detectAnomalies(rec) {
    const list = [];
    if (!rec) {
      list.push({ level: "error", text: "设备离线:未收到任何数据" });
      return list;
    }
    const d = rec.data || {};
    const a = accOf(rec);
    const mag = magnitude(a.x, a.y, a.z);
    const age = nowMs() - Number(rec.received_at_ms || 0);

    // 1) 数据延迟
    if (age > T.staleMs) {
      list.push({ level: age > DS.delayedMs ? "error" : "warn",
                  text: `数据延迟:${Math.floor(age / 1000)} 秒未更新` });
    }
    // 2) 加速度异常
    if (mag !== null && mag > T.magMax) {
      list.push({ level: "warn", text: `合加速度偏大:${mag.toFixed(2)} m/s²(阈值 ${T.magMax})` });
    }
    if (mag !== null && mag < T.magMin) {
      list.push({ level: "warn", text: `合加速度偏小:${mag.toFixed(2)} m/s²(可能处于失重/异常)` });
    }
    // 3) RSSI 过低
    const rssi = toNum(d.rssi);
    if (rssi !== null && rssi < T.rssiWeak) {
      list.push({ level: "warn", text: `WiFi 信号弱:${rssi} dBm(阈值 ${T.rssiWeak})` });
    }
    // 4) 字段缺失
    const missing = [];
    if (a.x === null) missing.push("acc_x");
    if (a.y === null) missing.push("acc_y");
    if (a.z === null) missing.push("acc_z");
    if (missing.length) {
      list.push({ level: "warn", text: `数据字段缺失:${missing.join(", ")}(页面已用 -- 占位)` });
    }
    // 5) 时间戳异常(板端 ts_ms 应递增)
    if (state.lastRecord) {
      const prevTs = toNum(state.lastRecord.ts_ms);
      const curTs = toNum(rec.ts_ms);
      if (prevTs !== null && curTs !== null) {
        if (curTs < prevTs) {
          list.push({ level: "warn", text: "时间戳异常:板端时间戳回退(可能设备重启)" });
        } else if (curTs - prevTs > T.tsGapMs * 2) {
          list.push({ level: "warn", text: `采样间隔异常:${((curTs - prevTs) / 1000).toFixed(1)} 秒` });
        }
      }
    }
    // 6) 状态非 ok
    if (rec.status && rec.status !== "ok" && rec.status !== "simulated") {
      list.push({ level: "error", text: `设备上报状态异常:${rec.status}` });
    }
    return list;
  }

  function renderAnomalies(list) {
    const box = $("anomalyList");
    if (!box) return;
    if (!list.length) {
      box.innerHTML = '<div class="anomaly none">✓ 未检测到异常</div>';
      return;
    }
    box.innerHTML = list.map((a) =>
      `<div class="anomaly ${a.level}">${a.level === "error" ? "✕" : "⚠"} ${a.text}</div>`
    ).join("");
  }

  // ---------- 数据质量 ----------
  function updateQuality(statsResp) {
    const q = statsResp && statsResp.quality;
    const bar = $("qualityBar");
    const pctEl = $("qualityPct");
    const detail = $("qualityDetail");
    if (!q) {
      if (bar) bar.style.width = "0%";
      if (pctEl) pctEl.textContent = "--";
      if (detail) detail.innerHTML = '<span class="muted">暂无数据</span>';
      return;
    }
    const score = q.score === null || q.score === undefined ? null : q.score;
    if (bar) {
      bar.style.width = (score === null ? 0 : score) + "%";
      bar.className = "quality-fill" +
        (score === null ? "" : (score >= 90 ? " good" : score >= T.qualityMin ? " warn" : " bad"));
    }
    if (pctEl) pctEl.textContent = score === null ? "--" : score + "%";

    if (detail) {
      const rows = [
        ["记录数", q.record_count],
        ["实际频率", q.actual_hz === null ? "--" : q.actual_hz + " Hz"],
        ["理论频率", q.expected_hz + " Hz"],
        ["丢包次数", q.gap_count],
        ["最大间隔", q.max_gap_ms ? q.max_gap_ms + " ms" : "--"],
        ["重复时间戳", q.duplicate_ts],
        ["时长", q.duration_s + " s"],
      ];
      detail.innerHTML = rows.map(([k, v]) =>
        `<div class="qrow"><span>${k}</span><b>${v}</b></div>`
      ).join("");
    }
  }

  // ---------- 统计 ----------
  function updateStats(statsResp) {
    const box = $("statsTable");
    if (!box) return;
    if (!statsResp || !statsResp.ok) {
      box.innerHTML = '<tr><td colspan="6" class="muted">暂无统计数据</td></tr>';
      return;
    }
    const rows = [
      ["X 加速度", statsResp.acc_x],
      ["Y 加速度", statsResp.acc_y],
      ["Z 加速度", statsResp.acc_z],
      ["合加速度", statsResp.acc_magnitude],
    ];
    box.innerHTML = rows.map(([name, s]) => {
      if (!s) {
        return `<tr><td>${name}</td><td>--</td><td>--</td><td>--</td><td>--</td><td>--</td></tr>`;
      }
      return `<tr>
        <td>${name}</td>
        <td>${fmtNum(s.max)}</td>
        <td>${fmtNum(s.min)}</td>
        <td>${fmtNum(s.avg)}</td>
        <td>${fmtNum(s.std)}</td>
        <td>${fmtNum(s.ptp)}</td>
      </tr>`;
    }).join("");
  }

  // ---------- 来源信息 ----------
  function updateSourceInfo(rec) {
    const set = (id, v) => { const e = $(id); if (e) e.textContent = v; };
    if (!rec) {
      ["srcGroup", "srcDevice", "srcTs", "srcRecv", "srcSince", "srcStatus", "srcCount"]
        .forEach((id) => set(id, "--"));
      return;
    }
    set("srcGroup", rec.group_id || "--");
    set("srcDevice", rec.device_id || "--");
    set("srcTs", rec.ts_ms === null || rec.ts_ms === undefined ? "--" : rec.ts_ms);
    set("srcRecv", fmtDateTime(rec.received_at_ms));
    set("srcSince", fmtAgo(rec.received_at_ms));

    const st = rec.status;
    const cls = st === "ok" ? "ok" : (st === "simulated" ? "demo" : "fail");
    const el = $("srcStatus");
    if (el) el.innerHTML = `<span class="badge ${cls}">${st || "--"}</span>`;

    set("srcCount", state.serverCount);
  }

  // ---------- 原始 JSON ----------
  function updateRaw(rec) {
    const pre = $("rawPreview");
    if (!pre) return;
    if (!rec) { pre.textContent = "(暂无数据)"; return; }
    try {
      pre.textContent = JSON.stringify(rec, null, 2);
    } catch (e) {
      pre.textContent = "(JSON 格式化失败:" + e.message + ")";
    }
  }

  // ---------- 主刷新 ----------
  async function refresh(force = false) {
    if (state.paused && !force) return;

    const g = state.groupId;
    const now = nowMs();
    const sinceMs = state.historyRangeMs > 0 ? now - state.historyRangeMs : 0;

    // 并发请求:最新 + 历史 + 统计
    const [latestResp, historyResp, statsResp] = await Promise.all([
      Api.latest(g),
      Api.history(g, { sinceMs, limit: 500 }),
      Api.stats(g, { sinceMs }),
    ]);

    // 服务健康
    const healthResp = await Api.health();
    state.serverOk = !!healthResp.ok;
    if (healthResp.ok) state.serverCount = healthResp.count;

    // ---- API 失败处理 ----
    if (!latestResp.ok) {
      state.apiFailStreak++;
      setSystemStatus("fail", "数据服务连接失败");
      setBanner("error", "数据服务连接失败:无法访问后端 API(" + (latestResp.error || "未知错误") + ")");
      return;
    }
    state.apiFailStreak = 0;

    const rec = latestResp.record;

    // ---- 无数据状态 ----
    if (!rec) {
      setSystemStatus("idle", "等待开发板数据");
      setBanner("info", `等待开发板数据……(分组 ${g} 暂无记录)`);
      updateOverview(null);
      updateDevicePanel(null);
      updateSourceInfo(null);
      updateRaw(null);
      renderAnomalies([{ level: "warn", text: "尚未收到该分组的任何数据" }]);
      Charts.renderHistory([]);
      updateStats(null);
      updateQuality(null);
      return;
    }

    // ---- 记录接收时间(用于估算频率)----
    if (!state.lastRecord || state.lastRecord.received_at_ms !== rec.received_at_ms) {
      state.recvTimes.push(Number(rec.received_at_ms));
      if (state.recvTimes.length > 30) state.recvTimes.shift();
    }

    // ---- 更新各面板 ----
    const st = deviceStateOf(rec);
    if (st.level === "online") {
      setSystemStatus("live", `在线 · ${Math.floor((st.ageMs || 0) / 1000)}s 前更新`);
      setBanner("", "");
    } else if (st.level === "delayed") {
      setSystemStatus("stale", `数据延迟 · ${Math.floor((st.ageMs || 0) / 1000)}s 未更新`);
      setBanner("warn", `数据延迟:已 ${Math.floor((st.ageMs || 0) / 1000)} 秒未收到新数据`);
    } else {
      setSystemStatus("fail", "设备已离线");
      setBanner("error", `设备已离线:最后数据在 ${fmtAgo(rec.received_at_ms)}`);
    }

    updateOverview(rec);
    updateDevicePanel(rec);
    updateSourceInfo(rec);
    updateRaw(rec);
    renderAnomalies(detectAnomalies(rec));
    updateStats(statsResp);
    updateQuality(statsResp);

    // ---- 图表 ----
    if (historyResp.ok && historyResp.records) {
      state.lastRecords = historyResp.records;
      Charts.renderHistory(historyResp.records);
    }
    // 实时图:只在新数据到来时追加
    if (!state.lastRecord || state.lastRecord.received_at_ms !== rec.received_at_ms) {
      Charts.pushPoint(rec);
    }

    state.lastRecord = rec;
  }

  // ---------- 定时器 ----------
  function restartTimer() {
    if (state.timer) clearInterval(state.timer);
    if (!state.paused) {
      state.timer = setInterval(() => refresh(), state.refreshMs);
    }
  }

  // ---------- 事件绑定 ----------
  function bindEvents() {
    // Group ID
    const gInput = $("groupInput");
    if (gInput) {
      gInput.value = state.groupId;
      const apply = Utils.debounce(() => {
        const v = gInput.value.trim() || CONFIG.defaultGroupId;
        if (v === state.groupId) return;
        state.groupId = v;
        localStorage.setItem(CONFIG.storageKeyGroup, v);
        Charts.clear();
        state.lastRecord = null;
        state.recvTimes = [];
        refresh(true);
      }, 400);
      gInput.addEventListener("input", apply);
    }

    // 刷新频率
    const freqSel = $("freqSelect");
    if (freqSel) {
      freqSel.innerHTML = CONFIG.refreshOptions
        .map((o) => `<option value="${o.value}">${o.label}</option>`).join("");
      freqSel.value = String(state.refreshMs);
      freqSel.addEventListener("change", () => {
        state.refreshMs = Number(freqSel.value) || CONFIG.defaultRefreshMs;
        localStorage.setItem(CONFIG.storageKeyFreq, String(state.refreshMs));
        restartTimer();
        toast(`刷新频率已设为 ${freqSel.options[freqSel.selectedIndex].text}`);
      });
    }

    // 暂停 / 继续
    const pauseBtn = $("pauseBtn");
    if (pauseBtn) {
      pauseBtn.addEventListener("click", () => {
        state.paused = !state.paused;
        pauseBtn.textContent = state.paused ? "▶ 继续实时" : "⏸ 暂停实时";
        pauseBtn.classList.toggle("primary", !state.paused);
        if (state.paused) {
          if (state.timer) clearInterval(state.timer);
          state.timer = null;
          setBanner("warn", "已暂停实时刷新(页面显示的是暂停时刻的数据)");
          toast("已暂停");
        } else {
          restartTimer();
          setBanner("", "");
          refresh(true);
          toast("已恢复实时刷新");
        }
      });
    }

    // 手动刷新
    const refreshBtn = $("refreshBtn");
    if (refreshBtn) refreshBtn.addEventListener("click", () => {
      refresh(true);
      toast("已刷新");
    });

    // 清空图表
    const clearBtn = $("clearChartBtn");
    if (clearBtn) clearBtn.addEventListener("click", () => {
      Charts.clear();
      toast("图表已清空");
    });

    // 历史时间范围
    const rangeSel = $("rangeSelect");
    if (rangeSel) {
      rangeSel.innerHTML = CONFIG.historyRanges
        .map((o) => `<option value="${o.value}">${o.label}</option>`).join("");
      rangeSel.value = String(state.historyRangeMs);
      rangeSel.addEventListener("change", () => {
        state.historyRangeMs = Number(rangeSel.value);
        refresh(true);
        toast("已切换时间范围");
      });
    }

    // 导出 CSV
    const csvBtn = $("exportCsvBtn");
    if (csvBtn) csvBtn.addEventListener("click", () => {
      const sinceMs = state.historyRangeMs > 0 ? nowMs() - state.historyRangeMs : 0;
      window.location.href = Api.exportCsvUrl(state.groupId, { sinceMs });
      toast("正在导出 CSV…");
    });

    // 导出 JSON
    const jsonBtn = $("exportJsonBtn");
    if (jsonBtn) jsonBtn.addEventListener("click", () => {
      const data = state.lastRecords || [];
      if (!data.length) { toast("暂无数据可导出"); return; }
      const name = `imu_${state.groupId}_${new Date().toISOString().slice(0,19).replace(/[:T]/g,"")}.json`;
      downloadText(name, JSON.stringify(data, null, 2), "application/json;charset=utf-8");
      toast(`已导出 ${data.length} 条 JSON`);
    });

    // 原始 JSON 折叠
    const rawToggle = $("rawToggle");
    if (rawToggle) rawToggle.addEventListener("click", () => {
      const box = $("rawBox");
      const open = box.classList.toggle("open");
      rawToggle.textContent = open ? "▼ 收起原始数据" : "▶ 展开原始数据";
    });

    // 复制原始 JSON
    const copyBtn = $("copyRawBtn");
    if (copyBtn) copyBtn.addEventListener("click", async () => {
      const pre = $("rawPreview");
      const ok = await copyText(pre ? pre.textContent : "");
      toast(ok ? "已复制到剪贴板" : "复制失败,请手动选择复制");
    });

    // 历史图曲线显隐
    ["histX", "histY", "histZ"].forEach((id, idx) => {
      const cb = $(id);
      if (cb) cb.addEventListener("change", () => Charts.toggleHistorySeries(idx, cb.checked));
    });

    // 页面可见性:切回前台立即刷新
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && !state.paused) refresh(true);
    });
  }

  // ---------- 轻量提示 ----------
  let toastTimer = null;
  function toast(msg) {
    const el = $("toast");
    if (!el) return;
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 1800);
  }

  // ---------- 启动 ----------
  function init() {
    // 恢复本地设置
    const savedGroup = localStorage.getItem(CONFIG.storageKeyGroup);
    if (savedGroup) state.groupId = savedGroup;
    const savedFreq = Number(localStorage.getItem(CONFIG.storageKeyFreq));
    if (savedFreq && CONFIG.refreshOptions.some((o) => o.value === savedFreq)) {
      state.refreshMs = savedFreq;
    }

    Charts.init();
    Attitude.init();
    bindEvents();

    setSystemStatus("idle", "正在连接…");
    setBanner("info", "正在连接数据服务…");
    refresh(true).then(() => restartTimer());

    // 姿态图随最新数据更新
    setInterval(() => {
      const rec = state.lastRecord;
      if (!rec) return;
      const a = accOf(rec);
      Attitude.draw(a.x, a.y, a.z);
    }, 200);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
