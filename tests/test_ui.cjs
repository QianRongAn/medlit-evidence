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
      listeners: {},
      addEventListener(name, handler) { this.listeners[name] = handler; }, focus() { this.focused = true; },
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

test("study-type distribution counts actual sources, including empty results", () => {
  const {context,get} = loadApp();
  const docs = [
    {study_type:"randomized_controlled_trial"},
    {study_type:"meta_analysis"}, {study_type:"systematic_review"},
    {study_type:"clinical_trial"}, {study_type:"notice"}, {},
  ];
  context.renderDist(docs);
  assert.equal(get("distTotal").textContent,"（纳入 6 篇）");
  assert.equal(get("distBar").children.length,3);
  assert.deepEqual(Array.from(get("distBar").children, segment => segment.style.background),
    ["#D9D6F7","#CFECFA","#E0F5CD"]);
  assert.deepEqual(Array.from(get("distLegend").children, item => item.innerHTML.match(/ (\d+)$/)[1]),["1","2","3"]);
  assert.equal(context.sourceType({study_type:"clinical_trial"}),"other");
  context.renderDist([]);
  assert.equal(get("distTotal").textContent,"（纳入 0 篇）");
  assert.equal(get("distLegend").textContent,"暂无纳入文献");
});

test("PICO overview names identified and unspecified conditions without invented matching percentages", () => {
  const {context,get} = loadApp();
  context.renderPico({population:["heart failure"], intervention:["SGLT2 inhibitor"]});
  assert.equal(get("picoP").textContent,"heart failure");
  assert.equal(get("picoC").textContent,"原问题未指定");
  assert.match(get("picoSummary").textContent,/已识别：人群、干预/);
  assert.match(get("picoSummary").textContent,/原问题未指定：对照、结局/);
  assert.doesNotMatch(get("picoSummary").textContent,/%|大部分匹配/);
  context.renderPico(null);
  assert.equal(get("picoP").textContent,"原问题未指定");
  assert.match(get("picoSummary").textContent,/尚未识别研究条件/);
});

test("source type filter combines with text and is reset by citation location", () => {
  const {context,get} = loadApp();
  context.renderDocs([{pmid:"123",title:"Heart failure trial",study_type:"randomized_controlled_trial"},
    {pmid:"456",title:"Heart failure review",study_type:"systematic_review"}]);
  vm.runInContext('sourceCategory = "synthesis"',context);
  get("sourceFilter").value="heart";
  context.filterSources();
  const [trial,review]=get("docList").children;
  assert.equal(trial.classList.contains("hidden"),true);
  assert.equal(review.classList.contains("hidden"),false);
  assert.equal(get("sourceVisible").textContent,"当前显示 1 / 2 篇文献");
  context.setTimeout=()=>1;
  const target=get("source-123");
  target.classList.add("hidden");
  context.focusSource("123");
  assert.equal(vm.runInContext('sourceCategory',context),"all");
  assert.equal(trial.classList.contains("hidden"),false);
  assert.equal(get("sourceFilter").value,"");
});

test("empty source results have an explicit message and no fabricated distribution", () => {
  const {context,get} = loadApp();
  context.renderDocs([]);
  context.renderDist([]);
  assert.equal(get("sourceEmpty").classList.contains("hidden"),false);
  assert.match(get("sourceEmpty").textContent,/没有通过筛选/);
  assert.equal(get("docCount").textContent,"0 篇文献");
  context.filterSources();
  assert.equal(get("sourceEmpty").classList.contains("hidden"),false);
});

test("manual PICO belongs to its question and is sent on re-query", async () => {
  const {context,get}=loadApp(); requestRuntime(context);
  get("editPicoP").value="adults";get("editPicoC").value="placebo";
  vm.runInContext('picoEdited=true; picoForQuery="metformin";',context);
  const payloads=[];
  context.fetch=async (_url,options)=>{payloads.push(JSON.parse(options.body));return {ok:true,json:async()=>emptyAnswer("metformin")};};
  await context.ask("metformin");
  assert.equal(payloads[0].pico.population,"adults");
  assert.equal(payloads[0].pico.comparison,"placebo");
  await context.ask("aspirin");
  assert.equal(payloads[1].pico,undefined);
  assert.equal(get("editPicoP").value,"");
});

