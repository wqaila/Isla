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
  },

  // ---------- 默认值 ----------
  defaultGroupId: "G03",
  storageKeyGroup: "imu_group_id",       // Group ID 持久化
  storageKeyFreq: "imu_refresh_ms",      // 刷新频率持久化

  // ---------- 数据刷新频率(ms) ----------
  refreshOptions: [
    { label: "200ms", value: 200 },
    { label: "500ms", value: 500 },
    { label: "1s", value: 1000 },
    { label: "2s", value: 2000 },
    { label: "5s", value: 5000 },
  ],
  defaultRefreshMs: 500,

  // ---------- 图表 ----------
  chart: {
    // 板端上传频率已提升到 5Hz(200ms),150 点 ≈ 30 秒窗口,兼顾流畅与信息量
    maxPoints: 150,
    yPadding: 0.15,         // Y 轴上下留白比例
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
