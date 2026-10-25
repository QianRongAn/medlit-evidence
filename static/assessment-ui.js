/* Source-reported findings and an explicitly human-authored GRADE worksheet. */
const GRADE_DOMAINS = ["risk_of_bias", "inconsistency", "indirectness", "imprecision", "publication_bias"];
let gradeDraftComplete = false;

function resetGradeReview() {
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
  gradeDraftComplete = false;
  const demo = docs.length > 0 && docs.every(doc => ["offline", "demo"].includes(doc.source));
  $("submitGrade").disabled = demo;
  const reports = docs.flatMap(doc => (doc.reported_assessment || []).map(report => ({...report, pmid: doc.pmid})));
  const groups = new Map();
  reports.forEach(report => {
    if (!groups.has(report.outcome)) groups.set(report.outcome, []);
    groups.get(report.outcome).push(report);
  });
  const direction = [], certainties = [];
  const cite = pmid => /^[1-9][0-9]*$/.test(String(pmid))
    ? `<a href="https://pubmed.ncbi.nlm.nih.gov/${pmid}/" target="_blank" rel="noopener">PMID ${esc(String(pmid))}</a>` : "";
  groups.forEach((items, outcome) => {
    const count = key => items.filter(item => item.direction === key).length;
    const findings = items.flatMap(item => item.findings || []);
    const evidence = [...new Map(findings.map(item => [item.pmid + item.quote, item])).values()];
    direction.push(`<div class="reported-outcome"><b>${esc(outcome)}</b>
      <p>报告增加 ${count("increase")} · 报告减少 ${count("decrease")} · 未见明确方向 ${count("uncertain")} · 文内不一致 ${count("mixed")}</p>
      ${items.some(item=>item.question_direction) ? `<p>与提问方向一致 ${items.filter(item=>item.alignment==="same_direction").length} · 相反 ${items.filter(item=>item.alignment==="opposite_direction").length}；方向一致不等于临床结论成立。</p>` : ""}
      <small>可核对方向 ${items.filter(item => item.direction).length} / ${items.length} 篇；未命中规则的摘要仍需全文核查。</small>
      ${evidence.length ? `<details><summary>查看方向依据</summary>${evidence.map(item => `<blockquote>${esc(item.quote)}<br>${cite(item.pmid)} · ${esc(item.label)}</blockquote>`).join("")}</details>` : ""}</div>`);
    items.forEach(item => (item.source_certainty || []).forEach(source => certainties.push({...source, outcome})));
  });
  $("reportedDirection").innerHTML = direction.join("")
    || (demo ? '<p>当前为离线演示改写摘要，不进行方向或 GRADE 评估。</p>'
      : '<p>请补充具体结局，才能按结局核对方向。没有明确方向句时不会将其当作反对或无效。</p>');
  const unique = [...new Map(certainties.map(item => [item.pmid + item.quote, item])).values()];
  const levels = [...new Set(unique.map(item => item.label))];
  $("reportedCertainty").innerHTML = unique.length
    ? `<details><summary>原文 GRADE 评级及依据（${unique.length} 条）</summary>${unique.map(item => `<blockquote>${esc(item.label)} · ${esc(item.outcome)}<br>${esc(item.quote)}<br>${cite(item.pmid)}</blockquote>`).join("")}</details>`
    : '<p>摘要未报告可提取的 GRADE 评级；可展开工作表，核查五项后形成分级草案。</p>';
  $("confTag").textContent = levels.length ? levels.join(" / ") + "（原文报告）" : "需核查 5 项";
  $("confTag").style.color = "#5F6E83";
  $("confDesc").textContent = levels.length > 1 ? "来源评级不同，未合并成一个分数"
    : levels.length ? "来源评级，不是系统校准概率" : "填写依据后生成 GRADE 草案";
}

async function submitGradeReview() {
  const current = resultData;
  const domains = Object.fromEntries(GRADE_DOMAINS.map(key => [key, {
    severity: $("grade-" + key).value, rationale: $("reason-" + key).value || "",
  }]));
  const references = ($("gradeReferences").value || "").split(/[,，、\s]+/).filter(Boolean);
  $("submitGrade").disabled = true;
  try {
    const response = await fetch("/api/grade", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({initial: $("gradeInitial").value, domains, references})});
    const review = await response.json();
    if (resultData !== current) return;
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
    }
  } catch (error) {
    if (resultData === current) $("gradeReviewResult").textContent = error.message;
  } finally {
    $("submitGrade").disabled = false;
  }
}

$("submitGrade").addEventListener("click", submitGradeReview);

const reviewInputs = ["gradeInitial", "gradeReferences", ...GRADE_DOMAINS.flatMap(key => ["grade-" + key, "reason-" + key])];
reviewInputs.forEach(id => $(id).addEventListener("input", () => {
  if (!gradeDraftComplete) return;
  renderReportedAssessment(resultData?.results || []);
  $("gradeReviewResult").textContent = "核查内容已修改，请重新生成可信度分级草案。";
}));
