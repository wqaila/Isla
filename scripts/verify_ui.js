/**
 * Web UI 层冒烟复验(第 2 周任务卡片 + 第 4 周自然语言卡片)
 *
 * 目的:接口层(verify_week2 / verify_week4)跑的是 CLI,页面按钮是否真的
 *      绑对了、点了有没有反应、有没有 JS 报错,只有真浏览器能证明。
 *
 * 实现:puppeteer-core 驱动**系统自带的 Edge**,不下载 Chromium。
 *
 * 用法:
 *   cd server && python app.py                 # 先起服务
 *   node scripts/verify_ui.js                  # 跑本脚本(需要 NODE_PATH 指向 puppeteer-core)
 *   node scripts/verify_ui.js --shots          # 额外产出演示截图到 docs/screenshots/
 */
const path = require("path");
const fs = require("fs");

const PUPPETEER = "C:/Users/user/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core";
const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const BASE = process.env.BASE_URL || "http://127.0.0.1:8000";
const WANT_SHOTS = process.argv.includes("--shots");
const SHOT_DIR = path.resolve(__dirname, "..", "docs", "screenshots");

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok, detail: detail || "" });
  console.log(`[${ok ? "ok  " : "FAIL"}] ${name}${detail ? "  — " + detail : ""}`);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 轮询等待某个条件成立 */
async function waitFor(page, fn, timeoutMs, label) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      if (await page.evaluate(fn)) return true;
    } catch (_) { /* 页面重渲染中,忽略 */ }
    await sleep(300);
  }
  console.log(`       (等「${label}」超时 ${timeoutMs}ms)`);
  return false;
}

