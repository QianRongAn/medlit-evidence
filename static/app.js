const GRADE_ZH = {
  High: "高", Moderate: "中", Low: "低", "Very low": "极低", "N/A": "未分级",
};
// 沉静的分级配色；类别含义同时用文字表达
const GRADE_COLOR = {
  High: "#377F78", Moderate: "#4665B8", Low: "#80652C",
  "Very low": "#A26761", "N/A": "#65758C",
};

// 根据背景亮度自动选深/浅文字，避免亮黄底配白字看不清
function contrastText(hex) {
  const m = String(hex || "").replace("#", "");
  if (m.length < 6) return "#fff";
  const r = parseInt(m.substr(0, 2), 16);
  const g = parseInt(m.substr(2, 2), 16);
  const b = parseInt(m.substr(4, 2), 16);
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return lum > 0.6 ? "#1f2430" : "#fff";
}
const STYPE_ZH = {
  meta_analysis: "Meta 分析",
  systematic_review: "系统综述",
  guideline: "指南 / 共识",
  randomized_controlled_trial: "随机对照试验",
  clinical_trial: "临床试验",
  cohort: "队列研究",
  case_control: "病例对照",
  case_report: "病例报告",
  review: "综述",
  basic: "基础研究",
  other: "其他",
  notice: "学术通知",
};
const GRADE_ORDER = ["High", "Moderate", "Low", "Very low", "N/A"];

const $ = (id) => document.getElementById(id);

function setStatus(online) {
  const s = $("status");
  s.classList.remove("online", "offline");
  if (online === null) {
    $("statusText").textContent = "连接中…";
  } else if (online) {
    s.classList.add("online");
    $("statusText").textContent = "PubMed 在线";
  } else {
    s.classList.add("offline");
    $("statusText").textContent = "离线模式";
  }
}

async function checkHealth() {
  try {
    const r = await fetch("/health");
    const d = await r.json();
    setStatus(!!d.pubmed_online);
    renderHomeStatus(d);
  } catch {
    setStatus(false);
    renderHomeStatus(null);
  }
}

function esc(s) {
  return (s || "").replace(/[&<>"]/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
  }[c]));
}

const POLARITY = {
  unassessed: { label: "未评估", color: "#8f8f88" },
};

function motionBehavior() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ? "auto" : "smooth";
}

function signalAction(kind, element) {
  if (typeof CustomEvent === "function") {
    document.dispatchEvent(new CustomEvent("medlit:action", { detail: { kind, element } }));
  }
}

function focusSource(pmid) {
  const target = $(pmid ? "source-" + pmid : "sourcePanel");
  if (!target) return;
  if (target.classList.contains("hidden")) {
    $("sourceFilter").value = "";
    sourceCategory = "all";
    document.querySelectorAll("[data-source-type]").forEach(button => {
      button.classList.toggle("selected", button.dataset.sourceType === "all");
      button.ariaPressed = String(button.dataset.sourceType === "all");
    });
    filterSources();
  }
  target.scrollIntoView({ behavior: motionBehavior(), block: "center" });
  target.focus({ preventScroll: true });
  signalAction("source", target);
  target.classList.add("source-highlight");
  setTimeout(() => target.classList.remove("source-highlight"), 2400);
}

function toggleReadingMode() {
  const enabled = !$("result").classList.contains("reading-mode");
  $("result").classList.toggle("reading-mode", enabled);
  $("readingMode").ariaPressed = String(enabled);
  $("readingMode").textContent = enabled ? "退出舒适阅读" : "舒适阅读";
}

function renderAnswer(data) {
  const body = $("answerBody");
  body.innerHTML = "";
  $("answerNotice").textContent = data.mode === "llm"
    ? "引用来源与对应原句已校验；生成摘要的语义是否受原文支持仍需核对。"
    : data.llm_fallback_reason === "citation_validation_failed"
      ? "生成结果未通过引用校验，已改用摘要摘录。"
      : data.llm_fallback_reason === "llm_unavailable" ? "生成服务不可用，已改用摘要摘录。" : "";
  if (data.sentences && data.sentences.length) {
    data.sentences.forEach((s) => {
      const p = document.createElement("p");
      p.className = "answer-sentence";
      const pol = POLARITY.unassessed;
      const mark = document.createElement("span");
      mark.className = "pol-mark";
      mark.style.color = pol.color;
      mark.title = "结论方向：" + pol.label;
      p.appendChild(mark);
      p.appendChild(document.createTextNode(s.sentence + " "));
      const cite = document.createElement("a");
      cite.className = "cite";
      cite.textContent = "PMID " + s.pmid;
      if (s.pmid) {
        cite.href = "https://pubmed.ncbi.nlm.nih.gov/" + s.pmid + "/";
        cite.target = "_blank";
        cite.rel = "noopener";
      }
      p.appendChild(cite);
      if (/^[1-9][0-9]*$/.test(String(s.pmid || ""))) {
        const locate = document.createElement("button");
        locate.className = "locate-source";
        locate.textContent = "定位文献 ↘";
        locate.title = "定位本页文献 PMID " + s.pmid;
        locate.addEventListener("click", () => focusSource(s.pmid));
        p.appendChild(locate);
      }
      body.appendChild(p);
      if (data.mode === "llm" && s.quote) {
        const quote = document.createElement("blockquote");
        quote.className = "source-quote";
        quote.textContent = "对应摘要原句：" + s.quote;
        body.appendChild(quote);
      }
    });
  } else {
    const p = document.createElement("p");
    p.textContent = data.answer || "未能生成回答，请换一种问法。";
    body.appendChild(p);
  }
  $("modeBadge").textContent =
    data.mode === "llm" ? "LLM 摘要整理（待核对）" : `摘要摘录（${data.online ? "PubMed" : "演示语料"}）`;
}

