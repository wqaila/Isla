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

  /** POST JSON(远程采集任务用) */
  async function postJson(url, body, { timeoutMs = 8000 } = {}) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: ctrl.signal,
        cache: "no-store",
      });
      if (!resp.ok) {
        let detail = `HTTP ${resp.status}`;
        try {
          const j = await resp.json();
          if (j && j.error) detail = j.error;
        } catch (_) { /* 保留 HTTP 状态码 */ }
        return { ok: false, error: detail, status: resp.status };
      }
      return await resp.json();
    } catch (e) {
      const msg = e && e.name === "AbortError" ? "请求超时" : (e && e.message) || "网络错误";
      return { ok: false, error: msg };
    } finally {
      clearTimeout(timer);
    }
  }

  /** 创建远程采集任务。action: sample | pause | resume */
  function createTask(groupId, action = "sample") {
    return postJson(CONFIG.api.taskCreate, { group_id: groupId, action });
  }

  /** 查询单个任务状态 */
  function getTask(requestId) {
    return request(`${CONFIG.api.taskGet}/${encodeURIComponent(requestId)}?_=${nowMs()}`);
  }

  /** 任务列表(最近 N 条,按分组过滤) */
  function tasks(groupId, { limit = 5 } = {}) {
    const u = `${CONFIG.api.taskList}?group_id=${encodeURIComponent(groupId)}&limit=${limit}&_=${nowMs()}`;
    return request(u);
  }

  /** 事件列表(第 3 周)。只含服务端真正收到过的事件 —— 断网期间板端的
   *  本地触发不会出现在列表里,这正是"本地确认 ≠ 远端收到"的体现。 */
  function events(groupId, { limit = 10 } = {}) {
    const u = `${CONFIG.api.eventList}?group_id=${encodeURIComponent(groupId)}&limit=${limit}&_=${nowMs()}`;
    return request(u);
  }

  /** 回应某个事件 */
  function ackEvent(eventId, note = "") {
    return postJson(`${CONFIG.api.eventAck}/${encodeURIComponent(eventId)}/ack`, { note });
  }

  /** 取消某个事件 */
  function cancelEvent(eventId, note = "") {
    return postJson(`${CONFIG.api.eventCancel}/${encodeURIComponent(eventId)}/cancel`, { note });
  }

  /** 自然语言查询(第 4 周)。
   *  服务端最多等板端回执 12 秒,所以这里超时给到 20 秒。 */
  function nlqQuery(text, { groupId = "", wait = true } = {}) {
    return postJson(CONFIG.api.nlq, { text, group_id: groupId, wait }, { timeoutMs: 20000 });
  }

  return { request, postJson, latest, history, stats, health, groups, exportCsvUrl,
           createTask, getTask, tasks, events, ackEvent, cancelEvent, nlqQuery };
})();
