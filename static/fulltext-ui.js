/* Full text enriches the current result without delaying retrieval or crossing queries. */
let fulltextEpoch = 0;
const fulltextRequests = new Set();

function resetFulltextAssessment() {
  fulltextEpoch++;
  fulltextRequests.forEach(controller => controller.abort());
  fulltextRequests.clear();
}

function fulltextProgress() {
  const docs = (resultData?.results || []).filter(doc=>doc.source === "pubmed" && doc.answer_eligible !== false);
  const count = status=>docs.filter(doc=>doc.fulltext?.status === status).length;
  const pending = docs.filter(doc=>!doc.fulltext?.status || doc.fulltext.status === "pending").length;
  $("fulltextStatus").textContent = docs.length ? `全文评估：已取得 ${count("available")} 篇开放全文 · 无可用开放全文 ${count("unavailable")} 篇 · 待处理 ${pending} 篇 · 失败 ${count("error")} 篇。`
    + (pending ? "正在自动补充全文依据，摘要结果可先阅读。" : "正文及可解析表格已处理；图像、外部补充文件和复杂表头仍有解析限制。") : "";
  $("retryFulltext").classList.toggle("hidden", !count("error"));
}

function scheduleFulltextAssessment() {
  fulltextProgress();
  if (!resultData?.online || fulltextRequests.size >= 2) return;
  const docs = (resultData.results || []).filter(doc=>doc.source === "pubmed" && doc.answer_eligible !== false && !doc.fulltext?.status).slice(0,10);
  if (!docs.length) return;
  docs.forEach(doc=>{doc.fulltext={status:"pending"};});
  const epoch = fulltextEpoch, query = resultData.query, controller = new AbortController();
  fulltextRequests.add(controller);
  fetch("/api/assessment/fulltext", {method:"POST",headers:{"Content-Type":"application/json"},signal:controller.signal,
    body:JSON.stringify({query,pmids:docs.map(doc=>String(doc.pmid)),...(resultPico ? {pico:resultPico} : {})})})
    .then(async response=>{
      const data=await response.json();
      if (!response.ok) throw new Error(data.detail || "全文评估请求失败");
      if (epoch !== fulltextEpoch || controller.signal.aborted || resultData?.query !== query) return;
      const current=new Map(resultData.results.map(doc=>[String(doc.pmid),doc]));
      const returned=new Map((data.results || []).map(doc=>[String(doc.pmid),doc]));
      const updates=docs.filter(doc=>current.has(String(doc.pmid))).map(doc=>{
        const updated=returned.get(String(doc.pmid));
        return updated ? {...current.get(String(doc.pmid)),...updated,risk:current.get(String(doc.pmid)).risk}
          : {...current.get(String(doc.pmid)),fulltext:{status:"error",reason:"全文服务未返回该记录"}};
      });
      const metadataChanged=updates.some(doc=>['study_type','integrity','is_notice','integrity_flags','integrity_relations'].some(key=>JSON.stringify(doc[key])!==JSON.stringify(current.get(String(doc.pmid))[key])));
      const screening=resultData.screening;
      Object.assign(resultData,{...mergeSourcePage(resultData,{results:updates,screening:{candidate_count:0}}),screening});
      const category=sourceCategory, filter=$("sourceFilter").value;
      if (metadataChanged) renderDocs(resultData.results);
      sourceCategory=category;$("sourceFilter").value=filter;filterSources();renderDist(resultData.results);
      document.querySelectorAll("[data-source-type]").forEach(button=>{
        button.classList.toggle("selected",button.dataset.sourceType===category);
        button.ariaPressed=String(button.dataset.sourceType===category);
      });
      $("integrityWarning").textContent=resultData.evidence.integrity_warning || "";
      $("integrityWarning").classList.toggle("hidden",!resultData.evidence.integrity_warning);
      if ($("gradeReviewResult").textContent) $("gradeReviewResult").textContent="全文依据已更新，人工复核草案需重新检查。";
      renderReportedAssessment(resultData.results);
    })
    .catch(error=>{
      if (epoch !== fulltextEpoch || controller.signal.aborted) return;
      docs.forEach(doc=>{
        const current=resultData?.results.find(item=>String(item.pmid)===String(doc.pmid));
        if (current) current.fulltext={status:"error",reason:error.message};
      });
    })
    .finally(()=>{
      fulltextRequests.delete(controller);
      if (epoch === fulltextEpoch) scheduleFulltextAssessment();
    });
  scheduleFulltextAssessment();
}

$("retryFulltext").addEventListener("click",()=>{
  (resultData?.results || []).forEach(doc=>{if(doc.fulltext?.status === "error")doc.fulltext={};});
  scheduleFulltextAssessment();
});