function renderStats(data, elapsedMs, ev) {
  // 未经验证的方向与置信度不显示为数字或无冲突。
  $("confidenceNum").textContent = "–";

  // 未验证的证据方向保持待核对状态。
  // 保留原有判定文字，不通过主题色暗示支持或反对。
  $("verdictText").textContent = ev ? ev.verdict.replace(/^证据/, "") : "待核对";
  const verdictCard = $("statVerdict");
  verdictCard.classList.remove("tone-cream", "tone-pink", "tone-salmon", "tone-mint");
  verdictCard.classList.add("tone-mint");
  $("verdictSub").textContent = "尚未验证，暂不评分";
  $("assessmentNote").textContent = ev ? ev.assessment_note : "证据方向尚未评估";
  $("polarityLine").textContent = ev
    ? `方向未评估 ${ev.unassessed_count || 0} 篇`
    : "";

  // 卡 3：文献命中
  $("hitNum").textContent = data.total.toLocaleString();
  $("hitSub").textContent = `筛选纳入 ${data.results.length} 篇 · ${data.online ? "PubMed 在线" : "离线语料"}`;

  // 卡 4：响应耗时
  const sec = elapsedMs / 1000;
  $("timeNum").textContent = sec >= 1 ? sec.toFixed(1) + "s" : Math.round(elapsedMs) + "ms";
  $("timeSub").textContent = data.mode === "llm" ? "生成式回答" : "抽取式回答";

  const screening = data.screening;
  $("retrievalSummary").textContent = screening
    ? `PubMed ${data.online ? "命中" : "离线候选"} ${data.total.toLocaleString()} 篇 · 已检查 ${screening.candidate_count} 篇 · 通过 ${screening.matched_count} 篇 · 展示 ${data.results.length} 篇`
    : `纳入 ${data.results.length} 篇 · 检索命中 ${data.total.toLocaleString()} 篇`;
  $("requestSummary").textContent = `${data.screening?.next_cursor ? "首批耗时" : "响应耗时"} ${$("timeNum").textContent} · ${data.mode === "llm" ? "LLM 摘要整理" : "摘要摘录"}`;
  $("resultMeta").textContent = `「${data.query}」`;

  // 完整性告警（撤稿 / 存疑 / 更正）
  const warn = $("integrityWarning");
  if (ev && ev.integrity_warning) {
    warn.textContent = "注意：" + ev.integrity_warning;
    warn.classList.remove("hidden");
  } else {
    warn.classList.add("hidden");
  }

  renderConfidence();
}

/* ---------- 首页仪表盘 ---------- */
const ASKCOUNT_KEY = "medlit.askCount";

function getAskCount() {
  return Number(localStorage.getItem(ASKCOUNT_KEY) || 0);
}

/* 由 /health 数据填充首页四张状态卡 */
function renderHomeStatus(h) {
  const online = !!(h && h.pubmed_online);
  const svc = $("homeSvc");
  svc.textContent = online ? "在线" : "离线";
  svc.style.color = online ? "#287567" : "#95631b";
  $("homeSvcSub").textContent = online
    ? "PubMed E-utilities 实时检索已连通"
    : "联网失败 · 自动回退内置示例语料";

  const loaded = !!(h && h.model_loaded);
  const model = $("homeModel");
  model.textContent = loaded ? "已加载" : "未加载";
  model.style.color = loaded ? "#273449" : "#95631b";
  $("homeModelSub").textContent = loaded
    ? "研究模型分数 · 未校准"
    : "模型不可用 · 分数未显示";

  $("homeHist").textContent = getAskCount();

  const lib = $("homeLib");
  if (online) {
    lib.textContent = "已连接";
    $("homeLibSub").textContent = "PubMed · 按问题实时检索";
  } else {
    lib.textContent = h && Number.isInteger(h.corpus_size) ? h.corpus_size : "–";
    $("homeLibSub").textContent = "离线语料篇数 · 断网可用";
  }
}

/* 使用统计（累计次数独立计数，不受历史 20 条上限影响） */
function renderUsage() {
  const h = getHistory();
  $("usageTotal").textContent = getAskCount();
  if (h.length) {
    const avgMs = h.reduce((a, b) => a + (b.elapsedMs || 0), 0) / h.length;
    $("usageAvg").textContent = avgMs >= 1000 ? (avgMs / 1000).toFixed(1) + "s" : Math.round(avgMs) + "ms";
    const confs = h.map((x) => Number(x.confidence)).filter((n) => !isNaN(n) && n > 0);
    $("usageConf").textContent = confs.length ? Math.round(confs.reduce((a, b) => a + b, 0) / confs.length) : "–";
    const cf = h.filter((x) => x.conflict).length;
    $("usageConflict").textContent = cf ? cf + " 次" : "未评估";
  } else {
    $("usageAvg").textContent = "–";
    $("usageConf").textContent = "–";
    $("usageConflict").textContent = "–";
  }
}

