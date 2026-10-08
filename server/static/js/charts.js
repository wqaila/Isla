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

  const baseOpts = (yTitle) => ({
    responsive: true,
    maintainAspectRatio: false,
    // 开启动画:每次追加数据点时平滑过渡,而不是生硬跳变
    animation: {
      duration: 420,
      easing: "easeOutQuad",
    },
    // 数据高频到达时不要重新播放整段动画
    animations: {
      y: { duration: 420, easing: "easeOutQuad" },
      x: { duration: 0 },
    },
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
  });

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
      chartHistory = new Chart(c3, {
        type: "line",
        data: { labels: [], datasets: [] },
        options: baseOpts("m/s²"),
      });
    }
    return true;
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
    render();
  }

  function render() {
    if (chartXYZ) {
      chartXYZ.data.labels = buf.labels.slice();
      chartXYZ.data.datasets[0].data = buf.x.slice();
      chartXYZ.data.datasets[1].data = buf.y.slice();
      chartXYZ.data.datasets[2].data = buf.z.slice();
      chartXYZ.update();          // 带动画:新点平滑滑入
    }
    if (chartMag) {
      chartMag.data.labels = buf.labels.slice();
      chartMag.data.datasets[0].data = buf.mag.slice();
      chartMag.update();
    }
  }

  /** 清空实时图表 */
  function clear() {
    buf.labels.length = 0;
    buf.x.length = 0; buf.y.length = 0; buf.z.length = 0; buf.mag.length = 0;
    render();
  }

  /** 渲染历史数据图(传 records 数组) */
  function renderHistory(records) {
    if (!chartHistory || !records || !records.length) {
      if (chartHistory) {
        chartHistory.data.labels = [];
        chartHistory.data.datasets = [];
        chartHistory.update("none");
      }
      return;
    }
    // 数据量大时抽样,避免前端卡顿
    const MAXP = 300;
    const step = Math.max(1, Math.ceil(records.length / MAXP));
    const sampled = records.filter((_, i) => i % step === 0);

    const labels = sampled.map((r) => fmtTime(r.received_at_ms));
    const mk = (key, label, color) => ({
      label,
      data: sampled.map((r) => Utils.toNum((r.data || {})[key])),
      borderColor: color, backgroundColor: color,
      borderWidth: 1.8, pointRadius: 0, pointHitRadius: 8,
      ...SMOOTH,
    });

    chartHistory.data.labels = labels;
    chartHistory.data.datasets = [
      mk("acc_x", "X", colors.x),
      mk("acc_y", "Y", colors.y),
      mk("acc_z", "Z", colors.z),
    ];
    chartHistory.update("none");
  }

  /** 切换历史图某条曲线的显示 */
  function toggleHistorySeries(index, visible) {
    if (!chartHistory || !chartHistory.data.datasets[index]) return;
    chartHistory.data.datasets[index].hidden = !visible;
    chartHistory.update("none");
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
