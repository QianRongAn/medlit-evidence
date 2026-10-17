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
      addEventListener() {}, focus() {},
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
