/**
 * utils.js —— 通用工具函数
 * 数据格式化、安全取值、统计计算。不依赖其他模块。
 */
const Utils = (() => {
  const $ = (id) => document.getElementById(id);
  const nowMs = () => Date.now();

  /** 数字格式化:根据量级自动选精度 */
  function fmtNum(v, digits) {
    if (v === null || v === undefined || v === "" || Number.isNaN(Number(v))) return "--";
    const n = Number(v);
    if (!Number.isFinite(n)) return "--";
    if (digits !== undefined) return n.toFixed(digits);
    const a = Math.abs(n);
    if (a >= 1000) return n.toFixed(0);
    if (a >= 100) return n.toFixed(1);
    if (a >= 1) return n.toFixed(2);
    return n.toFixed(3);
  }

  /** 带单位格式化 */
  function fmtWithUnit(v, unit, digits) {
    const s = fmtNum(v, digits);
    return s === "--" ? "--" : `${s} ${unit}`;
  }

  /** 时间格式化 */
  function fmtTime(ms) {
    if (!ms || !Number.isFinite(Number(ms))) return "--";
    const d = new Date(Number(ms));
    if (Number.isNaN(d.getTime())) return "--";
    const p = (x) => String(x).padStart(2, "0");
    return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  }

  function fmtDateTime(ms) {
    if (!ms || !Number.isFinite(Number(ms))) return "--";
    const d = new Date(Number(ms));
    if (Number.isNaN(d.getTime())) return "--";
    const p = (x) => String(x).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
           `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  }

  /** 相对时间:"3 秒前" */
  function fmtAgo(ms) {
    if (!ms || !Number.isFinite(Number(ms))) return "--";
    const s = Math.max(0, Math.floor((nowMs() - Number(ms)) / 1000));
    if (s < 60) return `${s} 秒前`;
    if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
    return `${Math.floor(s / 3600)} 小时前`;
  }

  /** 安全读取嵌套字段(缺失返回 null,不抛错) */
  function pick(obj, path, fallback = null) {
    if (!obj) return fallback;
    const parts = path.split(".");
    let cur = obj;
    for (const p of parts) {
      if (cur === null || cur === undefined || typeof cur !== "object") return fallback;
      cur = cur[p];
    }
    return cur === undefined ? fallback : cur;
  }

  /** 安全转数字,失败返回 null */
  function toNum(v) {
    if (v === null || v === undefined || v === "") return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  /** 从一条 record 里取出三轴加速度(m/s²) */
  function accOf(record) {
    const d = (record && record.data) || {};
    return {
      x: toNum(d.acc_x),
      y: toNum(d.acc_y),
      z: toNum(d.acc_z),
    };
  }

  /** 合加速度 */
  function magnitude(x, y, z) {
    if (x === null || y === null || z === null) return null;
    return Math.sqrt(x * x + y * y + z * z);
  }

  /** 从 record 直接算合加速度 */
  function magOf(record) {
    const a = accOf(record);
    return magnitude(a.x, a.y, a.z);
  }

  // ---------- 统计 ----------
  function mean(arr) {
    if (!arr.length) return null;
    return arr.reduce((s, v) => s + v, 0) / arr.length;
  }

  function std(arr) {
    if (arr.length < 2) return null;
    const m = mean(arr);
    const v = arr.reduce((s, x) => s + (x - m) ** 2, 0) / arr.length;
    return Math.sqrt(v);
  }

  function describe(arr) {
    const vals = arr.filter((v) => v !== null && Number.isFinite(v));
    if (!vals.length) return null;
    const mn = Math.min(...vals), mx = Math.max(...vals);
    return {
      count: vals.length,
      min: mn,
      max: mx,
      avg: mean(vals),
      std: std(vals),
      ptp: mx - mn,
    };
  }

  /** 防抖 */
  function debounce(fn, wait) {
    let t = null;
    return function (...args) {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), wait);
    };
  }

  /** 下载文本文件 */
  function downloadText(filename, text, mime = "text/plain;charset=utf-8") {
    const blob = new Blob([text], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }, 0);
  }

  /** 复制到剪贴板(带降级) */
  async function copyText(text) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (e) { /* 落到降级方案 */ }
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch (e) {
      return false;
    }
  }

  return {
    $, nowMs, fmtNum, fmtWithUnit, fmtTime, fmtDateTime, fmtAgo,
    pick, toNum, accOf, magnitude, magOf,
    mean, std, describe, debounce, downloadText, copyText,
  };
})();
