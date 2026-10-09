/**
 * charts.js —— 图表与可视化
 * 1) 三轴加速度实时图 (m/s²)
 * 2) 合加速度实时图
 * 3) 历史数据图
 * 4) 姿态可视化(基于重力方向的粗略估计)
 */
const Charts = (() => {
  const { colors } = CONFIG;
  const { fmtTime, magnitude } = Utils;

  let chartXYZ = null;     // 三轴加速度
  let chartMag = null;     // 合加速度
  let chartHistory = null; // 历史数据

  // 数据缓冲(前端保留最近 N 点)
  const buf = {
    labels: [],
    x: [], y: [], z: [], mag: [],
  };

  const baseOpts = (yTitle, fps) => {
    const f = fps || CONFIG.chart.fps;
    const animMs = Math.max(60, CONFIG.chart.animationMs);
    return {
      responsive: true,
      maintainAspectRatio: false,
      // 动画时长跟随数据更新间隔,曲线持续平滑移动
      animation: {
        duration: animMs,
        easing: "easeOutQuad",
      },
      animations: {
        y: { duration: animMs, easing: "easeOutQuad" },
        x: { duration: 0 },
      },
      // 关闭 Chart.js 默认的节流,交给外层 RAF 循环按目标帧率驱动
      animationLoop: undefined,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { boxWidth: 12, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${Number(ctx.parsed.y).toFixed(3)}`,
          },
        },
      },
      scales: {
        x: {
          ticks: { maxTicksLimit: 6, font: { size: 10 } },
          grid: { color: "rgba(0,0,0,0.04)" },
        },
        y: {
          title: { display: !!yTitle, text: yTitle, font: { size: 11 } },
          ticks: { font: { size: 10 } },
          grid: { color: "rgba(0,0,0,0.06)" },
        },
      },
      // 记录目标帧率,供 RAF 循环使用
      _targetFps: f,
    };
  };

  // 曲线平滑参数:monotone 插值不会产生过冲(比默认的 cubic 更稳),张力 0.4 让线条更圆润
  const SMOOTH = {
    tension: 0.4,
    cubicInterpolationMode: "monotone",
    borderCapStyle: "round",
    borderJoinStyle: "round",
  };

  function init() {
    if (typeof Chart === "undefined") {
      console.warn("[charts] Chart.js 未加载,图表功能不可用");
      return false;
    }
    Chart.defaults.font.family =
      '-apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';

    const c1 = document.getElementById("chartXYZ");
    const c2 = document.getElementById("chartMag");
    if (c1) {
      chartXYZ = new Chart(c1, {
        type: "line",
        data: {
          labels: [],
          datasets: [
            { label: "X", data: [], borderColor: colors.x, backgroundColor: colors.x, borderWidth: 2, pointRadius: 0, pointHitRadius: 8, ...SMOOTH },
            { label: "Y", data: [], borderColor: colors.y, backgroundColor: colors.y, borderWidth: 2, pointRadius: 0, pointHitRadius: 8, ...SMOOTH },
            { label: "Z", data: [], borderColor: colors.z, backgroundColor: colors.z, borderWidth: 2, pointRadius: 0, pointHitRadius: 8, ...SMOOTH },
          ],
        },
        options: baseOpts("m/s²"),
      });
    }
    if (c2) {
      chartMag = new Chart(c2, {
        type: "line",
        data: {
          labels: [],
          datasets: [
            { label: "合加速度", data: [], borderColor: colors.mag, backgroundColor: "rgba(139,92,246,0.12)", borderWidth: 2.2, pointRadius: 0, pointHitRadius: 8, fill: true, ...SMOOTH },
          ],
        },
        options: baseOpts("m/s²"),
      });
    }
    const c3 = document.getElementById("chartHistory");
    if (c3) {
      // 历史图用"真实时间轴"(linear + 毫秒)而不是分类轴:
      // 分类轴下每个点占一个固定槽位,窗口一滑动所有点就集体换槽位,
      // 表现为整条线硬跳一格。改成时间轴后点按真实时刻定位,
      // 窗口右移变成连续平移,再配合 x 轴动画就是平滑滚动。
      const histOpts = baseOpts("m/s²", CONFIG.chart.historyFps);
      histOpts.scales.x.type = "linear";
      histOpts.scales.x.ticks = {
        maxTicksLimit: 6,
        font: { size: 10 },
        callback: (v) => fmtTime(v),
      };
      // x 轴动画跟随历史刷新间隔,让平移连续而不是瞬移
      histOpts.animations = {
        y: { duration: Math.max(60, CONFIG.chart.animationMs), easing: "easeOutQuad" },
        x: { duration: CONFIG.chart.historyRefreshMs || 1000, easing: "linear" },
      };
      chartHistory = new Chart(c3, {
        type: "line",
        data: { labels: [], datasets: [] },
        options: histOpts,
      });
    }

    startRenderLoop();   // 启动 120fps 渲染循环
    return true;
  }

  /** 清空实时图表 */
  function clear() {
    buf.labels.length = 0;
    buf.x.length = 0; buf.y.length = 0; buf.z.length = 0; buf.mag.length = 0;
    markDirty();
  }

  // ---------- 高帧率渲染循环 ----------
  // 数据到达时只标记"脏",由 RAF 按目标帧率(默认 120fps)统一重绘,
  // 避免每个数据点都触发一次重排,也保证动画帧率稳定。
  let rafId = null;
  let dirty = false;
  let histDirty = false;   // 历史图是否需要重绘
  let lastDraw = 0;
  let lastHistDraw = 0;    // 历史图上次重绘时间(按 historyFps 节流)

  function markDirty() { dirty = true; }

  function startRenderLoop() {
    if (rafId !== null) return;
    const targetFps = Math.max(30, Math.min(240, CONFIG.chart.fps || 60));
    const minInterval = 1000 / targetFps;   // 120fps → 8.33ms

    const loop = (ts) => {
      if (dirty && (ts - lastDraw) >= minInterval) {
        lastDraw = ts;
        dirty = false;
        drawNow(ts);
      }
      rafId = requestAnimationFrame(loop);
    };
    rafId = requestAnimationFrame(loop);
  }

  function stopRenderLoop() {
    if (rafId !== null) {
      cancelAnimationFrame(rafId);
      rafId = null;
    }
  }

  /** 真正的重绘(实时图 + 历史图统一在 RAF 循环里刷新,历史图单独按 historyFps 节流) */
  function drawNow(ts) {
    if (chartXYZ) {
      chartXYZ.data.labels = buf.labels;
      chartXYZ.data.datasets[0].data = buf.x;
      chartXYZ.data.datasets[1].data = buf.y;
      chartXYZ.data.datasets[2].data = buf.z;
      chartXYZ.update();
    }
    if (chartMag) {
      chartMag.data.labels = buf.labels;
      chartMag.data.datasets[0].data = buf.mag;
      chartMag.update();
    }
    // 历史图点数多,单独按 historyFps 节流,避免每次实时重绘都拖着历史图一起算
    if (chartHistory && histDirty) {
      const histMin = 1000 / Math.max(30, Math.min(240, CONFIG.chart.historyFps || 60));
      if (ts === undefined || ts - lastHistDraw >= histMin) {
        lastHistDraw = ts || 0;
        histDirty = false;
        chartHistory.update();
      }
    }
  }

  /** 追加一个实时数据点 */
  function pushPoint(record) {
    const d = (record && record.data) || {};
    const x = Utils.toNum(d.acc_x);
    const y = Utils.toNum(d.acc_y);
    const z = Utils.toNum(d.acc_z);
    const mag = magnitude(x, y, z);

    buf.labels.push(fmtTime(record.received_at_ms));
    buf.x.push(x);
    buf.y.push(y);
    buf.z.push(z);
    buf.mag.push(mag);

    const max = CONFIG.chart.maxPoints;
    if (buf.labels.length > max) {
      const over = buf.labels.length - max;
      buf.labels.splice(0, over);
      buf.x.splice(0, over);
      buf.y.splice(0, over);
      buf.z.splice(0, over);
      buf.mag.splice(0, over);
    }
    markDirty();   // 交给 RAF 循环渲染
  }

  function render() {
    markDirty();
  }

  /** 渲染历史数据图(传 records 数组) */
  function renderHistory(records) {
    if (!chartHistory || !records || !records.length) {
      if (chartHistory) {
        chartHistory.data.labels = [];
        chartHistory.data.datasets = [];
        histDirty = true;    // 交给 RAF 循环重绘
      }
      return;
    }
    // 按"绝对时间网格"分桶聚合(而不是按索引取模 i % step):
    // 桶边界对齐到 epoch 的整数倍,新点进来只会新增/更新最后一个桶,
    // 已有桶的位置一动不动,曲线不会再整体跳格。
    const MAXP = CONFIG.chart.historyMaxPoints || 800;
    const t0 = records[0].received_at_ms;
    const t1 = records[records.length - 1].received_at_ms;
    const span = Math.max(1, t1 - t0);
    // 桶宽取 200ms 的整数倍,保证网格稳定
    const bucketMs = Math.max(200, Math.ceil(span / MAXP / 200) * 200);

    const buckets = new Map();   // bucketKey -> { t, x, y, z, n }
    for (const r of records) {
      const k = Math.floor(r.received_at_ms / bucketMs);
      let b = buckets.get(k);
      if (!b) {
        b = { t: k * bucketMs, x: 0, y: 0, z: 0, n: 0 };
        buckets.set(k, b);
      }
      const d = r.data || {};
      b.x += Utils.toNum(d.acc_x);
      b.y += Utils.toNum(d.acc_y);
      b.z += Utils.toNum(d.acc_z);
      b.n++;
    }
    const pts = [...buckets.values()].sort((a, b) => a.t - b.t).map((b) => ({
      t: b.t, x: b.x / b.n, y: b.y / b.n, z: b.z / b.n,
    }));

    const defs = [
      ["x", "X", colors.x],
      ["y", "Y", colors.y],
      ["z", "Z", colors.z],
    ];
    const mk = (key, label, color) => ({
      label,
      data: pts.map((p) => ({ x: p.t, y: p[key] })),
      borderColor: color, backgroundColor: color,
      borderWidth: 1.8, pointRadius: 0, pointHitRadius: 8,
      ...SMOOTH,
    });

    // 复用 dataset 对象,只替换 data:整体替换会让 Chart.js 当成全新数据集,
    // 每刷新一次就重放入场动画(表现为闪烁)
    if (chartHistory.data.datasets.length !== defs.length) {
      chartHistory.data.datasets = defs.map(([k, l, c]) => mk(k, l, c));
    } else {
      // 只换 data 引用、保留 dataset 对象本身:Chart.js 会做数据过渡,
      // 而不会像"替换整个 datasets 数组"那样重放入场动画
      defs.forEach(([k, l, c], i) => {
        chartHistory.data.datasets[i].data = pts.map((p) => ({ x: p.t, y: p[k] }));
      });
    }
    chartHistory.data.labels = [];
    histDirty = true;        // 交给 RAF 循环重绘
  }

  /** 切换历史图某条曲线的显示 */
  function toggleHistorySeries(index, visible) {
    if (!chartHistory || !chartHistory.data.datasets[index]) return;
    chartHistory.data.datasets[index].hidden = !visible;
    histDirty = true;
  }

  return { init, pushPoint, clear, renderHistory, toggleHistorySeries };
})();


/**
 * 姿态可视化:基于重力方向的粗略估计。
 * ⚠️ 只有加速度数据时,无法得到准确的绝对姿态(需要陀螺仪做积分)。
 * 这里用静止重力方向做"倾斜角"估计,晃动时会有噪声,属于正常现象。
 */
const Attitude = (() => {
  let canvas = null, ctx = null;

  function init() {
    canvas = document.getElementById("attitudeCanvas");
    if (!canvas) return false;
    ctx = canvas.getContext("2d");
    draw(null, null, null);
    return true;
  }

  /** 由加速度求倾斜角(度) */
  function tiltFromAcc(ax, ay, az) {
    if (ax === null || ay === null || az === null) return null;
    const rad2deg = 180 / Math.PI;
    return {
      // 绕 X/Y 轴的倾角(板子相对水平面的倾斜)
      pitch: Math.atan2(-ax, Math.sqrt(ay * ay + az * az)) * rad2deg,
      roll: Math.atan2(ay, az) * rad2deg,
      yaw: null,  // 加速度无法测偏航角
    };
  }

  /** 画一个简单的 3D 立方体,按重力方向旋转 */
  function draw(ax, ay, az) {
    if (!ctx || !canvas) return;
    const W = canvas.width, H = canvas.height;
    ctx.clearRect(0, 0, W, H);

    const t = tiltFromAcc(ax, ay, az);
    const pitch = t ? (t.pitch * Math.PI / 180) : 0;
    const roll = t ? (t.roll * Math.PI / 180) : 0;

    const cx = W / 2, cy = H / 2, s = Math.min(W, H) * 0.26;

    // 立方体 8 个顶点
    const V = [
      [-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
      [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1],
    ];
    const E = [
      [0,1],[1,2],[2,3],[3,0],
      [4,5],[5,6],[6,7],[7,4],
      [0,4],[1,5],[2,6],[3,7],
    ];

    // 旋转(先绕 X 轴 pitch,再绕 Y 轴 roll)
    const rot = (p) => {
      let [x, y, z] = p;
      let y1 = y * Math.cos(pitch) - z * Math.sin(pitch);
      let z1 = y * Math.sin(pitch) + z * Math.cos(pitch);
      let x2 = x * Math.cos(roll) + z1 * Math.sin(roll);
      let z2 = -x * Math.sin(roll) + z1 * Math.cos(roll);
      return [x2, y1, z2];
    };

    const proj = (p) => {
      const [x, y, z] = rot(p);
      const f = 3.2;
      const k = f / (f + z * 0.6);
      return [cx + x * s * k, cy + y * s * k, z];
    };

    const P = V.map(proj);

    // 画边
    ctx.lineWidth = 2;
    E.forEach(([a, b]) => {
      const za = P[a][2], zb = P[b][2];
      ctx.strokeStyle = (za + zb) / 2 > 0 ? "#93a4bd" : "#c8d2e0";
      ctx.beginPath();
      ctx.moveTo(P[a][0], P[a][1]);
      ctx.lineTo(P[b][0], P[b][1]);
      ctx.stroke();
    });

    // 画顶点
    P.forEach((p) => {
      ctx.beginPath();
      ctx.arc(p[0], p[1], 2.2, 0, Math.PI * 2);
      ctx.fillStyle = "#3b6fd4";
      ctx.fill();
    });

    // 重力方向箭头(从中心指向"下")
    if (ax !== null && ay !== null && az !== null) {
      const m = Math.sqrt(ax * ax + ay * ay + az * az) || 1;
      const g = [ax / m, ay / m, az / m];
      const gp = rot(g);
      const ex = cx + gp[0] * s * 1.5;
      const ey = cy + gp[1] * s * 1.5;
      ctx.strokeStyle = "#e5484d";
      ctx.lineWidth = 2.4;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(ex, ey);
      ctx.stroke();
      // 箭头
      const ang = Math.atan2(ey - cy, ex - cx);
      ctx.beginPath();
      ctx.moveTo(ex, ey);
      ctx.lineTo(ex - 9 * Math.cos(ang - 0.4), ey - 9 * Math.sin(ang - 0.4));
      ctx.lineTo(ex - 9 * Math.cos(ang + 0.4), ey - 9 * Math.sin(ang + 0.4));
      ctx.closePath();
      ctx.fillStyle = "#e5484d";
      ctx.fill();
    }
  }

  return { init, draw, tiltFromAcc };
})();