(async () => {
  if (!fs.existsSync(EDGE)) {
    console.error("找不到 Edge:" + EDGE);
    process.exit(2);
  }
  const puppeteer = require(PUPPETEER);

  const browser = await puppeteer.launch({
    executablePath: EDGE,
    headless: "new",
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1400, height: 1000, deviceScaleFactor: 1 });

  // 收集前端报错 —— 这是 CLI 验证永远抓不到的一类问题
  const jsErrors = [];
  page.on("pageerror", (e) => jsErrors.push("pageerror: " + e.message));
  page.on("console", (m) => {
    if (m.type() === "error") jsErrors.push("console.error: " + m.text());
  });
  page.on("requestfailed", (r) => {
    // 只关心本站资源,忽略 CDN(Chart.js 可能走外网)
    if (r.url().startsWith(BASE)) jsErrors.push("requestfailed: " + r.url());
  });

  console.log("==============================================================");
  console.log("  Web UI 层冒烟复验(真实浏览器点击)");
  console.log("  页面: " + BASE);
  console.log("==============================================================\n");

  // ---------- 1) 页面加载 ----------
  console.log("--------------------------------------------------------------");
  console.log("1) 页面加载与实时指标");
  console.log("--------------------------------------------------------------");
  // 注意:页面有持续的轮询刷新,网络永远不会 idle,不能用 networkidle2
  await page.goto(BASE, { waitUntil: "domcontentloaded", timeout: 30000 });

  const hasMetrics = await waitFor(page, () => {
    const el = document.getElementById("mMag");
    return el && el.textContent && el.textContent.trim() !== "--";
  }, 20000, "实时指标出现");
  check("实时指标渲染出数值(非 --)", hasMetrics,
    hasMetrics ? "合=" + await page.$eval("#mMag", (e) => e.textContent.trim()) + " m/s²" : "");

  const devId = await page.$eval("#devId", (e) => e.textContent.trim());
  check("设备状态卡片显示设备 ID", devId && devId !== "--", "devId=" + devId);

  const qpct = await page.$eval("#qualityPct", (e) => e.textContent.trim());
  check("数据质量卡片渲染", qpct && qpct !== "--", "quality=" + qpct);

  // ---------- 2) 第 2 周:点「采集一次」 ----------
  console.log("\n--------------------------------------------------------------");
  console.log("2) 第 2 周任务卡片 —— 点「🎯 采集一次」");
  console.log("--------------------------------------------------------------");
  const sampleBtn = await page.$("#taskSampleBtn");
  check("找到「采集一次」按钮", !!sampleBtn);

  await page.click("#taskSampleBtn");
  // 按钮应先禁用(防重复提交)
  const disabledNow = await page.$eval("#taskSampleBtn", (b) => b.disabled);
  check("点击后按钮置灰(防重复提交)", disabledNow);

  const gotCurrent = await waitFor(page, () => {
    const el = document.getElementById("taskCurrent");
    return el && el.textContent && el.textContent.trim().length > 0;
  }, 8000, "任务状态区出现内容");
  check("任务状态区开始显示", gotCurrent);

  // 轮询到终态,最多 25 秒。
  // 注意:这里**不能**用「耗时」当判据 —— 等待中的文案是"耗时:等待中…",
  // 会瞬间命中、让断言扑空。必须只认终态词。
  const reachedFinal = await waitFor(page, () => {
    const t = (document.getElementById("taskCurrent") || {}).textContent || "";
    return /已完成|已超时|未响应|超时/.test(t);
  }, 25000, "任务到达终态");

  const currentText = await page.$eval("#taskCurrent", (e) => e.textContent.replace(/\s+/g, " ").trim());
  check("任务到达终态(已完成)", reachedFinal && /已完成/.test(currentText),
    currentText.slice(0, 120));

  // 历史列表里应出现本次任务
  const histRows = await page.$$eval("#taskHistoryTable tbody tr", (rs) => rs.length);
  check("最近任务列表有记录", histRows > 0, histRows + " 行");

  // ---------- 3) 第 4 周:自然语言「采集一次」 ----------
  console.log("\n--------------------------------------------------------------");
  console.log("3) 第 4 周自然语言卡片 —— 点示例「🎯 采集一次」");
  console.log("--------------------------------------------------------------");
  await page.click('button[data-nlq="采集一次"]');
  check("点击后出现「查询中」提示", await waitFor(page, () => {
    const el = document.querySelector("#nlqResult .nlq-answer");
    return el && /查询中/.test(el.textContent);
  }, 6000, "查询中提示"));

  const nlqDone = await waitFor(page, () => {
    const el = document.querySelector("#nlqResult .nlq-answer");
    return el && !/查询中/.test(el.textContent) && el.textContent.trim().length > 0;
  }, 25000, "自然语言回答");

  const nlqText = await page.$eval("#nlqResult", (e) => e.textContent.replace(/\s+/g, " ").trim());
  check("自然语言回答出现", nlqDone, nlqText.slice(0, 150));

  // 关键原则:板子在线才允许出现"成功";离线时必须说超时
  if (/成功/.test(nlqText)) {
    check("回答含 request_id(可追溯是哪次采集)", /req-/.test(nlqText));
  } else {
    check("离线时如实报超时(未谎称成功)", /超时|没等到|pending/.test(nlqText), nlqText.slice(0, 100));
  }

  // ---------- 4) 第 4 周:查询类 ----------
  console.log("\n--------------------------------------------------------------");
  console.log("4) 第 4 周 —— 查询类提问");
  console.log("--------------------------------------------------------------");
  // 必须先清空:上一步点过示例按钮,输入框里还留着「采集一次」,
  // 不清空就会拼成「采集一次最近 5 分钟…」→ 又被判成采集意图,
  // 统计查询等于根本没验到。
  await page.$eval("#nlqInput", (el) => { el.value = ""; });
  await page.type("#nlqInput", "最近 5 分钟合加速度的最大值");
  await page.click("#nlqAskBtn");
  const statDone = await waitFor(page, () => {
    const el = document.querySelector("#nlqResult .nlq-answer");
    return el && !/查询中/.test(el.textContent) && el.textContent.trim().length > 0;
  }, 15000, "统计类回答");
  const statText = await page.$eval("#nlqResult", (e) => e.textContent.replace(/\s+/g, " ").trim());
  check("统计类提问有回答", statDone, statText.slice(0, 150));
  check("回答里出现数值", /\d/.test(statText));
  // 必须是"查询"意图(不是又跑到采集通道去了),并且给出的是统计量而非三轴采样值
  check("意图判定为统计查询(非采集)", /查统计|统计/.test(statText), statText.slice(0, 90));
  check("答案给的是聚合值(最大值)", /最大值|最大/.test(statText), statText.slice(0, 90));

  // 历史记录
  const histItems = await page.$$eval("#nlqHistory > div", (rs) => rs.length);
  check("「最近提问」保留了问答", histItems > 0, histItems + " 条");

  // ---------- 5) 前端报错 ----------
  console.log("\n--------------------------------------------------------------");
  console.log("5) 前端运行时报错(CLI 验证抓不到的一类)");
  console.log("--------------------------------------------------------------");
  check("无 JS 报错 / 本站资源加载失败", jsErrors.length === 0,
    jsErrors.length ? jsErrors.slice(0, 5).join(" | ") : "");

  // ---------- 截图 ----------
  if (WANT_SHOTS) {
    if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
    const full = path.join(SHOT_DIR, "page-full.png");
    await page.screenshot({ path: full, fullPage: true });
    console.log("\n截图已保存: " + full);
    // 再截一张第 4 周卡片特写
    const card = await page.$("#nlqCard") || await page.$(".nlq-result");
    if (card) {
      const c = path.join(SHOT_DIR, "nlq-card.png");
      await card.screenshot({ path: c });
      console.log("截图已保存: " + c);
    }
  }

  await browser.close();

  const pass = results.filter((r) => r.ok).length;
  const fail = results.length - pass;
  console.log("\n==============================================================");
  console.log(`  UI 冒烟结果:${pass} 通过 / ${fail} 失败`);
  console.log("==============================================================");
  if (jsErrors.length) {
    console.log("\n捕获到的前端报错:");
    jsErrors.slice(0, 10).forEach((e) => console.log("  - " + e));
  }
  process.exit(fail ? 1 : 0);
})().catch((e) => {
  console.error("脚本异常:", e && e.message ? e.message : e);
  process.exit(2);
});