function renderHome() {
  renderUsage();
}

/* 首页仪表盘与结果区互斥显示 */
function syncHome() {
  const busy = !$("loading").classList.contains("hidden");
  const hasResult = !$("result").classList.contains("hidden");
  $("homeDash").classList.toggle("hidden", busy || hasResult);
  $("workspaceIntro").classList.toggle("hidden", busy || hasResult);
  document.body?.classList.toggle("research-active", busy || hasResult);
  $("overviewNav").classList.toggle("selected", !busy && !hasResult);
  $("searchNav").classList.toggle("selected", busy || hasResult);
  $("overviewNav").ariaCurrent = !busy && !hasResult ? "page" : "false";
  $("searchNav").ariaCurrent = busy || hasResult ? "page" : "false";
}

function showDashboard() {
  cancelSourcePages();
  if (typeof resetGradeReview === "function") resetGradeReview();
  cancelSearch();
  $("result").classList.add("hidden");
  $("error").classList.add("hidden");
  $("loading").classList.add("hidden");
  syncHome();
  window.scrollTo({ top: 0, behavior: motionBehavior() });
}
function renderPico(pico) {
  pico = pico || {};
  const set = (id, arr) => {
    $(id).textContent = arr && arr.length ? arr.join(" · ") : "原问题未指定";
  };
  set("picoP", pico.population);
  set("picoI", pico.intervention);
  set("picoC", pico.comparison);
  set("picoO", pico.outcome);
  if (!picoEdited) Object.entries(PICO_INPUTS).forEach(([field,id]) => {
    $(id).value = (pico[field] || []).join("、");
  });
  const fields = { population: "人群", intervention: "干预", comparison: "对照", outcome: "结局" };
  const identified = Object.keys(fields).filter(key => pico[key]?.length).map(key => fields[key]);
  const missing = Object.keys(fields).filter(key => !pico[key]?.length).map(key => fields[key]);
  $("picoSummary").textContent = (identified.length ? "已识别：" + identified.join("、") + "。" : "尚未识别研究条件，可直接补充 PICO。")
    + (missing.length ? "原问题未指定：" + missing.join("、") + "，可补充条件后重新检索。" : "") + "词项覆盖不等于临床适用性。";
}

function renderScreening(data) {
  const screening = data.screening;
  const excluded = data.excluded_results || [];
  const note = $("screeningNote");
  if (!screening) {
    note.textContent = "";
  } else {
    const issues = {
      unmapped_chinese_terms: "有未映射的中文词项",
      ambiguous_alternatives: "尚不能解析或者条件",
      unsupported_numeric_constraint: "尚不能解析数字条件",
      negated_population_query: "尚不能解析排除人群条件",
      unparsed_exclusion: "尚不能解析排除条件",
      no_content_terms: "缺少可检索的医学词项",
    };
    const detail = (screening.issues || []).map((key) => issues[key] || "查询条件待明确").join("；");
    note.textContent = `候选 ${screening.candidate_count} 篇，词项筛选命中 ${screening.matched_count} 篇，展示 ${screening.included_count} 篇，未纳入 ${screening.excluded_count} 篇。`
      + (screening.not_displayed_count ? `另有 ${screening.not_displayed_count} 篇通过筛选，受展示上限限制未显示。` : "")
      + (screening.search_exhausted === false ? "尚未检查全部 PubMed 命中。" : "")
      + (detail ? detail + "。" : "")
      + (screening.unmapped_terms && screening.unmapped_terms.length ? "未映射：" + screening.unmapped_terms.join("、") + "。" : "")
      + (screening.note || "");
  }
  $("excludedSources").classList.toggle("hidden", excluded.length === 0);
  $("excludedCount").textContent = `未纳入的候选 · ${excluded.length} 篇`;
  const list = $("excludedList");
  list.innerHTML = "";
  const reasons = {
    missing_population: "人群词项未覆盖", missing_intervention: "干预词项未覆盖",
    missing_comparison: "对照词项未覆盖", missing_outcome: "摘要中未覆盖所问结局",
    insufficient_lexical_coverage: "其他查询词覆盖不足", missing_abstract: "缺少摘要",
    unsupported_query: "查询条件尚未完整解析",
  };
  excluded.forEach((d) => {
    const item = document.createElement("div");
    item.className = "doc-item";
    const why = ((d.screening && d.screening.reasons) || []).map((key) => reasons[key] || key).join("；");
    const pmid = String(d.pmid || "");
    const title = /^[1-9][0-9]{0,9}$/.test(pmid)
      ? `<a href="https://pubmed.ncbi.nlm.nih.gov/${pmid}/" target="_blank" rel="noopener">${esc(d.title || "无标题")}</a>`
      : esc(d.title || "无标题");
    item.innerHTML = `<p class="doc-title">${title}</p><div>${integrityBadges(d)}</div><p class="doc-meta">未纳入原因：${esc(why)}</p><div>${integrityLinks(d)}</div>`;
    list.appendChild(item);
  });
}