test("retrieval summary separates the scanned pool, matches and displayed sources",()=>{
  const {context,get}=loadApp();
  const data={query:"metformin",total:4626,results:[{},{}],online:true,mode:"extractive",
    screening:{candidate_count:100,matched_count:35,included_count:2,excluded_count:65,not_displayed_count:33,search_exhausted:false}};
  context.renderStats(data,1200,null);context.renderScreening(data);
  assert.match(get("retrievalSummary").textContent,/已检查 100 篇 · 通过 35 篇 · 展示 2 篇/);
  assert.match(get("screeningNote").textContent,/33 篇通过筛选/);
  assert.match(get("screeningNote").textContent,/尚未检查全部/);
});

test("history action has no numeric badge in the shipped markup",()=>{
  const html=fs.readFileSync(path.join(__dirname,"../static/index.html"),"utf8");
  assert.doesNotMatch(html,/id="notifBadge"/);
  assert.match(html,/id="navNotifications"/);
});

test("page merging retains every unique match and keeps prior exclusions",()=>{
  const {context}=loadApp();
  const first={results:[{pmid:"1"},{pmid:"2"}],excluded_results:[{pmid:"9"}],screening:{candidate_count:3},evidence:{conclusions:[]}};
  const next={results:[{pmid:"2"},{pmid:"3"}],excluded_results:[{pmid:"8"}],screening:{candidate_count:3,next_cursor:"next"},evidence:{conclusions:[]}};
  const merged=context.mergeSourcePage(first,next);
  assert.deepEqual(Array.from(merged.results,d=>d.pmid),["1","2","3"]);
  assert.equal(merged.screening.candidate_count,6);
  assert.equal(merged.screening.included_count,3);
  assert.equal(merged.screening.excluded_count,2);
  assert.equal(merged.screening.next_cursor,"next");
});

test("next-page errors retain the current result and permit retry",async()=>{
  const {context,get}=loadApp();
  context.page={query:"metformin",total:4000,results:[{pmid:"1"}],screening:{next_cursor:"cursor",candidate_count:100}};
  vm.runInContext('resultData=page',context);
  context.AbortController=AbortController;
  context.fetch=async()=>({ok:false,json:async()=>({detail:"temporary failure"})});
  await context.loadMoreSources();
  assert.equal(vm.runInContext('resultData.results.length',context),1);
  assert.equal(get("pageError").textContent,"temporary failure");
  assert.equal(get("loadMoreSources").disabled,false);
});

test("a late source page cannot replace a new question",async()=>{
  const {context}=loadApp();context.AbortController=AbortController;
  context.page={query:"old",results:[],screening:{next_cursor:"cursor"}};
  vm.runInContext('resultData=page',context);
  let resolve;context.fetch=()=>new Promise(r=>resolve=r);
  const pending=context.loadMoreSources();
  context.cancelSourcePages();
  resolve({ok:true,json:async()=>({results:[{pmid:"99"}],screening:{}})});
  await pending;
  assert.equal(vm.runInContext('resultData',context),null);
});

test("source-reported grades and directions remain cited and are not numeric probabilities",()=>{
  const {context,get}=loadApp();
  vm.runInContext(fs.readFileSync(path.join(__dirname,"../static/assessment-ui.js"),"utf8"),context);
  context.renderReportedAssessment([{pmid:"123",reported_assessment:[{outcome:"mortality",direction:"decrease",question_direction:"decrease",alignment:"same_direction",findings:[{pmid:"123",quote:"Metformin reduced mortality.",label:"报告减少"}],source_certainty:[{pmid:"123",label:"中等",quote:"Moderate-certainty evidence."}]}]}]);
  assert.match(get("reportedDirection").innerHTML,/与提问方向一致 1/);
  assert.match(get("reportedDirection").innerHTML,/PMID 123/);
  assert.equal(get("confTag").textContent,"中等（原文报告）");
  assert.doesNotMatch(get("confTag").textContent,/%/);
  assert.match(get("reportedCertainty").innerHTML,/Moderate-certainty evidence/);
});

