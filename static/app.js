const GRADE_ZH = {
  High: "高", Moderate: "中", Low: "低", "Very low": "极低", "N/A": "未分级",
};
const GRADE_COLOR = {
  High: "#16a34a", Moderate: "#2563eb", Low: "#f59e0b",
  "Very low": "#ef4444", "N/A": "#94a3b8",
};
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
  } catch {
    setStatus(false);
  }
}

function esc(s) {
  return (s || "").replace(/[&<>"]/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
  }[c]));
}

function renderAnswer(data) {
  const body = $("answerBody");
  body.innerHTML = "";
  if (data.sentences && data.sentences.length) {
    data.sentences.forEach((s) => {
      const p = document.createElement("p");
      p.textContent = s.sentence + " ";
      const cite = document.createElement("span");
      cite.className = "cite";
      cite.textContent = `[PMID ${s.pmid}]`;
      p.appendChild(cite);
      body.appendChild(p);
    });
  } else {
    const p = document.createElement("p");
    p.textContent = data.answer || "未能生成回答，请换一种问法。";
    body.appendChild(p);
  }
  $("modeBadge").textContent =
    data.mode === "llm" ? "生成式回答（LLM）" : "抽取式回答（离线）";
}

function renderDist(dist) {
  const bar = $("distBar");
  const legend = $("distLegend");
  bar.innerHTML = "";
  legend.innerHTML = "";
  const total = GRADE_ORDER.reduce((a, k) => a + (dist[k] || 0), 0) || 1;
  GRADE_ORDER.forEach((k) => {
    const v = dist[k] || 0;
    if (v === 0) return;
    const pct = (v / total) * 100;
    const seg = document.createElement("div");
    seg.className = "dist-seg";
    seg.style.width = pct + "%";
    seg.style.background = GRADE_COLOR[k];
    seg.title = `${k}：${v} 篇`;
    bar.appendChild(seg);

    const item = document.createElement("span");
    item.innerHTML = `<i class="swatch" style="background:${GRADE_COLOR[k]}"></i>${k} 级 · ${v} 篇`;
    legend.appendChild(item);
  });
}

function renderDocs(results) {
  const list = $("docList");
  list.innerHTML = "";
  $("docCount").textContent = `${results.length} 篇文献`;
  results.forEach((d) => {
    const div = document.createElement("div");
    div.className = "doc-item";

    const grade = GRADE_ZH[d.grade] || "未分级";
    const color = GRADE_COLOR[d.grade] || "#94a3b8";
    const url = d.pmid
      ? `https://pubmed.ncbi.nlm.nih.gov/${d.pmid}/`
      : "#";

    const authors = (d.authors || []).slice(0, 2).join(", ");
    const metaParts = [
      d.journal, d.year,
      `${STYPE_ZH[d.study_type] || "其他"} · 证据 ${grade}`,
      authors,
    ].filter(Boolean).join(" · ");

    div.innerHTML = `
      <p class="doc-title"><a href="${url}" target="_blank" rel="noopener">${esc(d.title)}</a></p>
      <div class="doc-meta">
        <span class="badge" style="background:${color}">${grade}</span>
        <span>${esc(metaParts)}</span>
        ${d.pmid ? `<span>PMID ${esc(d.pmid)}</span>` : ""}
      </div>
      ${d.abstract ? `<div class="doc-abstract">${esc(d.abstract)}</div>` : ""}
      <div class="rel-bar"><div class="rel-fill" style="width:${Math.max(2, d.relevance || 0)}%"></div></div>
    `;
    list.appendChild(div);
  });
}

function renderMeta(data) {
  const src = data.online ? "PubMed 在线检索" : "离线内置语料";
  const mode = data.mode === "llm" ? "生成式" : "抽取式";
  $("resultMeta").textContent =
    `「${data.query}」· ${src} · 命中 ${data.total} 条，返回 ${data.results.length} 条 · 回答模式：${mode}`;
}

async function ask(query) {
  if (!query.trim()) return;
  $("query").value = query;
  $("askBtn").disabled = true;
  $("result").classList.add("hidden");
  $("error").classList.add("hidden");
  $("loading").classList.remove("hidden");

  try {
    const r = await fetch("/api/answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    if (!r.ok) {
      const e = await r.json().catch(() => ({}));
      throw new Error(e.detail || `请求失败（${r.status}）`);
    }
    const data = await r.json();
    setStatus(data.online);
    renderMeta(data);
    renderAnswer(data);
    renderDist(data.evidence_distribution || {});
    renderDocs(data.results || []);
    $("loading").classList.add("hidden");
    $("result").classList.remove("hidden");
  } catch (err) {
    $("loading").classList.add("hidden");
    $("error").textContent = "出错了：" + err.message;
    $("error").classList.remove("hidden");
  } finally {
    $("askBtn").disabled = false;
  }
}

$("askBtn").addEventListener("click", () => ask($("query").value));
$("query").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) ask($("query").value);
});
document.querySelectorAll(".chip").forEach((c) =>
  c.addEventListener("click", () => ask(c.dataset.q))
);

checkHealth();