/* 未完成语义对齐与独立验证前，不渲染旧版置信度。 */
function renderConfidence() {
  const tag = $("confTag");
  const score = $("confScore");
  const desc = $("confDesc");
  tag.textContent = "未评估";
  tag.style.color = "#5F6E83";
  score.textContent = "–";
  score.style.color = "#4665b8";
  desc.textContent = "研究类型不等于结论可信度";
}

function sourceType(doc) {
  if (doc.study_type === "randomized_controlled_trial") return "trial";
  if (["systematic_review", "meta_analysis"].includes(doc.study_type)) return "synthesis";
  return "other";
}

function renderDist(results) {
  const groups = [
    { key: "trial", label: "随机试验", color: "#D9D6F7" },
    { key: "synthesis", label: "系统综述 / Meta 分析", color: "#CFECFA" },
    { key: "other", label: "其他", color: "#E0F5CD" },
  ];
  const bar = $("distBar"), legend = $("distLegend");
  bar.innerHTML = "";
  legend.innerHTML = "";
  $("distTotal").textContent = `（纳入 ${results.length} 篇）`;
  groups.forEach(group => {
    const count = results.filter(doc => sourceType(doc) === group.key).length;
    if (count) {
      const segment = document.createElement("div");
      segment.className = "dist-seg";
      segment.style.width = count / results.length * 100 + "%";
      segment.style.background = group.color;
      segment.title = `${group.label}：${count} 篇`;
      bar.appendChild(segment);
    }
    const item = document.createElement("span");
    item.innerHTML = `<i class="swatch" style="background:${group.color}"></i>${group.label} ${count}`;
    legend.appendChild(item);
  });
  if (!results.length) legend.textContent = "暂无纳入文献";
}

function modelScoreBadge(score) {
  // 旧版概率载荷也不展示，避免把 0–1 误当作新版 0–100 分数。
  if (!score || score.kind !== "research_model_score" || score.calibrated !== false
      || !Array.isArray(score.scale) || score.scale[0] !== 0 || score.scale[1] !== 100
      || typeof score.score !== "number" || !Number.isFinite(score.score)
      || score.score < 0 || score.score > 100) return "";
  return `<span class="risk-badge" style="background:#eff2e9;color:#506346" title="仅供人工排序；未校准，不代表未来撤稿概率">研究分数 ${score.score.toFixed(1)} / 100</span>`;
}

function integrityBadges(doc) {
  const labels = { retracted: "已撤稿", concern: "存疑", corrected: "有更正/重发", notice: "学术通知" };
  const flags = new Set(doc.integrity_flags || []);
  if (doc.integrity && doc.integrity !== "ok") flags.add(doc.integrity);
  if (doc.is_notice) flags.add("notice");
  return Object.keys(labels).filter((key) => flags.has(key)).map((key) =>
    `<span class="integrity-badge integrity-${key}">${labels[key]}</span>`
  ).join("");
}

function integrityLinks(doc) {
  const labels = {
    RetractionIn: "撤稿通知", RetractionOf: "所涉原文",
    ExpressionOfConcernIn: "存疑通知", ExpressionOfConcernFor: "所涉原文",
    ErratumIn: "更正通知", ErratumFor: "所涉原文",
    CorrectedandRepublishedIn: "更正重发版", CorrectedandRepublishedFrom: "更正前版本",
    RetractedandRepublishedIn: "重发版", RetractedandRepublishedFrom: "已撤稿原版",
  };
  return (doc.integrity_relations || []).filter((r) => labels[r.ref_type]).map((r) => {
    const label = labels[r.ref_type];
    const pmid = String(r.pmid || "");
    return /^[1-9][0-9]{0,9}$/.test(pmid)
      ? `<a class="doc-pmid" href="https://pubmed.ncbi.nlm.nih.gov/${pmid}/" target="_blank" rel="noopener">${label} · PMID ${pmid}</a>`
      : `<span class="doc-meta">${label}：${esc(r.citation || "未提供关联 PMID")}</span>`;
  }).join(" · ");
}

let sourceCategory = "all";

function filterSources() {
  const query = ($("sourceFilter").value || "").trim().toLocaleLowerCase();
  const cards = Array.from($("docList").children);
  let visible = 0;
  cards.forEach(card => {
    const match = (!query || (card.dataset.search || "").includes(query))
      && (sourceCategory === "all" || card.dataset.category === sourceCategory);
    card.classList.toggle("hidden", !match);
    if (match) visible++;
  });
  $("sourceVisible").textContent = query || sourceCategory !== "all" ? `当前显示 ${visible} / ${cards.length} 篇文献` : "";
  $("sourceEmpty").textContent = cards.length ? "已加载文献中没有匹配项。可继续加载，或尝试其他类型和关键词。" : "本次没有通过筛选的文献。请检查 PICO 条件或调整问题。";
  $("sourceEmpty").classList.toggle("hidden", visible > 0);
}