function automaticDoc(pmid,direction,priority=1) {
  return {pmid,source:"pubmed",reported_assessment:[{outcome:"mortality",direction,findings:[],source_certainty:[],
    automatic:{priority,design:"randomized_controlled_trial",domains:{risk_of_bias:{label:"偏倚风险",status:"unknown",evidence:[]}},
      certainty:{status:"limited",label:"可信度受限",reason:"未报告偏倚资料",lower:"极低",upper:"高"}}}]};
}

test("automatic direction and certainty appear without any manual GRADE input",()=>{
  const {context,get}=loadApp();
  vm.runInContext(fs.readFileSync(path.join(__dirname,"../static/assessment-ui.js"),"utf8"),context);
  context.renderReportedAssessment([automaticDoc("123","decrease")]);
  assert.match(get("reportedDirection").innerHTML,/现有证据提示减少（自动初评）/);
  assert.match(get("reportedCertainty").innerHTML,/可信度受限/);
  assert.match(get("reportedCertainty").innerHTML,/资料不足，未按通过处理/);
  assert.match(get("reportedCertainty").innerHTML,/无需填写人工工作表/);
  assert.match(get("confTag").textContent,/已自动初评/);
  assert.doesNotMatch(get("confDesc").textContent,/填写|点击生成/);
});

test("automatic conclusions update when later pages add a conflicting trial",()=>{
  const {context,get}=loadApp();
  vm.runInContext(fs.readFileSync(path.join(__dirname,"../static/assessment-ui.js"),"utf8"),context);
  const first={results:[automaticDoc("123","decrease")]};
  context.renderReportedAssessment(first.results);
  const merged=context.mergeSourcePage(first,{results:[automaticDoc("456","increase")],screening:{}});
  context.renderReportedAssessment(merged.results);
  assert.match(get("reportedDirection").innerHTML,/现有证据方向不一致（自动初评）/);
  assert.match(get("reportedCertainty").innerHTML,/PMID 456/);
});

test("an uncertain report is a caveat rather than opposite evidence",()=>{
  const {context,get}=loadApp();
  vm.runInContext(fs.readFileSync(path.join(__dirname,"../static/assessment-ui.js"),"utf8"),context);
  context.renderReportedAssessment([automaticDoc("123","decrease"),automaticDoc("456","uncertain")]);
  assert.match(get("reportedDirection").innerHTML,/现有证据提示减少（自动初评）/);
  assert.match(get("reportedDirection").innerHTML,/不确定不等于相反方向/);
});

test("lower-priority reviews do not outvote a trial and automatic quotes are escaped",()=>{
  const {context,get}=loadApp();
  vm.runInContext(fs.readFileSync(path.join(__dirname,"../static/assessment-ui.js"),"utf8"),context);
  const primary=automaticDoc("123","decrease");
  primary.reported_assessment[0].automatic.domains.risk_of_bias.evidence=[{quote:"<script>bad()</script>",pmid:"123"}];
  context.renderReportedAssessment([primary,...[1,2,3,4].map(n=>automaticDoc(String(n),"increase",3))]);
  assert.match(get("reportedDirection").innerHTML,/现有证据提示减少（自动初评）/);
  assert.doesNotMatch(get("reportedCertainty").innerHTML,/<script>/);
  assert.match(get("reportedCertainty").innerHTML,/&lt;script&gt;/);
});

function fulltextRuntime() {
  const runtime=loadApp();runtime.context.AbortController=AbortController;
  for(const name of ['assessment-ui.js','fulltext-ui.js']) vm.runInContext(fs.readFileSync(path.join(__dirname,'../static',name),'utf8'),runtime.context);
  return runtime;
}

