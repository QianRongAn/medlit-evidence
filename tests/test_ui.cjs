const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// Minimal DOM for state assertions; no network or browser dependencies.
function loadApp(history = []) {
  const nodes = new Map();
  const storage = new Map([["medlit.history", JSON.stringify(history)]]);
  function element() {
    const classes = new Set();
    return {
      textContent: "", innerHTML: "", style: {}, dataset: {}, children: [],
      classList: {
        add: (...names) => names.forEach((n) => classes.add(n)),
        remove: (...names) => names.forEach((n) => classes.delete(n)),
        contains: (name) => classes.has(name),
        toggle: (name, enabled) => enabled ? classes.add(name) : classes.delete(name),
      },
      appendChild(child) { this.children.push(child); },
      addEventListener() {}, focus() { this.focused = true; },
      scrollIntoView(options) { this.scrollOptions = options; },
    };
  }
  const get = (id) => {
    if (!nodes.has(id)) nodes.set(id, element());
    return nodes.get(id);
  };
  const context = vm.createContext({
    document: {
      getElementById: get, createElement: element,
      createTextNode: (text) => ({ textContent: text }),
      querySelectorAll: () => [], querySelector: element, addEventListener() {},
    },
    localStorage: {
      getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: (key) => storage.delete(key),
    },
    window: { scrollTo() {} }, performance: { now: () => 0 },
    fetch: async () => ({ json: async () => ({ pubmed_online: false, corpus_size: 11 }) }),
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8"), context);
  return { context, get, storage };
}

test("unassessed confidence and conflict are never shown as zero or no conflict", () => {
  const { context, get } = loadApp();
  const evidence = {
    assessment_version: "2", assessment_status: "unassessed",
    assessment_note: "尚未验证问题与文献的结局一致性",
    verdict: "证据方向待核对", confidence: null, conflict: null,
    unassessed_count: 2, support_count: 0, against_count: 0, neutral_count: 0,
  };
  context.renderStats({ query: "他汀会增加新发糖尿病风险吗", total: 2,
    results: [{}, {}], online: true, mode: "extractive" }, 100, evidence);
  assert.equal(get("confidenceNum").textContent, "–");
  assert.equal(get("confScore").textContent, "–");
  assert.equal(get("confTag").textContent, "未评估");
  assert.equal(get("verdictText").textContent, "方向待核对");
  assert.equal(get("polarityLine").textContent, "方向未评估 2 篇");
  assert.equal(get("assessmentNote").textContent, evidence.assessment_note);
});

test("legacy history is retained but its conclusions and scores are retired", () => {
  const { context, get, storage } = loadApp([
    { query: "old question", verdict: "证据倾向支持", confidence: 98,
      conflict: true, time: Date.now(), elapsedMs: 100 },
  ]);
  const history = context.getHistory();
  assert.equal(history[0].query, "old question");
  assert.equal(history[0].verdict, "旧版判定已停用");
  assert.equal(history[0].confidence, null);
  assert.equal(history[0].conflict, null);
  assert.equal(get("usageConf").textContent, "–");
  assert.equal(get("usageConflict").textContent, "未评估");
  context.recordHistory("new question", { assessment_version: "2", verdict: "证据方向待核对" }, 100);
  const saved = JSON.parse(storage.get("medlit.history"));
  assert.equal(saved.length, 2);
  assert.equal(saved[0].assessment_version, "2");
  assert.equal(saved[0].confidence, null);
  assert.equal(saved[1].query, "old question");
});

test("non-array and invalid history entries do not break initialization", () => {
  assert.equal(loadApp({ invalid: true }).context.getHistory().length, 0);
  assert.equal(loadApp([null, 42]).context.getHistory().length, 0);
});

test("answer badges distinguish actual PubMed, demo and unverified LLM summaries", () => {
  const { context, get } = loadApp();
  context.renderAnswer({ answer: "excerpt", sentences: [], mode: "extractive", online: true });
  assert.equal(get("modeBadge").textContent, "摘要摘录（PubMed）");
  context.renderAnswer({ answer: "excerpt", sentences: [], mode: "extractive", online: false });
  assert.equal(get("modeBadge").textContent, "摘要摘录（演示语料）");
  context.renderAnswer({ answer: "summary", sentences: null, mode: "llm", online: true });
  assert.equal(get("modeBadge").textContent, "LLM 摘要整理（待核对）");
});

test("source sentences retain citations without support or opposition badges", () => {
  const { context, get } = loadApp();
  context.renderAnswer({ mode: "extractive", online: true,
    sentences: [{ sentence: "Statins increased risk of diabetes.", pmid: "123", polarity: "unassessed" }],
  });
  const sentence = get("answerBody").children[0];
  assert.equal(sentence.children[0].title, "结论方向：未评估");
  assert.equal(sentence.children[2].textContent, "PMID 123");
});

test("research scores have no probability sign or risk bands and legacy payloads are hidden", () => {
  const { context } = loadApp();
  const score = { kind: "research_model_score", score: 73, scale: [0, 100], calibrated: false };
  const badge = context.modelScoreBadge(score);
  assert.match(badge, /研究分数 73\.0 \/ 100/);
  assert.match(badge, /未校准，不代表未来撤稿概率/);
  assert.doesNotMatch(badge, /%|中高|中低|风险 73/);
  for (const bad of [null, { score: 0.73, level: "高" }, { ...score, calibrated: true },
      { ...score, score: NaN }, { ...score, score: -1 }, { ...score, score: 101 }]) {
    assert.equal(context.modelScoreBadge(bad), "");
  }
});

test("LLM validation scope and original quote are visible and invalid citations report fallback", () => {
  const { context, get } = loadApp();
  context.renderAnswer({ mode: "llm", online: true, sentences: [
    { sentence: "Summary", pmid: "123", polarity: "unassessed", quote: "Exact original abstract sentence." },
  ] });
  assert.match(get("answerNotice").textContent, /引用来源与对应原句已校验/);
  assert.match(get("answerNotice").textContent, /语义.*仍需核对/);
  assert.equal(get("answerBody").children[1].textContent, "对应摘要原句：Exact original abstract sentence.");
  context.renderAnswer({ mode: "extractive", online: true, answer: "Original excerpt",
    sentences: [], llm_fallback_reason: "citation_validation_failed" });
  assert.equal(get("answerNotice").textContent, "生成结果未通过引用校验，已改用摘要摘录。");
  context.renderAnswer({ mode: "extractive", online: true, answer: "Excerpt", sentences: [] });
  assert.equal(get("answerNotice").textContent, "");
});

test("multiple integrity flags and notice identity remain visible together", () => {
  const { context } = loadApp();
  const badges = context.integrityBadges({ integrity: "concern", integrity_flags: ["concern", "corrected"], is_notice: true });
  assert.match(badges, /存疑/);
  assert.match(badges, /有更正\/重发/);
  assert.match(badges, /学术通知/);
  assert.doesNotMatch(badges, /已撤稿/);
});

test("integrity links preserve direction and reject malformed linked IDs", () => {
  const { context } = loadApp();
  const links = context.integrityLinks({ integrity_relations: [
    { ref_type: "RetractionIn", pmid: "201" },
    { ref_type: "RetractionOf", pmid: "101" },
    { ref_type: "RetractedandRepublishedFrom", pmid: "104" },
    { ref_type: "ErratumIn", pmid: '123" onmouseover="x', citation: "<script>bad</script>" },
  ] });
  assert.match(links, /撤稿通知 · PMID 201/);
  assert.match(links, /所涉原文 · PMID 101/);
  assert.match(links, /已撤稿原版 · PMID 104/);
  assert.match(links, /&lt;script&gt;/);
  assert.doesNotMatch(links, /onmouseover|<script>/);
});

test("screening results expose counts and exclusions without calling them clinical inapplicability", () => {
  const { context, get } = loadApp();
  context.renderScreening({ screening: { candidate_count: 3, matched_count: 1, included_count: 1,
    excluded_count: 2, issues: [], note: "词项匹配不代表临床适用性。" }, excluded_results: [
    { title: "Wrong drug", screening: { reasons: ["missing_intervention"] } },
    { title: "<script>bad</script>", screening: { reasons: ["missing_outcome", "missing_abstract"] } },
  ] });
  assert.match(get("screeningNote").textContent, /候选 3 篇.*展示 1 篇.*未纳入 2 篇/);
  assert.match(get("screeningNote").textContent, /不代表临床适用性/);
  assert.equal(get("excludedSources").classList.contains("hidden"), false);
  assert.match(get("excludedList").children[0].innerHTML, /干预词项未覆盖/);
  assert.match(get("excludedList").children[1].innerHTML, /&lt;script&gt;/);
  context.renderScreening({ screening: { candidate_count: 0, matched_count: 0, included_count: 0,
    excluded_count: 0, issues: ["unsupported_numeric_constraint"], note: "" }, excluded_results: [] });
  assert.match(get("screeningNote").textContent, /尚不能解析数字条件/);
  assert.equal(get("excludedSources").classList.contains("hidden"), true);
});


test("comfortable reading toggles layout and exposes its state", () => {
  const {context, get} = loadApp();
  context.toggleReadingMode();
  assert.equal(get("result").classList.contains("reading-mode"), true);
  assert.equal(get("readingMode").ariaPressed, "true");
  context.toggleReadingMode();
  assert.equal(get("result").classList.contains("reading-mode"), false);
  assert.equal(get("readingMode").ariaPressed, "false");
});

test("full abstracts use native details and preserve escaped source text", () => {
  const {context, get} = loadApp();
  context.renderDocs([{pmid:"123", title:"A clinical study", grade:"High", abstract:"<script>unsafe()</script> Actual source."}]);
  const card = get("docList").children[0];
  assert.equal(card.id, "source-123");
  assert.match(card.innerHTML, /<details class="abstract-details">/);
  assert.match(card.innerHTML, /阅读完整摘要/);
  assert.match(card.innerHTML, /&lt;script&gt;unsafe\(\)&lt;\/script&gt;/);
  assert.doesNotMatch(card.innerHTML, /<script>/);
});

test("source location respects reduced motion and focuses the source", () => {
  const {context,get} = loadApp();
  context.window.matchMedia = () => ({matches:true});
  context.setTimeout = () => 0;
  context.focusSource("123");
  assert.equal(get("source-123").scrollOptions.behavior, "auto");
  assert.equal(get("source-123").focused, true);
  assert.equal(get("source-123").classList.contains("source-highlight"), true);
});

function requestRuntime(context) {
  context.AbortController = AbortController;
  context.setInterval = () => 1;
  context.clearInterval = () => {};
}
function emptyAnswer(query) {
  return {query, total:0, results:[], excluded_results:[], pico:{}, mode:"extractive",
    online:false, sentences:[], answer:"No source found.", evidence_distribution:{}};
}

test("cancelled responses cannot overwrite a newer query and duplicate submits are ignored", async () => {
  const {context,get} = loadApp();
  requestRuntime(context);
  const pending=[];
  context.fetch = (_url,options) => new Promise(resolve => pending.push({resolve,options}));
  const first=context.ask("first pending query");
  await context.ask("duplicate ignored query");
  assert.equal(pending.length,1);
  assert.equal(get("askBtn").disabled,true);
  context.cancelSearch();
  assert.equal(pending[0].options.signal.aborted,true);
  assert.equal(get("askBtn").disabled,false);
  const second=context.ask("newer query");
  pending[0].resolve({ok:true,json:async()=>emptyAnswer("stale query")});
  await first;
  assert.equal(get("askBtn").disabled,true);
  assert.equal(get("resultMeta").textContent,"");
  pending[1].resolve({ok:true,json:async()=>emptyAnswer("newer query")});
  await second;
  assert.equal(get("resultMeta").textContent,"「newer query」");
  assert.equal(get("askBtn").disabled,false);
  assert.equal(get("searchComposer").ariaBusy,"false");
});

test("request failure restores controls and permits another search", async () => {
  const {context,get} = loadApp();
  requestRuntime(context);
  context.fetch=async()=>({ok:false,status:503,json:async()=>({detail:"Service unavailable"})});
  await context.ask("failed query");
  assert.match(get("error").textContent,/Service unavailable/);
  assert.equal(get("error").classList.contains("hidden"),false);
  assert.equal(get("askBtn").disabled,false);
  assert.equal(get("askLabel").textContent,"检索证据");
  context.fetch=async()=>({ok:true,json:async()=>emptyAnswer("recovered query")});
  await context.ask("recovered query");
  assert.equal(get("resultMeta").textContent,"「recovered query」");
  assert.equal(get("error").classList.contains("hidden"),true);
});

test("source filtering searches text and PMID without changing the result total", () => {
  const {context, get} = loadApp();
  context.renderDocs([
    {pmid:"123",title:"Statin diabetes trial",abstract:"Adult participants",authors:["Smith"],year:2024},
    {pmid:"456",title:"Heart failure study",abstract:"Cardiovascular outcomes",authors:["Chen"]},
  ]);
  const [first, second] = get("docList").children;
  get("sourceFilter").value = " SMITH ";
  context.filterSources();
  assert.equal(first.classList.contains("hidden"), false);
  assert.equal(second.classList.contains("hidden"), true);
  assert.equal(get("sourceVisible").textContent, "当前显示 1 / 2 篇文献");
  assert.equal(get("docCount").textContent, "2 篇文献");
  get("sourceFilter").value = "456";
  context.filterSources();
  assert.equal(second.classList.contains("hidden"), false);
  get("sourceFilter").value = "no matching paper";
  context.filterSources();
  assert.equal(get("sourceEmpty").classList.contains("hidden"), false);
  get("sourceFilter").value = "";
  context.filterSources();
  assert.equal(first.classList.contains("hidden"), false);
  assert.equal(second.classList.contains("hidden"), false);
  assert.equal(get("sourceEmpty").classList.contains("hidden"), true);
  assert.equal(get("sourceVisible").textContent, "");
});

test("citation location clears a filter that would hide the cited source", () => {
  const {context, get} = loadApp();
  context.setTimeout = () => 1;
  const card = get("source-123");
  card.dataset.search = "statin trial";
  card.classList.add("hidden");
  get("docList").children.push(card);
  get("sourceFilter").value = "unrelated";
  context.focusSource("123");
  assert.equal(get("sourceFilter").value, "");
  assert.equal(card.classList.contains("hidden"), false);
  assert.equal(card.focused, true);
});

test("activity chart uses seven local calendar days and excludes future or older records", () => {
  const {context, get} = loadApp();
  const now = new Date(2026, 9, 21, 12);
  const days = context.dailyActivity([
    {time:new Date(2026,9,15,9).getTime()},
    {time:new Date(2026,9,21,8).getTime()},
    {time:new Date(2026,9,21,10).getTime()},
    {time:new Date(2026,9,14,23).getTime()},
    {time:new Date(2026,9,21,13).getTime()},
    {time:"invalid"},
  ], now);
  assert.equal(days.length,7);
  assert.deepEqual(Array.from(days,day=>day.count),[1,0,0,0,0,0,2]);
  assert.equal(days[0].date.getDate(),15);
  assert.equal(days[6].date.getDate(),21);
  context.renderActivity();
  assert.equal(get("activityTotal").textContent,"0 次");
  assert.match(get("activityChart").innerHTML,/还没有检索记录/);
  assert.doesNotMatch(get("activityChart").innerHTML,/<polygon/);
});