function renderDocs(results) {
  const list = $("docList");
  sourceCategory = "all";
  document.querySelectorAll("[data-source-type]").forEach(button => {
    button.classList.toggle("selected", button.dataset.sourceType === "all");
    button.ariaPressed = String(button.dataset.sourceType === "all");
  });
  list.innerHTML = "";
  $("docCount").textContent = `${results.length} 篇文献`;
  $("sourceFilter").value = "";
  $("sourceVisible").textContent = "";
  $("sourceEmpty").textContent = "本次没有通过筛选的文献。请检查 PICO 条件或调整问题。";
  $("sourceEmpty").classList.toggle("hidden", results.length > 0);
  results.forEach((d, index) => {
    const div = document.createElement("div");
    div.className = "doc-item";
    div.dataset.category = sourceType(d);
    div.dataset.search = [d.title, d.abstract, d.journal, d.year, d.pmid, ...(d.authors || [])].filter(Boolean).join(" ").toLocaleLowerCase();
    if (/^[1-9][0-9]*$/.test(String(d.pmid || ""))) div.id = "source-" + d.pmid;
    div.tabIndex = -1;
    div.style.setProperty?.("--entry-delay", Math.min(index, 5) * 45 + "ms");

    const grade = GRADE_ZH[d.grade] || "未分级";
    const color = GRADE_COLOR[d.grade] || "#C3C2BC";

    const authors = (d.authors || []).slice(0, 2).join(", ");
    const metaParts = [
      d.journal, d.year,
      `${STYPE_ZH[d.study_type] || "其他"} · 证据 ${grade}`,
      authors,
    ].filter(Boolean).join(" · ");

    const integBadge = integrityBadges(d);

    const riskBadge = modelScoreBadge(d.risk);

    const pmidUrl = d.pmid ? `https://pubmed.ncbi.nlm.nih.gov/${d.pmid}/` : "";
    div.innerHTML = `
      <div class="doc-topline"><span>${String(index + 1).padStart(2, "0")}</span><span>${esc(STYPE_ZH[d.study_type] || "其他研究")} · ${esc(String(d.year || "年份未注明"))}</span></div>
      <p class="doc-title"><a href="${pmidUrl || "#"}" target="_blank" rel="noopener">${esc(d.title)}</a></p>
      <div class="doc-meta">
        <span class="badge" style="background:${color};color:${contrastText(color)}">${grade}</span>
        ${integBadge}
        ${riskBadge}
      </div>
      <div class="doc-meta">${esc(metaParts)}</div>
      ${d.abstract ? `<div class="abstract-block"><div class="doc-abstract abstract-preview" aria-hidden="true">${esc(d.abstract)}</div><details class="abstract-details"><summary><span class="when-closed">阅读完整摘要</span><span class="when-open">收起摘要</span><span class="abstract-plus" aria-hidden="true">+</span></summary><div class="doc-abstract abstract-full">${esc(d.abstract)}</div></details></div>` : ""}
      ${d.pmid ? `<a class="doc-pmid" href="${pmidUrl}" target="_blank" rel="noopener">PMID ${esc(d.pmid)}</a>` : ""}
      <div>${integrityLinks(d)}</div>
      <div class="doc-meta">查询词项覆盖 ${Number(d.relevance || 0).toFixed(1)}% · 不代表临床适用性</div>
      <div class="rel-bar"><div class="rel-fill" style="width:${Math.max(2, d.relevance || 0)}%"></div></div>
    `;
    list.appendChild(div);
  });
}