test("fulltext automatically enriches every source in bounded batches without a total cap",async()=>{
  const {context,get}=fulltextRuntime();
  context.page={query:'metformin mortality',online:true,results:Array.from({length:26},(_,i)=>automaticDoc(String(i+1),'decrease')),
    screening:{candidate_count:100,next_cursor:'keep'},evidence:{}};
  vm.runInContext('resultData=page',context);
  const calls=[];
  context.fetch=async(url,options)=>{
    const body=JSON.parse(options.body);calls.push(body.pmids);
    assert.equal(url,'/api/assessment/fulltext');assert.ok(body.pmids.length<=10);
    return {ok:true,json:async()=>({results:body.pmids.map(pmid=>({...automaticDoc(pmid,'decrease'),fulltext:{status:'available'}}))})};
  };
  context.scheduleFulltextAssessment();
  for(let i=0;i<8;i++)await new Promise(setImmediate);
  assert.equal(calls.flat().length,26);assert.equal(new Set(calls.flat()).size,26);
  assert.match(get('fulltextStatus').textContent,/已取得 26 篇开放全文/);
  assert.equal(vm.runInContext('resultData.screening.next_cursor',context),'keep');
  assert.equal(vm.runInContext('resultData.screening.candidate_count',context),100);
  assert.equal(vm.runInContext('resultData === page',context),true);
});

test("a duplicate retrieval record preserves completed fulltext unless integrity changes",()=>{
  const {context}=loadApp();
  const old={...automaticDoc('123','decrease'),fulltext:{status:'available'},integrity:'ok'};
  const fresh={...automaticDoc('123','uncertain'),fulltext:{},integrity:'ok'};
  const merged=context.mergeSourcePage({results:[old]},{results:[fresh],screening:{}});
  assert.equal(merged.results[0].fulltext.status,'available');
  assert.equal(merged.results[0].reported_assessment[0].direction,'decrease');
  fresh.integrity='retracted';fresh.answer_eligible=false;
  assert.equal(context.mergeSourcePage({results:[old]},{results:[fresh],screening:{}}).results[0].fulltext.status,undefined);
});

test("late fulltext results cannot overwrite a new query",async()=>{
  const {context}=fulltextRuntime();
  context.page={query:'old',online:true,results:[automaticDoc('123','decrease')],screening:{},evidence:{}};
  vm.runInContext('resultData=page',context);
  let finish;
  context.fetch=()=>new Promise(resolve=>{finish=resolve;});
  context.scheduleFulltextAssessment();context.resetFulltextAssessment();
  vm.runInContext('resultData={query:"new",online:false,results:[]}',context);
  finish({ok:true,json:async()=>({results:[{pmid:'123',fulltext:{status:'available'}}]})});
  await new Promise(setImmediate);
  assert.equal(vm.runInContext('resultData.query',context),'new');
  assert.equal(vm.runInContext('resultData.results.length',context),0);
});

test("fulltext failures retain sources and explicit retry succeeds",async()=>{
  const {context,get}=fulltextRuntime();
  context.page={query:'metformin mortality',online:true,results:[automaticDoc('123','decrease')],screening:{},evidence:{}};
  vm.runInContext('resultData=page',context);
  context.fetch=async()=>{throw new Error('temporary failure');};
  context.scheduleFulltextAssessment();await new Promise(setImmediate);
  assert.equal(vm.runInContext('resultData.results.length',context),1);
  assert.match(get('fulltextStatus').textContent,/失败 1 篇/);
  assert.equal(get('retryFulltext').classList.contains('hidden'),false);
  context.fetch=async()=>({ok:true,json:async()=>({results:[{...automaticDoc('123','decrease'),fulltext:{status:'available'}}]})});
  get('retryFulltext').listeners.click();await new Promise(setImmediate);
  assert.match(get('fulltextStatus').textContent,/已取得 1 篇开放全文/);
});

test("incomplete manual GRADE does not display a completed level",async()=>{
  const {context,get}=loadApp();
  vm.runInContext(fs.readFileSync(path.join(__dirname,"../static/assessment-ui.js"),"utf8"),context);
  context.resetGradeReview();
  context.fetch=async()=>({ok:true,json:async()=>({status:"incomplete",missing:["imprecision","references"]})});
  await context.submitGradeReview();
  assert.match(get("gradeReviewResult").textContent,/待补齐：2 项/);
  assert.match(get("gradeReviewResult").textContent,/效应估计不精确性：请选择判断、请填写理由与依据/);
  assert.match(get("gradeReviewResult").textContent,/核查依据 PMID/);
  assert.equal(get("grade-imprecision").focused,true);
  assert.doesNotMatch(get("confTag").textContent,/人工草案/);
});

