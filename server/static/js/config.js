/**
 * config.js —— 全局配置集中管理
 * 所有阈值、频率、选项都放这里,避免散落在各处。
 */
const CONFIG = {
  // ---------- 服务器 ----------
  api: {
    latest: "/api/latest",
    history: "/api/history",
    stats: "/api/stats",
    exportCsv: "/api/export.csv",
    health: "/api/health",
    groups: "/api/groups",
    // 第 2 周:远程采集任务
    taskCreate: "/api/task",      // POST 创建任务
    taskGet: "/api/task",         // GET /api/task/<id> 查询状态
    taskList: "/api/tasks",       // GET /api/tasks 任务列表
    // 第 3 周:按键触发事件
    eventList: "/api/events",     // GET 事件列表(只含服务端真正收到过的)
    eventAck: "/api/event",       // POST /api/event/<id>/ack   回应
    eventCancel: "/api/event",    // POST /api/event/<id>/cancel 取消
  },

  // ---------- 远程采集任务 ----------
  task: {
    pollIntervalMs: 1000,    // 任务状态轮询间隔
    pollTimeoutMs: 20000,    // 前端等待任务完成的上限(超时后不再轮询,以服务器状态为准)
    historyLimit: 5,         // 最近任务列表条数
  },

  // ---------- 默认值 ----------
  defaultGroupId: "G03",
  storageKeyGroup: "imu_group_id",       // Group ID 持久化
  storageKeyFreq: "imu_refresh_ms",      // 刷新频率持久化

  // ---------- 数据刷新频率(ms) ----------
  // 板端 5Hz(200ms)上传,前端默认 200ms 拉取,保证每个新数据点都能被及时取到。
  refreshOptions: [
    { label: "100ms", value: 100 },
    { label: "200ms", value: 200 },
    { label: "500ms", value: 500 },
    { label: "1s", value: 1000 },
    { label: "2s", value: 2000 },
  ],
  defaultRefreshMs: 200,

  // ---------- 图表 ----------
  chart: {
    // 板端 5Hz(200ms)上传,300 点 ≈ 60 秒窗口,兼顾流畅与信息量
    maxPoints: 300,
    yPadding: 0.15,         // Y 轴上下留白比例

    // 渲染帧率:用 requestAnimationFrame 驱动,按此帧率节流重绘
    // 144fps ≈ 6.94ms/帧。显示器不支持高刷时浏览器会自动降到实际刷新率。
    fps: 144,

    // 曲线动画时长(ms):略小于数据到达间隔(200ms),
    // 避免上一段动画还没走完就来新点导致跳变或堆积
    animationMs: 150,

    // 历史图数据量大,单独限制点数与帧率,避免卡顿
    historyMaxPoints: 800,
    historyFps: 120,

    // 历史图的刷新间隔(ms)。
    // 实时曲线跟数据走(200ms);历史是"分析视图",1s 更新一次足够,
    // 更新太勤反而整条线一直在平移,看着就是一跳一跳。
    historyRefreshMs: 1000,
  },

  // ---------- 设备在线状态判定(基于最后收到数据的时间) ----------
  // 注意:不依赖网页刷新时间,而是用服务端的 received_at_ms
  deviceState: {
    onlineMs: 5000,         // <5s   → 在线
    delayedMs: 30000,       // <30s  → 延迟;  >=30s → 离线
  },

  // ---------- 异常检测阈值(集中配置) ----------
  thresholds: {
    // 合加速度合理范围(单位 m/s²)。静止约 9.8,剧烈晃动可到 30+
    magMin: 2.0,
    magMax: 40.0,
    // 单轴绝对值上限
    axisMax: 40.0,
    // RSSI 过低告警(dBm)
    rssiWeak: -85,
    // 数据延迟告警(ms)
    staleMs: 10000,
    // 采样频率异常范围(Hz)
    hzMin: 0.5,
    hzMax: 5.0,
    // 时间戳异常:相邻时间差超过此值算异常间隔
    tsGapMs: 3000,
    // 数据质量分低于此值告警
    qualityMin: 70,
  },

  // ---------- 历史数据时间范围 ----------
  historyRanges: [
    { label: "最近 1 分钟", value: 60 * 1000 },
    { label: "最近 5 分钟", value: 5 * 60 * 1000 },
    { label: "最近 30 分钟", value: 30 * 60 * 1000 },
    { label: "最近 1 小时", value: 60 * 60 * 1000 },
    { label: "全部数据", value: 0 },       // 0 = 不限时间
  ],
  defaultHistoryRange: 5 * 60 * 1000,

  // ---------- 图表配色(X/Y/Z 用不同颜色区分) ----------
  colors: {
    x: "#e5484d",
    y: "#2f8f4e",
    z: "#3b6fd4",
    mag: "#8b5cf6",
    rssi: "#d97706",
  },
};
