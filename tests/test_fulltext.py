import asyncio
from copy import deepcopy
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app.fulltext import parse_jats, fetch_fulltext, enrich_fulltexts, _CACHE
from app.fulltext_assessment import assess_fulltext
from app.reported_assessment import reported_summary
from app.screening import build_query_plan

XML = '''<article><front><article-meta><article-id pub-id-type="pmid">123</article-id><article-id pub-id-type="pmc">456</article-id><permissions><license>CC BY 4.0</license></permissions></article-meta></front><body>
<sec><title>Introduction</title><p>Metformin increased mortality in previous studies.</p></sec>
<sec><title>Methods</title><p>We included 12 randomized controlled trials of metformin.</p></sec>
<sec><title>Results</title><p>Metformin reduced mortality (hazard ratio 0.8; 95% CI 0.7-0.9).</p>
<table-wrap><caption>Metformin compared with placebo</caption><table><thead><tr><td>Outcome</td><td>Certainty of evidence</td></tr></thead><tbody><tr><td>Mortality</td><td>Moderate</td></tr><tr><td>Adverse events</td><td>Low</td></tr></tbody></table></table-wrap></sec>
<sec><title>Limitations</title><p>Residual confounding could affect these estimates.</p></sec></body><back><ref-list><ref><mixed-citation>Metformin increased mortality.</mixed-citation></ref></ref-list></back></article>'''


def document(xml=XML):
    return {'pmid':'123','source':'pubmed','integrity':'ok','title':'Metformin compared with placebo',
            'study_type':'meta_analysis','abstract':'', 'fulltext':parse_jats(xml,'123','PMC456')}


class FulltextParserTests(unittest.TestCase):
    def test_identity_and_body_and_table_provenance(self):
        full= parse_jats(XML,'123','PMC456')
        self.assertEqual(full['status'],'available')
        self.assertEqual(full['license'],'CC BY 4.0')
        self.assertEqual(len(full['text_sha256']),64)
        rows=[b for b in full['blocks'] if b['kind']=='table']
        self.assertEqual(rows[0]['headers'],['Outcome','Certainty of evidence'])
        self.assertEqual(rows[0]['cells'],['Mortality','Moderate'])
        self.assertEqual(rows[0]['table_layout'],'simple')
        self.assertEqual(len({b['id'] for b in full['blocks']}),len(full['blocks']))
        self.assertFalse(any('previous' not in b['text'] and 'Metformin increased mortality.' == b['text'] for b in full['blocks']))

    def test_mismatched_missing_identity_and_entity_xml_are_rejected(self):
        for xml,pmid,pmcid in ((XML,'999','PMC456'),(XML,'123','PMC999'),(XML.replace('pub-id-type="pmid"','pub-id-type="other"'),'123','PMC456'),('<!ENTITY x "unsafe">'+XML,'123','PMC456')):
            with self.subTest(pmid=pmid,pmcid=pmcid),self.assertRaises(ValueError):
                parse_jats(xml,pmid,pmcid)

    def test_body_absent_cannot_be_marked_available(self):
        with self.assertRaises(ValueError):
            parse_jats(XML.replace('<body>','<abstract>').replace('</body>','</abstract>'),'123','PMC456')

    def test_complex_table_does_not_invent_grade_column_alignment(self):
        doc=document(XML.replace('<td>Moderate</td>','<td colspan="2">Moderate</td>'))
        plan=build_query_plan('metformin mortality')
        reported_summary([doc],plan);assess_fulltext(doc,plan)
        self.assertEqual(doc['reported_assessment'][0]['source_certainty'],[])

    def test_appendix_tables_are_parsed_but_references_are_excluded(self):
        xml=XML.replace('</article>','<floats-group><table-wrap><caption>Summary of findings</caption><table><thead><tr><th>Outcome</th><th>GRADE</th></tr></thead><tbody><tr><td>Mortality</td><td>Low</td></tr></tbody></table></table-wrap></floats-group></article>')
        self.assertEqual(len([b for b in parse_jats(xml,'123','PMC456')['blocks'] if b['kind']=='table']),3)