test("GRADE lists missing selections even when all rationales are filled",async()=>{
  const {context,get}=loadApp();
  vm.runInContext(fs.readFileSync(path.join(__dirname,"../static/assessment-ui.js"),"utf8"),context);
  context.resetGradeReview();
  for(const key of ["risk_of_bias","inconsistency","indirectness","imprecision","publication_bias"]) get("reason-"+key).value="已核对全文";
  context.fetch=async()=>({ok:true,json:async()=>({status:"incomplete",missing:["risk_of_bias","inconsistency","indirectness","imprecision","publication_bias","initial_evidence","references"]})});
  await context.submitGradeReview();
  assert.match(get("gradeReviewResult").textContent,/偏倚风险：请选择判断/);
  assert.match(get("gradeReviewResult").textContent,/证据起点/);
  assert.doesNotMatch(get("gradeReviewResult").textContent,/请填写理由/);
  assert.equal(get("gradeReview").open,true);
});

test("complete manual GRADE submits judgments and evidence and shows the draft",async()=>{
  const {context,get}=loadApp();
  vm.runInContext(fs.readFileSync(path.join(__dirname,"../static/assessment-ui.js"),"utf8"),context);
  get("gradeInitial").value="randomized";get("gradeReferences").value="123，456";
  for(const key of ["risk_of_bias","inconsistency","indirectness","imprecision","publication_bias"]){
    get("grade-"+key).value="not_serious";get("reason-"+key).value="核查依据";
  }
  context.fetch=async(url,options)=>{
    const body=JSON.parse(options.body);
    assert.equal(url,"/api/grade");assert.equal(body.initial,"randomized");
    assert.deepEqual(body.references,["123","456"]);assert.equal(body.domains.imprecision.rationale,"核查依据");
    return {ok:true,json:async()=>({status:"completed",label:"高",note:"未经独立审核"})};
  };
  await context.submitGradeReview();
  assert.equal(get("confTag").textContent,"高（人工草案）");
  assert.match(get("gradeReviewResult").textContent,/高可信度（人工草案）/);
  assert.equal(get("submitGrade").disabled,false);
});

test("editing GRADE while a submission is pending discards its stale grade",async()=>{
  const {context,get}=loadApp();
  vm.runInContext(fs.readFileSync(path.join(__dirname,"../static/assessment-ui.js"),"utf8"),context);
  let resolve;
  context.fetch=()=>new Promise(done=>{resolve=done;});
  const pending=context.submitGradeReview();
  get("reason-imprecision").listeners.input();
  resolve({ok:true,json:async()=>({status:"completed",label:"高",note:"old"})});
  await pending;
  assert.doesNotMatch(get("confTag").textContent,/人工草案/);
  assert.match(get("gradeReviewResult").textContent,/已修改/);
  assert.equal(get("submitGrade").disabled,false);
});

test("leaving a result clears the human GRADE worksheet",()=>{
  const {context,get}=loadApp();
  vm.runInContext(fs.readFileSync(path.join(__dirname,"../static/assessment-ui.js"),"utf8"),context);
  get("gradeReferences").value="123";
  get("gradeReviewResult").textContent="高（人工草案）";
  context.showDashboard();
  assert.equal(get("gradeReferences").value,"");
  assert.equal(get("gradeReviewResult").textContent,"");
});

test("integrity warnings also cover papers loaded on later pages",()=>{
  const {context}=loadApp();
  const merged=context.mergeSourcePage({results:[{pmid:"1",integrity:"ok"}],screening:{candidate_count:1}},
    {results:[{pmid:"2",integrity:"retracted",integrity_flags:["retracted"]}],screening:{candidate_count:1}});
  assert.equal(merged.evidence.retracted_count,1);
  assert.match(merged.evidence.integrity_warning,/已撤稿，不用于回答/);
});

test("an incomplete re-review clears a formerly completed manual grade",async()=>{
  const {context,get}=loadApp();
  vm.runInContext(fs.readFileSync(path.join(__dirname,"../static/assessment-ui.js"),"utf8"),context);
  context.fetch=async()=>({ok:true,json:async()=>({status:"incomplete",missing:["imprecision"]})});
  get("confTag").textContent="高（人工草案）";
  await context.submitGradeReview();
  assert.doesNotMatch(get("confTag").textContent,/人工草案/);
  assert.match(get("gradeReviewResult").textContent,/未生成分级/);
});
