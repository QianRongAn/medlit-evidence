"""Freeze full-text review packages; score only completed independent human reviews."""
import argparse
import asyncio
import csv
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DOMAINS = ("risk_of_bias", "inconsistency", "indirectness", "imprecision", "publication_bias")
DIRECTIONS = {"increase", "decrease", "uncertain", "mixed", "no_important_difference", "insufficient"}
CERTAINTIES = {"high", "moderate", "low", "very low", "insufficient"}
SEVERITIES = {"not_serious", "serious", "very_serious", "unknown"}


def digest(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as target:
        target.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def template(tasks, package_hash):
    return {"package_sha256": package_hash, "reviewer":{"id":"", "role":"", "expertise":"",
            "human_expert":False, "independent_review":False, "reviewed_at":""},
            "decisions":[{"task_id":task["task_id"], "direction":"", "certainty":"", "rationale":"", "evidence":[],
                          "domains":{key:{"judgment":"", "rationale":"", "evidence":[]} for key in DOMAINS}} for task in tasks]}


def freeze_package(folder, materials, predictions, metadata=None):
    folder = Path(folder)
    if folder.exists():
        raise FileExistsError("choose a new package version; existing packages cannot be overwritten")
    task_ids = [task["task_id"] for task in materials["tasks"]]
    if not task_ids or len(task_ids) != len(set(task_ids)):
        raise ValueError("empty or duplicate review tasks")
    if {item['task_id'] for item in predictions} != set(task_ids) or len(predictions) != len(task_ids):
        raise ValueError("incomplete or duplicate system predictions")
    if any(item.get('direction') not in DIRECTIONS or item.get('certainty') not in CERTAINTIES for item in predictions):
        raise ValueError("invalid system prediction labels")
    if set(metadata or {}) & {'version','materials_sha256','predictions_sha256','expert_review_status','annotation_kind','clinical_generalization_validated'}:
        raise ValueError("metadata cannot override review or fingerprint status")
    fingerprint = digest(materials)
    manifest = {"version":1, "materials_sha256":fingerprint, "predictions_sha256":digest(predictions),
                "expert_review_status":"not_started", "annotation_kind":"unannotated_human_expert_pilot",
                "clinical_generalization_validated":False, **(metadata or {})}
    write(folder/"manifest.json", manifest)
    write(folder/"blind"/"materials.json", materials)
    write(folder/"system"/"predictions.json", predictions)
    for reviewer in ("A", "B"):
        write(folder/"reviews"/f"reviewer_{reviewer}.json", template(materials["tasks"], fingerprint))
    notes = ["# 专家独立盲审材料", "", "只向每位评审者发送本 blind 目录及其本人的空白 review 文件；不要提供 system 目录、另一位评审者的判断或模型输出。", "",
             "审阅 materials.json 中冻结的原始摘要、全文 blocks 和来源链接。GRADE 以结局对应的证据体为单位；不能按篇数投票或把文献类型直接当作结论可信度。", "",
             "review 文件需填写真实评审者身份、临床/循证角色、专长、独立审阅声明与时间。逐项填写 direction、certainty、五个 domains 的判断及理由。不能确定时选 insufficient / unknown 并解释原因。", "",
             '引用锚点格式：{"pmid":"文献编号","block_id":"b00001","quote":"该 block 中的连续原文"}。摘要使用 block_id="abstract"。非不足/未知判断必须有引用，不能虚构原句。', "",
             "方向值：increase / decrease / uncertain / mixed / no_important_difference / insufficient。可信度值：high / moderate / low / very low / insufficient。域值：not_serious / serious / very_serious / unknown。", "",
             "正文解析不包括图像与外部补充文件；复杂合并表头不能可靠映射时不得假装已有表格评级。若判断依赖未包含的材料，应记录不足而不是补造证据。专家资质由组织者线下核验；填写声明本身不能证明资质。", "",
             "## 问题与来源", ""]
    for task in materials['tasks']:
        notes += [f"### {task['task_id']}", "", task.get('question',task.get('query','')), "", f"指定结局：{task.get('outcome','')}", ""]
        for pmid in task['pmids']:
            source=materials['documents'][pmid];full=source.get('fulltext',{})
            notes.append(f"- PMID {pmid}: {source.get('title','')}；全文状态 {full.get('status','unavailable')}；[PubMed](https://pubmed.ncbi.nlm.nih.gov/{pmid}/)。")
            if full.get('status')=='available':
                notes.append(f"  [开放全文]({full['url']})；正文 SHA256 `{full['text_sha256']}`。材料版权与许可保留原文声明，不适用项目代码许可。")
        notes.append("")
    (folder/'blind/README.md').write_text('\n'.join(notes)+'\n',encoding='utf-8')
    write(folder/"validation_status.json", {"status":"awaiting_two_independent_experts", "expert_accuracy":None,
          "agreement":None, "tasks":len(task_ids), "reason":"尚无真实专家标注，不能报告专家验证准确率"})
    return manifest


def load_package(folder):
    folder = Path(folder)
    manifest, materials, predictions = read(folder/"manifest.json"), read(folder/"blind"/"materials.json"), read(folder/"system"/"predictions.json")
    if digest(materials) != manifest['materials_sha256'] or digest(predictions) != manifest['predictions_sha256']:
        raise ValueError("frozen source materials or predictions changed")
    return manifest, materials, predictions


def check_review(review, manifest, materials, expected_ids=None, adjudication=False):
    if review.get('package_sha256') != manifest['materials_sha256']:
        raise ValueError("review belongs to different materials")
    person = review.get('reviewer', {})
    if not all(isinstance(person.get(key), str) and person[key].strip() for key in ('id','role','expertise','reviewed_at')):
        raise ValueError("reviewer identity, clinical role, expertise and time are required")
    if person.get('human_expert') is not True or (not adjudication and person.get('independent_review') is not True):
        raise ValueError("model labels or non-independent reviews cannot serve as expert gold")
    datetime.fromisoformat(person['reviewed_at'].replace('Z','+00:00'))
    tasks = {task['task_id']:task for task in materials['tasks']}
    ids = set(tasks) if expected_ids is None else expected_ids
    decisions = review.get('decisions', [])
    if len(decisions) != len(ids) or {item.get('task_id') for item in decisions} != ids:
        raise ValueError("review has missing, duplicate or foreign decisions")

    def check_evidence(items, task, required):
        if not isinstance(items, list) or required and not items:
            raise ValueError("substantive judgments require source anchors")
        for item in items:
            pmid = item.get('pmid')
            if pmid not in task['pmids'] or pmid not in materials['documents']:
                raise ValueError("evidence PMID is outside this case")
            source = materials['documents'][pmid]
            block_id = item.get('block_id')
            text = source.get('abstract','') if block_id == 'abstract' else next(
                (b['text'] for b in source.get('fulltext',{}).get('blocks',[]) if b['id']==block_id), '')
            quote = item.get('quote')
            if not isinstance(quote, str) or not quote.strip() or quote not in text:
                raise ValueError("source quote/block does not match the frozen evidence")

    for item in decisions:
        if item.get('direction') not in DIRECTIONS or item.get('certainty') not in CERTAINTIES:
            raise ValueError("direction and certainty must be explicitly reviewed")
        if not isinstance(item.get('rationale'),str) or len(item['rationale'].strip()) < 10:
            raise ValueError("a substantive review rationale is required")
        check_evidence(item.get('evidence'), tasks[item['task_id']], item['direction']!='insufficient' or item['certainty']!='insufficient')
        if set(item.get('domains',{})) != set(DOMAINS):
            raise ValueError("all five GRADE domains must be reviewed")
        for domain in item['domains'].values():
            if domain.get('judgment') not in SEVERITIES or not isinstance(domain.get('rationale'),str) or len(domain['rationale'].strip())<10:
                raise ValueError("each domain requires a judgment and rationale")
            check_evidence(domain.get('evidence'), tasks[item['task_id']], domain['judgment']!='unknown')
    return {item['task_id']:item for item in decisions}


def labels(item):
    return (item['direction'],item['certainty'],*(item['domains'][key]['judgment'] for key in DOMAINS))


def agreement(left, right):
    n = len(left)
    same = sum(a==b for a,b in zip(left,right))
    categories = set(left+right)
    chance = sum(left.count(value)*right.count(value) for value in categories)/n**2
    observed = same/n
    return {'n':n,'agreement':observed,'cohen_kappa':(observed-chance)/(1-chance) if chance<1 else None}


def evaluate_package(folder, review_a, review_b, adjudication=None):
    manifest, materials, predictions = load_package(folder)
    a=check_review(review_a,manifest,materials)
    b=check_review(review_b,manifest,materials)
    if review_a['reviewer']['id'].strip().casefold()==review_b['reviewer']['id'].strip().casefold():
        raise ValueError("two different independent experts are required")
    conflicts = {key for key in a if labels(a[key])!=labels(b[key])}
    stats = {field:agreement([labels(a[key])[i] for key in a],[labels(b[key])[i] for key in a])
             for i,field in enumerate(('direction','certainty',*DOMAINS))}
    if conflicts and adjudication is None:
        return {'status':'awaiting_adjudication','conflicts':sorted(conflicts),'agreement':stats,'expert_accuracy':None}
    final = dict(a)
    if conflicts:
        judge=check_review(adjudication,manifest,materials,conflicts,adjudication=True)
        if adjudication['reviewer']['id'].strip().casefold() in {review_a['reviewer']['id'].strip().casefold(), review_b['reviewer']['id'].strip().casefold()}:
            raise ValueError("conflicts require a third expert")
        final.update(judge)
    metrics = {}
    for field in ('direction','certainty'):
        correct = sum(item[field]==final[item['task_id']][field] for item in predictions)
        answered = [item for item in predictions if item[field]!='insufficient']
        metrics[field]={'n':len(predictions),'correct':correct,'accuracy_all_cases':correct/len(predictions),
                        'coverage':len(answered)/len(predictions),
                        'accuracy_when_answered':sum(item[field]==final[item['task_id']][field] for item in answered)/len(answered) if answered else None}
    return {'status':'expert_reviewed_pilot','expert_accuracy':metrics,'agreement':stats,'adjudicated_tasks':len(conflicts),
            'review_sha256':[digest(review_a),digest(review_b),digest(adjudication)],
            'materials_sha256':manifest['materials_sha256'], 'predictions_sha256':manifest['predictions_sha256'],
            'identity_verification':'reviewer credentials are self-declared; organizer must verify them separately',
            'clinical_generalization_validated':False}


async def prepare(cases, output):
    from app import main
    from app.fulltext import enrich_fulltexts
    from app.fulltext_assessment import assess_fulltext
    from app.reported_assessment import reported_summary
    from app.automatic_assessment import summarize_automatic
    from app.screening import screen_document
    from app.integrity import is_usable_evidence
    proposed={pmid for case in cases for pmid in case['pmids']}
    for path in (ROOT/'data').glob('features*.csv'):
        with path.open(encoding='utf-8-sig') as source:
            if proposed & {row.get('pmid') for row in csv.DictReader(source)}:
                raise ValueError('pilot/training PMID overlap: '+str(path))
    prior=ROOT/'evaluation/clinical_v1/corpus.json'
    if prior.exists() and proposed & {str(doc['pmid']) for doc in read(prior)}:
        raise ValueError('new expert pilot overlaps the prior development benchmark')
    materials={'tasks':[], 'documents':{}}
    predictions=[]
    for case in cases:
        raw=await main.efetch(case['pmids'])
        if {doc['pmid'] for doc in raw} != set(case['pmids']):
            raise ValueError('PubMed did not return all frozen case documents')
        await enrich_fulltexts(raw)
        for source in raw:
            materials['documents'][source['pmid']]=deepcopy(source)
        _,plan=main._planned_query(case['query'])
        docs=main._annotate_docs(raw,plan['ranking_tokens'])
        docs=[doc for doc in docs if screen_document(doc,plan)['eligible'] and is_usable_evidence(doc)]
        reported_summary(docs,plan)
        for doc in docs:
            assess_fulltext(doc,plan)
        summaries=summarize_automatic(docs,[case['outcome']])
        task_id=case['id']+':'+case['outcome']
        materials['tasks'].append({'task_id':task_id,**case})
        summary=summaries[0]
        selected=[r for doc in docs for r in doc.get('reported_assessment',[]) if r['outcome']==case['outcome'] and doc['pmid'] in summary['references']]
        levels={r['automatic']['certainty']['level'] for r in selected}
        level=next(iter(levels)) if len(levels)==1 else None
        predictions.append({'task_id':task_id,'direction':summary['direction'] or 'insufficient','certainty':level or 'insufficient',
                            'assessment':summaries,'documents':docs})
    return freeze_package(output,materials,predictions,{'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                          'application_sha256':digest({p.name:p.read_text(encoding='utf-8') for p in sorted((ROOT/'app').glob('*.py'))}),
                          'sampling':'curator_selected_pilot_not_population_representative',
                          'training_pmid_overlap':False,'prior_clinical_benchmark_pmid_overlap':False})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    build=commands.add_parser('prepare');build.add_argument('--cases',required=True);build.add_argument('--output',required=True)
    score=commands.add_parser('score');score.add_argument('--package',required=True);score.add_argument('--review-a',required=True);score.add_argument('--review-b',required=True);score.add_argument('--adjudication');score.add_argument('--output',required=True)
    args=parser.parse_args()
    if args.command=='prepare':
        print(json.dumps(asyncio.run(prepare(read(args.cases),args.output)),ensure_ascii=False))
    else:
        review_a,review_b=read(args.review_a),read(args.review_b)
        result=evaluate_package(args.package,review_a,review_b,read(args.adjudication) if args.adjudication else None)
        write(args.output,result)
        if result['status']=='awaiting_adjudication':
            manifest,materials,_=load_package(args.package)
            draft=template([task for task in materials['tasks'] if task['task_id'] in result['conflicts']],manifest['materials_sha256'])
            draft['independent_prior_reviews']=[{'reviewer':review['reviewer'], 'decisions':[item for item in review['decisions'] if item['task_id'] in result['conflicts']]} for review in (review_a,review_b)]
            write(Path(args.output).with_suffix('.adjudication-template.json'),draft)
        print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