const PICO_INPUTS = {population:"editPicoP", intervention:"editPicoI", comparison:"editPicoC", outcome:"editPicoO"};
let picoEdited = false;
let picoForQuery = "";
function clearPicoInputs(query = "") {
  picoEdited = false;
  picoForQuery = query;
  Object.values(PICO_INPUTS).forEach(id => { $(id).value = ""; });
}
function picoPayload(query) {
  if (!picoEdited || picoForQuery !== query) return null;
  return Object.fromEntries(Object.entries(PICO_INPUTS).map(([field,id]) => [field, ($(id).value || "").trim()]));
}
let resultData = null;
let pageRequest = null;
let resultPico = null;
function cancelSourcePages() {
  pageRequest?.abort();
  pageRequest = null;
  resultData = null;
}
function renderPageProgress() {
  const screening = resultData?.screening;
  const more = !!screening?.next_cursor;
  $("loadMoreSources").classList.toggle("hidden", !more);
  $("pageProgress").textContent = !screening ? "" : `已检查 ${screening.candidate_count} 篇，已展示 ${resultData.results.length} 篇匹配文献。`
    + (more ? "滚动到底部继续加载，总展示数量不设上限。" : "本次可获取的候选已检查完毕。");
  $("pageError").textContent = "";
}
function mergeSourcePage(previous, next) {
  const unique = values => [...new Map(values.map(doc => [String(doc.pmid), doc])).values()];
  const results = unique([...(previous.results || []), ...(next.results || [])]);
  const excluded = unique([...(previous.excluded_results || []), ...(next.excluded_results || [])]);
  const counts={retracted:0,concern:0,corrected:0,notice:0};
  results.forEach(doc=>{
    const flags=new Set(doc.integrity_flags || []);
    if(doc.integrity && doc.integrity!=="ok")flags.add(doc.integrity);
    if(doc.is_notice)flags.add("notice");
    Object.keys(counts).forEach(key=>{if(flags.has(key))counts[key]++;});
  });
  const labels={retracted:"已撤稿，不用于回答",concern:"存疑",corrected:"有更正或重发关联",notice:"学术通知，不用于回答"};
  const warning=Object.entries(counts).filter(([,count])=>count).map(([key,count])=>`${count} 篇${labels[key]}`).join("；");
  return {...previous, results, excluded_results:excluded, screening:{...next.screening,
    candidate_count:(previous.screening?.candidate_count || 0)+(next.screening?.candidate_count || 0),
    matched_count:results.length,included_count:results.length,excluded_count:excluded.length},
    evidence: {...previous.evidence, integrity_warning:warning || null, ...Object.fromEntries(Object.entries(counts).map(([key,count])=>[key==="notice"?"notice_count":key+"_count",count])), conclusions:[...(previous.evidence?.conclusions || []), ...(next.evidence?.conclusions || [])]}};
}
async function loadMoreSources() {
  const current = resultData;
  const cursor = current?.screening?.next_cursor;
  if (!cursor || pageRequest) return;
  const controller = new AbortController();
  pageRequest = controller;
  $("loadMoreSources").disabled = true;
  $("loadMoreSources").textContent = "正在加载下一批…";
  let succeeded = false;
  try {
    const response = await fetch("/api/answer", {method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({query:current.query,retmax:settings.retmax,cursor,...(resultPico ? {pico:resultPico} : {})}), signal:controller.signal});
    const next = await response.json();
    if (!response.ok) throw new Error(next.detail || "加载失败，请重试。");
    if (resultData !== current || controller.signal.aborted) return;
    resultData = mergeSourcePage(current,next);
    const category=sourceCategory, filter=$("sourceFilter").value;
    renderDocs(resultData.results);
    sourceCategory=category; $("sourceFilter").value=filter;
    document.querySelectorAll("[data-source-type]").forEach(button=>{
      button.classList.toggle("selected",button.dataset.sourceType===category);
      button.ariaPressed=String(button.dataset.sourceType===category);
    });
    filterSources();renderDist(resultData.results);renderScreening(resultData);renderPageProgress();
    $("retrievalSummary").textContent=`PubMed 命中 ${current.total.toLocaleString()} 篇 · 已检查 ${resultData.screening.candidate_count} 篇 · 展示 ${resultData.results.length} 篇`;
    $("integrityWarning").textContent=resultData.evidence.integrity_warning || "";
    $("integrityWarning").classList.toggle("hidden",!resultData.evidence.integrity_warning);
    if ($("gradeReviewResult").textContent) $("gradeReviewResult").textContent="文献已增加，请复核并重新提交可信度评估草案。";
    if (typeof renderReportedAssessment === "function") renderReportedAssessment(resultData.results);
    succeeded = true;
  } catch(error) {
    if (!controller.signal.aborted && resultData===current) $("pageError").textContent=error.message;
  } finally {
    if (pageRequest===controller) {
      pageRequest=null; $("loadMoreSources").disabled=false; $("loadMoreSources").textContent="继续加载文献";
      if (succeeded && resultData?.screening?.next_cursor && $("loadMoreSources").getBoundingClientRect?.().top < window.innerHeight)
        setTimeout(loadMoreSources,500);
    }
  }
}
let activeRequest = null;
let loadingTimer = null;

function setSearchBusy(busy) {
  $("askBtn").disabled = busy;
  $("askBtn").classList.toggle("is-loading", busy);
  $("askLabel").textContent = busy ? "检索中…" : "检索证据";
  $("searchComposer").ariaBusy = String(busy);
}

function cancelSearch() {
  if (!activeRequest) return;
  const request = activeRequest;
  activeRequest = null;
  request.abort();
  clearInterval(loadingTimer);
  loadingTimer = null;
  $("loading").classList.add("hidden");
  setSearchBusy(false);
  syncHome();
}

