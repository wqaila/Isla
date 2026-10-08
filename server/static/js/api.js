/**
 * api.js —— API 请求层
 * 所有与后端的通信都走这里,便于统一处理错误和节流。
 * 复用现有 API(/api/latest、/api/history),新增接口向后兼容。
 */
const Api = (() => {
  const { nowMs } = Utils;

  /** 统一 fetch 包装:超时 + 错误归一化 */
  async function request(url, { timeoutMs = 8000 } = {}) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const resp = await fetch(url, { signal: ctrl.signal, cache: "no-store" });
      if (!resp.ok) {
        return { ok: false, error: `HTTP ${resp.status}`, status: resp.status };
      }
      const json = await resp.json();
      return json;
    } catch (e) {
      const msg = e && e.name === "AbortError" ? "请求超时" : (e && e.message) || "网络错误";
      return { ok: false, error: msg };
    } finally {
      clearTimeout(timer);
    }
  }

  /** 最新一条 */
  function latest(groupId) {
    const u = `${CONFIG.api.latest}?group_id=${encodeURIComponent(groupId)}&_=${nowMs()}`;
    return request(u);
  }

  /** 历史记录(支持时间范围) */
  function history(groupId, { sinceMs = 0, limit = 200 } = {}) {
    let u = `${CONFIG.api.history}?group_id=${encodeURIComponent(groupId)}&limit=${limit}`;
    if (sinceMs > 0) u += `&since_ms=${sinceMs}`;
    u += `&_=${nowMs()}`;
    return request(u, { timeoutMs: 12000 });
  }

  /** 统计 */
  function stats(groupId, { sinceMs = 0 } = {}) {
    let u = `${CONFIG.api.stats}?group_id=${encodeURIComponent(groupId)}`;
    if (sinceMs > 0) u += `&since_ms=${sinceMs}`;
    u += `&_=${nowMs()}`;
    return request(u, { timeoutMs: 12000 });
  }

  /** 服务健康 */
  function health() {
    return request(`${CONFIG.api.health}?_=${nowMs()}`, { timeoutMs: 5000 });
  }

  /** 分组列表 */
  function groups() {
    return request(`${CONFIG.api.groups}?_=${nowMs()}`);
  }

  /** CSV 导出下载地址(交给浏览器直接下载) */
  function exportCsvUrl(groupId, { sinceMs = 0, limit = 20000 } = {}) {
    let u = `${CONFIG.api.exportCsv}?group_id=${encodeURIComponent(groupId)}&limit=${limit}`;
    if (sinceMs > 0) u += `&since_ms=${sinceMs}`;
    return u;
  }

  return { request, latest, history, stats, health, groups, exportCsvUrl };
})();