class FulltextAssessmentTests(unittest.TestCase):
    def test_grade_commentary_cannot_override_an_actual_effect(self):
        xml=XML.replace('<sec><title>Limitations</title>', '<sec><title>GRADE assessment</title><p>Low-quality evidence showed metformin increased mortality.</p></sec><sec><title>Limitations</title>')
        doc=document(xml);plan=build_query_plan('metformin mortality')
        reported_summary([doc],plan);assess_fulltext(doc,plan)
        self.assertEqual(doc['reported_assessment'][0]['direction'],'decrease')
        self.assertTrue(any(item['level']=='low' for item in doc['reported_assessment'][0]['source_certainty']))

    def test_grade_and_direction_from_fulltext_without_abstract(self):
        doc=document();plan=build_query_plan('metformin mortality')
        reported_summary([doc],plan)
        self.assertIsNone(doc['reported_assessment'][0]['direction'])
        assess_fulltext(doc,plan)
        report=doc['reported_assessment'][0]
        self.assertEqual(report['direction'],'decrease')
        self.assertEqual(report['automatic']['scope'],'full_text')
        self.assertEqual(report['automatic']['certainty']['level'],'moderate')
        self.assertEqual(report['automatic']['certainty']['status'],'source_reported')
        self.assertEqual(report['source_certainty'][0]['kind'],'outcome_grade_table')
        lookup={b['id']:b['text'] for b in doc['fulltext']['blocks']}
        items=report['findings']+report['source_certainty']+[item for d in report['automatic']['domains'].values() for item in d['evidence'] if item.get('quote')]
        for item in items:
            self.assertEqual(item['scope'],'full_text')
            self.assertIn(item['quote'],lookup[item['block_id']])
            self.assertEqual(item['text_sha256'],doc['fulltext']['text_sha256'])

    def test_other_outcome_and_comparator_grade_do_not_transfer(self):
        for xml in (XML.replace('<td>Mortality</td>','<td>Stroke</td>'),XML.replace('Metformin compared with placebo','Aspirin compared with placebo')):
            doc=document(xml)
            doc['title']='Study'
            plan=build_query_plan('metformin mortality')
            reported_summary([doc],plan);assess_fulltext(doc,plan)
            self.assertEqual(doc['reported_assessment'][0]['source_certainty'],[])

    def test_unavailable_fulltext_preserves_abstract_scope(self):
        doc=document();doc['abstract']='RESULTS: Metformin reduced mortality.'
        doc['fulltext']={'status':'unavailable'}
        plan=build_query_plan('metformin mortality')
        reported_summary([doc],plan);before=deepcopy(doc['reported_assessment'])
        assess_fulltext(doc,plan)
        self.assertEqual(doc['reported_assessment'],before)

    def test_fulltext_appraisal_does_not_mislabel_an_abstract_effect(self):
        doc=document(XML.replace('Metformin reduced mortality (hazard ratio 0.8; 95% CI 0.7-0.9).','No analyzable outcome was reported.'))
        doc['abstract']='RESULTS: Metformin reduced mortality.'
        plan=build_query_plan('metformin mortality')
        reported_summary([doc],plan);assess_fulltext(doc,plan)
        self.assertEqual(doc['reported_assessment'][0]['effect_scope'],'abstract')
        self.assertNotIn('block_id',doc['reported_assessment'][0]['findings'][0])


class FulltextClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        _CACHE.clear()

    async def test_access_identity_and_fixed_host(self):
        calls=[]
        def route(request):
            calls.append(str(request.url))
            if request.url.path.endswith('/search'):
                return httpx.Response(200,json={'resultList':{'result':[{'id':'123','source':'MED','pmcid':'PMC456','isOpenAccess':'Y'}]}})
            return httpx.Response(200,content=XML)
        async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as client:
            result=await fetch_fulltext('123',client)
            self.assertEqual(result['status'],'available')
            self.assertTrue(all(url.startswith('https://www.ebi.ac.uk/') for url in calls))
            cached=await fetch_fulltext('123',client)
            cached['blocks'].clear()
            self.assertTrue((await fetch_fulltext('123',client))['blocks'])
            self.assertEqual(len(calls),2)

    async def test_no_oa_is_unavailable_and_transient_failures_remain_retryable(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'resultList':{'result':[{'id':'123','source':'MED','pmcid':'PMC456','isOpenAccess':'N'}]}}))) as client:
            self.assertEqual((await fetch_fulltext('123',client))['status'],'unavailable')
        _CACHE.clear()
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(503))) as client:
            self.assertEqual((await fetch_fulltext('123',client))['status'],'error')
            self.assertNotIn('123',_CACHE)

    async def test_retracted_and_demo_documents_never_fetch_fulltext(self):
        with patch('app.fulltext.fetch_fulltext',AsyncMock()) as fetch:
            docs=[{'pmid':'1','source':'offline'}, {'pmid':'2','source':'pubmed','integrity':'retracted'}]
            await enrich_fulltexts(docs);fetch.assert_not_called()

    async def test_api_rechecks_original_metadata_and_rejects_url_input(self):
        from app import main
        raw={'pmid':'123','source':'pubmed','pubtypes':['Meta-Analysis'],'title':'Metformin mortality','abstract':'Metformin reduced mortality.'}
        async def enrich(docs):
            for doc in docs:doc['fulltext']=parse_jats(XML,'123','PMC456')
        with patch.object(main,'efetch',AsyncMock(return_value=[raw])),patch.object(main,'enrich_fulltexts',side_effect=enrich):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://test') as client:
                response=await client.post('/api/assessment/fulltext',json={'query':'metformin mortality','pmids':['123']})
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(response.json()['results'][0]['reported_assessment'][0]['automatic']['certainty']['level'],'moderate')
                self.assertNotIn('blocks',response.json()['results'][0]['fulltext'])
                self.assertEqual((await client.post('/api/assessment/fulltext',json={'query':'x','pmids':['https://example.com']})).status_code,422)