async function ask(query) {
  if (!query.trim() || activeRequest) return;
  cancelSourcePages();
  if (typeof resetGradeReview === "function") resetGradeReview();
  const pico = picoPayload(query);
  if (picoForQuery !== query) clearPicoInputs(query);
  const controller = new AbortController();
  activeRequest = controller;
  $("query").value = query;
  $("topQuery").value = query;
  setSearchBusy(true);
  $("result").classList.add("hidden");
  $("error").classList.add("hidden");
  $("loading").classList.remove("hidden");
  syncHome();
  window.scrollTo({ top: 0, behavior: motionBehavior() });
  const started = performance.now();
  $("loadingElapsed").textContent = "0s";
  loadingTimer = setInterval(() => {
    $("loadingElapsed").textContent = Math.floor((performance.now() - started) / 1000) + "s";
  }, 1000);

  try {
    const r = await fetch("/api/answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, retmax: settings.retmax, ...(pico ? {pico} : {}) }),
      signal: controller.signal,
    });
    if (!r.ok) {
      const e = await r.json().catch(() => ({}));
      throw new Error(e.detail || `请求失败（${r.status}）`);
    }
    const data = await r.json();
    if (activeRequest !== controller) return;
    const elapsed = performance.now() - started;
    setStatus(data.online);
    renderStats(data, elapsed, data.evidence);
    renderPico(data.pico);
    renderScreening(data);
    renderAnswer(data);
    renderDist(data.results || []);
    renderDocs(data.results || []);
    resultData = data;
    resultPico = pico;
    renderPageProgress();
    if (typeof renderReportedAssessment === "function") renderReportedAssessment(data.results || []);
    recordHistory(query, data.evidence, elapsed);
    $("loading").classList.add("hidden");
    $("result").classList.remove("hidden");
    syncHome();
  } catch (err) {
    if (activeRequest !== controller || controller.signal.aborted) return;
    $("loading").classList.add("hidden");
    $("error").textContent = "出错了：" + err.message;
    $("error").classList.remove("hidden");
    syncHome();
  } finally {
    if (activeRequest === controller) {
      clearInterval(loadingTimer);
      loadingTimer = null;
      activeRequest = null;
      setSearchBusy(false);
    }
  }
}

$("askBtn").addEventListener("click", () => ask($("query").value));
$("query").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) ask($("query").value);
});
document.querySelectorAll(".chip").forEach((c) =>
  c.addEventListener("click", () => ask(c.dataset.q))
);

/* ---------- 设置 ---------- */
const SETTINGS_KEY = "medlit.settings";
const defaultSettings = { retmax: 20, showAbstract: true };

function loadSettings() {
  try {
    const s = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}");
    return {retmax:[20,40,100].includes(s.retmax) ? s.retmax : 20, showAbstract:typeof s.showAbstract === "boolean" ? s.showAbstract : true};
  } catch {
    return { ...defaultSettings };
  }
}

function saveSettings() {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

const settings = loadSettings();

function applySettingsUI() {
  document.querySelectorAll("#retmaxSeg button").forEach((b) =>
    b.classList.toggle("active", Number(b.dataset.v) === settings.retmax)
  );
  $("showAbstract").checked = settings.showAbstract;
  $("docList").classList.toggle("hide-abstract", !settings.showAbstract);
}

document.querySelectorAll("#retmaxSeg button").forEach((b) =>
  b.addEventListener("click", () => {
    settings.retmax = Number(b.dataset.v);
    saveSettings();
    applySettingsUI();
  })
);
$("showAbstract").addEventListener("change", (e) => {
  settings.showAbstract = e.target.checked;
  saveSettings();
  applySettingsUI();
});

/* ---------- 通知 / 历史记录 ---------- */
const HISTORY_KEY = "medlit.history";

function getHistory() {
  try {
    const history = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    if (!Array.isArray(history)) return [];
    return history.filter((it) => it && typeof it === "object").map((it) => ({
      ...it,
      verdict: it.assessment_version === "2" ? it.verdict : "旧版判定已停用",
      confidence: null,
      conflict: null,
    }));
  } catch {
    return [];
  }
}

function recordHistory(query, ev, elapsedMs) {
  const h = getHistory();
  h.unshift({
    query,
    verdict: ev ? ev.verdict : "–",
    assessment_version: ev ? ev.assessment_version : null,
    confidence: null,
    conflict: null,
    time: Date.now(),
    elapsedMs: Math.round(elapsedMs),
  });
  localStorage.setItem(HISTORY_KEY, JSON.stringify(h.slice(0, 20)));
  localStorage.setItem(ASKCOUNT_KEY, String(getAskCount() + 1));
  renderHome();
}

function renderHistory() {
  const list = $("notifList");
  list.innerHTML = "";
  const h = getHistory();
  if (!h.length) {
    list.innerHTML = '<p class="notif-empty">暂无问答记录</p>';
    return;
  }
  h.forEach((it) => {
    const div = document.createElement("div");
    div.className = "notif-item";
    const color = it.conflict ? "#f5a800" : (it.verdict === "证据倾向支持" ? "#12b76a" : "#8f8f88");
    const t = new Date(it.time);
    const hh = String(t.getHours()).padStart(2, "0");
    const mm = String(t.getMinutes()).padStart(2, "0");
    div.innerHTML = `
      <p class="notif-query">${esc(it.query)}</p>
      <div class="notif-meta">
        <span class="notif-verdict" style="color:${color}">${esc(it.verdict)}</span>
        <span>置信度未评估</span>
        <span>${it.elapsedMs}ms</span>
        <span>${hh}:${mm}</span>
      </div>
    `;
    list.appendChild(div);
  });
  const clear = document.createElement("button");
  clear.className = "notif-clear";
  clear.textContent = "清空记录";
  clear.addEventListener("click", () => {
    localStorage.removeItem(HISTORY_KEY);
      renderHistory();
    renderHome();
  });
  list.appendChild(clear);
}

/* ---------- 抽屉开合 ---------- */
let activeDrawer = null;
let drawerOpener = null;
function openDrawer(name) {
  if (activeDrawer && activeDrawer !== name) closeDrawer(activeDrawer);
  drawerOpener = document.activeElement;
  activeDrawer = name;
  const isSettings = name === "settings";
  const drawer = $(isSettings ? "settingsDrawer" : "notifDrawer");
  const mask = document.querySelector(`.drawer-mask[data-close="${name}"]`);
  drawer.classList.remove("hidden");
  mask.classList.remove("hidden");
  if (!isSettings) renderHistory();
  document.querySelectorAll(".topbar, .nav-rail, main").forEach((el) => { el.inert = true; });
  document.body.classList.add("drawer-open");
  drawer.focus();
  signalAction("drawer", drawer);
}
function closeDrawer(name) {
  const isSettings = name === "settings";
  $(isSettings ? "settingsDrawer" : "notifDrawer").classList.add("hidden");
  document.querySelector(`.drawer-mask[data-close="${name}"]`).classList.add("hidden");
  if (activeDrawer === name) {
    activeDrawer = null;
    document.querySelectorAll(".topbar, .nav-rail, main").forEach((el) => { el.inert = false; });
    document.body.classList.remove("drawer-open");
    if (drawerOpener) drawerOpener.focus();
    drawerOpener = null;
  }
}

document.querySelectorAll(".drawer-close, .drawer-mask").forEach((el) =>
  el.addEventListener("click", () => closeDrawer(el.dataset.close))
);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    ["settings", "notif"].forEach(closeDrawer);
  }
  if (e.key === "Tab" && activeDrawer) {
    const drawer = $(activeDrawer === "settings" ? "settingsDrawer" : "notifDrawer");
    const controls = [...drawer.querySelectorAll('button, input, a[href], [tabindex="0"]')].filter((el) => !el.disabled);
    if (!controls.length) { e.preventDefault(); drawer.focus();
  signalAction("drawer", drawer); return; }
    const first = controls[0], last = controls[controls.length - 1];
    if (!controls.includes(document.activeElement) || (!e.shiftKey && document.activeElement === last)) {
      e.preventDefault(); (e.shiftKey ? last : first).focus();
    } else if (e.shiftKey && document.activeElement === first) {
      e.preventDefault(); last.focus();
    }
  }
});

