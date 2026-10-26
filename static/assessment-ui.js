/* Source-reported findings and an explicitly human-authored GRADE worksheet. */
const GRADE_DOMAINS = ["risk_of_bias", "inconsistency", "indirectness", "imprecision", "publication_bias"];
const GRADE_LABELS = {risk_of_bias: "偏倚风险", inconsistency: "研究结果不一致性", indirectness: "对当前 PICO 的间接性", imprecision: "效应估计不精确性", publication_bias: "发表偏倚"};
let gradeDraftComplete = false;
let gradeRevision = 0;

function resetGradeReview() {
  gradeRevision++;
  gradeDraftComplete = false;
  $("gradeInitial").value = "unknown";
  $("gradeReferences").value = "";
  $("gradeReviewResult").textContent = "";
  $("gradeReview").open = false;
  GRADE_DOMAINS.forEach(key => {
    $("grade-" + key).value = "unknown";
    $("reason-" + key).value = "";
  });
}

function renderReportedAssessment(docs) {
  gradeRevision++;
  gradeDraftComplete = false;
  const demo = docs.length > 0 && docs.every(doc => ["offline", "demo"].includes(doc.source));
  $("submitGrade").disabled = demo;
  const reports = docs.flatMap(doc => (doc.reported_assessment || []).map(report => ({...report, pmid: doc.pmid})));
  const groups = new Map();
  reports.forEach(report => {
    if (!groups.has(report.outcome)) groups.set(report.outcome, []);
    groups.get(report.outcome).push(report);
  });
  const direction = [], certainties = [], automatic = [];
  const cite = pmid => /^[1-9][0-9]*$/.test(String(pmid))
    ? `<a href="https://pubmed.ncbi.nlm.nih.gov/${pmid}/" target="_blank" rel="noopener">PMID ${esc(String(pmid))}</a>` : "";
  groups.forEach((items, outcome) => {
    const usable = items.filter(item => item.direction && item.automatic);
    const priority = usable.length ? Math.min(...usable.map(item => item.automatic.priority)) : null;
    const selected = usable.filter(item => item.automatic.priority === priority);
    const distinct = [...new Set(selected.map(item => item.direction))];
    const clear = distinct.filter(value=>["increase","decrease"].includes(value));
    const consensus = clear.length > 1 || distinct.includes("mixed") ? "mixed" : clear[0] || (distinct.length ? "uncertain" : null);
    const summary = ({increase:"现有证据提示增加", decrease:"现有证据提示减少", uncertain:"现有证据尚不能确定方向", mixed:"现有证据方向不一致"}[consensus] || "当前结论依据不足");
    const count = key => items.filter(item => item.direction === key).length;
    const findings = items.flatMap(item => item.findings || []);
    const evidence = [...new Map(findings.map(item => [item.pmid + item.quote, item])).values()];
    direction.push(`<div class="reported-outcome"><b>${esc(outcome)}</b>
      <p><strong>${esc(summary)}（自动初评）</strong></p>
      ${clear.length && distinct.includes("uncertain") ? '<p>同时存在未能确定效应的报告；不确定不等于相反方向，亦不证明没有效应。</p>' : ""}
      <p>结论仅适用于这些文献实际研究的比较与人群；问题未指定对照时，不代表相对于某一特定对照的统一效应。</p>
      ${selected.length ? `<p>方向依据：${selected.map(item=>cite(item.pmid)).join(" · ")}。按研究设计层级选择依据，未按篇数投票，未合并可能重叠的样本。</p>` : ""}
      <p>报告增加 ${count("increase")} · 报告减少 ${count("decrease")} · 未见明确方向 ${count("uncertain")} · 文内不一致 ${count("mixed")}</p>
      ${items.some(item=>item.question_direction) ? `<p>与提问方向一致 ${items.filter(item=>item.alignment==="same_direction").length} · 相反 ${items.filter(item=>item.alignment==="opposite_direction").length}；方向一致不等于临床结论成立。</p>` : ""}
      <small>可核对方向 ${items.filter(item => item.direction).length} / ${items.length} 篇；未命中规则的摘要仍需全文核查。</small>
      ${evidence.length ? `<details><summary>查看方向依据</summary>${evidence.map(item => `<blockquote>${esc(item.quote)}<br>${cite(item.pmid)} · ${esc(item.label)}</blockquote>`).join("")}</details>` : ""}</div>`);
    items.forEach(item => (item.source_certainty || []).forEach(source => certainties.push({...source, outcome})));
    const assessed = selected.length ? selected : items.filter(item => item.automatic);
    if (assessed.length) automatic.push(`<div class="reported-outcome"><b>${esc(outcome)} · 自动可信度评估</b>
      <p>${esc([...new Set(assessed.map(item=>item.automatic.certainty.label))].join(" / "))}（摘要初评）</p>
      <details><summary>查看系统判断、引用依据与资料缺口</summary>${assessed.map(item => {
        const auto=item.automatic, certainty=auto.certainty;
        return `<section><p>${cite(item.pmid)} · ${esc(auto.design)} · ${esc(certainty.reason)}</p>
          ${certainty.lower && certainty.upper && certainty.status === "limited" ? `<p>可能分级范围：${esc(certainty.lower)}—${esc(certainty.upper)}；摘要缺失资料使范围尚不能收窄，不是已确定评级。</p>` : ""}
          ${Object.values(auto.domains).map(domain=>`<p><b>${esc(domain.label)}</b>：${esc(({serious:"发现明确局限",not_serious:"原文报告未发现严重问题",unknown:"资料不足，未按通过处理"})[domain.status])}</p>${domain.evidence.map(source=>source.quote ? `<blockquote>${esc(source.quote)}<br>${cite(source.pmid)}</blockquote>` : `<p>出版元数据：${esc(source.metadata)} · ${cite(source.pmid)}</p>`).join("")}`).join("")}</section>`;
      }).join("")}</details></div>`);
  });
  $("reportedDirection").innerHTML = direction.join("")
    || (demo ? '<p>当前为离线演示改写摘要，不进行方向或 GRADE 评估。</p>'
      : '<p>请补充具体结局，才能按结局核对方向。没有明确方向句时不会将其当作反对或无效。</p>');
  const unique = [...new Map(certainties.map(item => [item.pmid + item.quote, item])).values()];
  const levels = [...new Set(unique.map(item => item.label))];
  $("reportedCertainty").innerHTML = automatic.join("") + (unique.length
    ? `<details><summary>原文 GRADE 评级及依据（${unique.length} 条）</summary>${unique.map(item => `<blockquote>${esc(item.label)} · ${esc(item.outcome)}<br>${esc(item.quote)}<br>${cite(item.pmid)}</blockquote>`).join("")}</details>`
    : automatic.length ? '<p>以上为当前已加载文献的系统自动初评，非全文 GRADE；无需填写人工工作表。继续加载时自动更新。</p>' : '<p>当前资料无法提取可追溯的结局依据，系统不会虚构方向或分级。</p>');
  $("confTag").textContent = levels.length ? levels.join(" / ") + "（原文报告）" : automatic.length ? "已自动初评 · 见各结局" : "结论依据不足";
  $("confTag").style.color = "#5F6E83";
  $("confDesc").textContent = levels.length > 1 ? "来源评级不同，未合并成一个分数"
    : levels.length ? "来源评级，不是系统校准概率" : "系统已核查当前文献；判断与资料缺口见上方";
}