/* ---------- 顶栏 ---------- */
$("navHome").addEventListener("click", () => {
  showDashboard();
  $("query").focus();
});
$("navNew").addEventListener("click", () => {
  clearPicoInputs();
  $("picoEditor").open = false;
  $("query").value = "";
  $("topQuery").value = "";
  showDashboard();
  $("query").focus();
});
$("navSettings").addEventListener("click", () => openDrawer("settings"));
$("navNotifications").addEventListener("click", () => openDrawer("notif"));

/* 顶栏搜索框：回车直接提问 */
$("topQuery").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    const q = $("topQuery").value.trim();
    if (q) ask(q);
  }
});

renderHome();
applySettingsUI();
checkHealth();

// Compact navigation shares the existing workspace actions.
$("railHome").addEventListener("click", () => { showDashboard(); $("query").focus(); });
$("railHistory").addEventListener("click", () => openDrawer("notif"));
$("railSettings").addEventListener("click", () => openDrawer("settings"));

$("readingMode").addEventListener("click", toggleReadingMode);
$("jumpSources").addEventListener("click", () => focusSource(null));
$("cancelSearch").addEventListener("click", () => { cancelSearch(); $("query").focus(); });

$("sourceFilter").addEventListener("input", filterSources);

$("overviewNav").addEventListener("click", showDashboard);
$("searchNav").addEventListener("click", () => {
  $("query").scrollIntoView({ behavior: motionBehavior(), block: "center" });
  $("query").focus({ preventScroll: true });
});
$("historyNav").addEventListener("click", () => openDrawer("notif"));

// Text and study-type filters share the same visible-source count.
document.querySelectorAll("[data-source-type]").forEach(button => button.addEventListener("click", () => {
  sourceCategory = button.dataset.sourceType;
  document.querySelectorAll("[data-source-type]").forEach(item => {
    item.classList.toggle("selected", item === button);
    item.ariaPressed = String(item === button);
  });
  filterSources();
}));

$("query").addEventListener("input", () => clearPicoInputs($("query").value));
Object.values(PICO_INPUTS).forEach(id => $(id).addEventListener("input", () => { picoEdited = true; picoForQuery = $("query").value; }));
$("editPico").addEventListener("click", () => {
  $("picoEditor").open = true;
  $("picoEditor").scrollIntoView({behavior:motionBehavior(),block:"center"});
  $("editPicoP").focus({preventScroll:true});
});
$("applyPico").addEventListener("click", () => { picoEdited = true; picoForQuery = $("query").value; ask($("query").value); });

$("loadMoreSources").addEventListener("click",loadMoreSources);
if (typeof IntersectionObserver === "function") {
  const pages = new IntersectionObserver(entries => {
    if (entries.some(entry=>entry.isIntersecting)) loadMoreSources();
  },{rootMargin:"100px"});
  pages.observe($("loadMoreSources"));
}