async function submitGradeReview() {
  const current = resultData;
  const revision = ++gradeRevision;
  const domains = Object.fromEntries(GRADE_DOMAINS.map(key => [key, {
    severity: $("grade-" + key).value, rationale: $("reason-" + key).value || "",
  }]));
  const references = ($("gradeReferences").value || "").split(/[,，、\s]+/).filter(Boolean);
  $("submitGrade").disabled = true;
  $("submitGrade").textContent = "正在生成草案…";
  $("gradeReviewResult").textContent = "正在核查填写内容…";
  try {
    const response = await fetch("/api/grade", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({initial: $("gradeInitial").value, domains, references})});
    const review = await response.json();
    if (resultData !== current || gradeRevision !== revision) return;
    if (!response.ok) throw new Error(typeof review.detail === "string" ? review.detail : "请检查核查字段与 PMID 格式。");
    $("gradeReviewResult").textContent = review.status === "completed"
      ? `${review.label}可信度（人工草案）。${review.note}`
      : `评估资料待补齐：${review.missing.length} 项，未生成分级。`;
    if (review.status === "completed") {
      gradeDraftComplete = true;
      $("confTag").textContent = review.label + "（人工草案）";
      $("confDesc").textContent = "5 项已填写，未经独立审核";
    } else {
      renderReportedAssessment(current?.results || []);
      const fields = [];
      const missing = review.missing.map(key => {
        if (key === "initial_evidence") { fields.push("gradeInitial"); return "证据起点：请选择随机试验或观察性证据"; }
        if (key === "references") { fields.push("gradeReferences"); return "核查依据 PMID：请填写文献编号"; }
        const domain = domains[key];
        if (!domain) return key;
        const parts = [];
        if (!["not_serious", "serious", "very_serious"].includes(domain.severity)) { fields.push("grade-" + key); parts.push("请选择判断"); }
        if (!domain.rationale.trim()) { fields.push("reason-" + key); parts.push("请填写理由与依据"); }
        return `${GRADE_LABELS[key]}：${parts.join("、") || "请核查填写内容"}`;
      });
      $("gradeReviewResult").textContent += " " + missing.join("；") + "。补齐后再次点击生成。";
      $("gradeReview").open = true;
      if (fields.length) $(fields[0]).focus();
    }
  } catch (error) {
    if (resultData === current && gradeRevision === revision) $("gradeReviewResult").textContent = "生成失败：" + error.message + " 请重试。";
  } finally {
    const docs = resultData?.results || [];
    $("submitGrade").disabled = docs.length > 0 && docs.every(doc => ["offline", "demo"].includes(doc.source));
    $("submitGrade").textContent = "生成可信度分级草案";
  }
}

$("submitGrade").addEventListener("click", submitGradeReview);

const reviewInputs = ["gradeInitial", "gradeReferences", ...GRADE_DOMAINS.flatMap(key => ["grade-" + key, "reason-" + key])];
reviewInputs.forEach(id => $(id).addEventListener("input", () => {
  gradeRevision++;
  if (gradeDraftComplete) renderReportedAssessment(resultData?.results || []);
  $("gradeReviewResult").textContent = "核查内容已修改，请重新生成可信度分级草案。";
}));
