"""Outcome-scoped source extraction and human GRADE regression fixtures (not clinical validation)."""
import unittest
from app.reported_assessment import assess_reported_findings, grade_review, GRADE_DOMAINS
from app.screening import build_query_plan


def assess(text,query="metformin mortality",**fields):
    return assess_reported_findings({"pmid":"123","abstract":text,"integrity":"ok","source":"pubmed",**fields},build_query_plan(query))


class ReportedFindingsTests(unittest.TestCase):
    def test_increasing_harm_is_an_increase_not_automatic_opposition(self):
        data=assess("RESULTS: Statin therapy increased risk of incident diabetes.","他汀会增加新发糖尿病风险吗")
        self.assertEqual(data[0]['direction'],'increase')
        self.assertIn('Statin therapy',data[0]['findings'][0]['quote'])
        self.assertNotIn('support',data[0])

    def test_different_outcomes_have_separate_directions(self):
        text="RESULTS: Metformin reduced mortality but metformin increased adverse events."
        rows=assess(text,'metformin mortality adverse events')
        self.assertEqual({r['outcome']:r['direction'] for r in rows},{'mortality':'decrease','adverse events':'increase'})

    def test_another_outcome_cannot_supply_the_requested_direction(self):
        self.assertIsNone(assess('RESULTS: Statins reduced cardiovascular risk.','statin incident diabetes')[0]['direction'])
        self.assertIsNone(assess('RESULTS: Incident diabetes during statin use was not associated with increased risk of MACE.','statin incident diabetes')[0]['direction'])

    def test_negated_findings_are_uncertain_not_opposition_or_proof_of_no_effect(self):
        for text in ['Metformin did not reduce mortality.','Metformin may reduce mortality.','Metformin was not associated with mortality.']:
            with self.subTest(text=text):self.assertEqual(assess('RESULTS: '+text)[0]['direction'],'uncertain')

    def test_comparator_effect_is_not_assigned_to_the_intervention(self):
        for text in ['Aspirin reduced mortality compared with metformin.',
                     'Metformin was compared with aspirin, which reduced mortality.',
                     'Aspirin, unlike metformin, reduced mortality.']:
            with self.subTest(text=text):self.assertIsNone(assess('RESULTS: '+text,'metformin versus aspirin mortality')[0]['direction'])
        self.assertEqual(assess('RESULTS: Metformin reduced mortality compared with aspirin.','metformin versus aspirin mortality')[0]['direction'],'decrease')

    def test_background_and_methods_do_not_become_findings(self):
        for text in ['BACKGROUND: Metformin reduced mortality. METHODS: We reviewed trials.',
                     'METHODS: We examined whether metformin reduced mortality.']:
            self.assertIsNone(assess(text)[0]['direction'])

    def test_explicit_pico_needs_context_and_contradictory_subgroups_abstain(self):
        query='metformin versus placebo in adults mortality'
        self.assertIsNone(assess('RESULTS: Metformin reduced mortality.',query)[0]['direction'])
        self.assertEqual(assess('METHODS: Adults received metformin or placebo. RESULTS: Metformin reduced mortality.',query)[0]['direction'],'decrease')
        self.assertIsNone(assess('METHODS: Adults and children received metformin or placebo. RESULTS: Metformin reduced mortality in children.',query)[0]['direction'])

    def test_integrity_and_demo_records_do_not_get_assessed(self):
        for options in [dict(integrity='retracted'),dict(is_notice=True),dict(source='demo'),dict(source='offline'),dict(source=None)]:
            self.assertEqual(assess('RESULTS: Metformin reduced mortality.',**options),[])

    def test_source_grade_is_a_quoted_source_claim(self):
        row=assess('CONCLUSIONS: Moderate-certainty evidence shows that metformin reduced mortality.')[0]
        self.assertEqual(row['source_certainty'][0]['level'],'moderate')
        self.assertIn('Moderate-certainty evidence',row['source_certainty'][0]['quote'])
        self.assertEqual(row['source_certainty'][0]['pmid'],'123')

    def test_negated_grade_and_statistical_confidence_are_not_grade(self):
        for quote in ['No high-certainty evidence for metformin and mortality was available.',
                      'Metformin reduced mortality with a high confidence interval.']:
            self.assertEqual(assess('CONCLUSIONS: '+quote)[0]['source_certainty'],[])

    def test_grade_is_not_transferred_between_outcomes(self):
        row=assess('CONCLUSIONS: High-certainty evidence for weight loss but low-certainty evidence for mortality with metformin.')[0]
        self.assertEqual([x['level'] for x in row['source_certainty']],['low'])

    def test_conflicting_within_paper_findings_are_not_majority_voted(self):
        row=assess('RESULTS: Metformin reduced mortality. Metformin increased mortality in a subgroup.')[0]
        self.assertEqual(row['direction'],'mixed')


class GradeWorksheetTests(unittest.TestCase):
    def domains(self):return {key:{'severity':'not_serious','rationale':'Reviewed source methods and results.'} for key in GRADE_DOMAINS}
    def test_complete_review_yields_named_grade_not_probability(self):
        fields=self.domains();fields['imprecision']['severity']='serious'
        result=grade_review('randomized',fields,['123'])
        self.assertEqual(result['level'],'moderate');self.assertEqual(result['source'],'user_review')
        self.assertNotIn('confidence',result)
    def test_missing_domain_reason_references_or_start_abstains(self):
        for initial,domains,refs in [('unknown',self.domains(),['123']),('randomized',{},['123']),('randomized',self.domains(),[])]:
            self.assertEqual(grade_review(initial,domains,refs)['status'],'incomplete')
        fields=self.domains();fields['imprecision']['rationale']=''
        self.assertEqual(grade_review('randomized',fields,['123'])['status'],'incomplete')
    def test_downgrades_have_a_floor_and_observational_studies_do_not_start_high(self):
        fields=self.domains()
        self.assertEqual(grade_review('observational',fields,['123'])['level'],'low')
        for field in fields.values():field['severity']='very_serious'
        self.assertEqual(grade_review('randomized',fields,['123'])['level'],'very low')

class GradeReviewAPITests(unittest.IsolatedAsyncioTestCase):
    async def test_rationales_alone_abstain_then_complete_judgments_generate_draft(self):
        import httpx
        from app.main import app
        from app.reported_assessment import GRADE_DOMAINS
        payload={'initial':'randomized','references':['12345678'],
                 'domains':{key:{'severity':'unknown','rationale':'已核查全文依据'} for key in GRADE_DOMAINS}}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            response=await client.post('/api/grade',json=payload)
            self.assertEqual(response.status_code,200)
            self.assertEqual(set(response.json()['missing']),set(GRADE_DOMAINS))
            for domain in payload['domains'].values():
                domain['severity']='not_serious'
            payload['domains']['imprecision']['severity']='serious'
            response=await client.post('/api/grade',json=payload)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['status'],'completed')
            self.assertEqual(response.json()['level'],'moderate')
            self.assertEqual(response.json()['source'],'user_review')

    async def test_unknown_fields_and_bad_pmids_are_rejected(self):
        import httpx
        from app.main import app
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            for payload in [{'domains':{'wrong':{}}},{'domains':{},'references':['javascript:bad']}]:
                self.assertEqual((await client.post('/api/grade',json=payload)).status_code,422)
            result=(await client.post('/api/grade',json={'domains':{}})).json()
            self.assertEqual(result['status'],'incomplete')

class QueryDirectionTests(unittest.TestCase):
    def test_effect_direction_is_stable_but_alignment_follows_the_question(self):
        quote='RESULTS: Statin therapy increased the risk of incident diabetes.'
        increase=assess(quote,'他汀会增加新发糖尿病风险吗')[0]
        decrease=assess(quote,'他汀会降低新发糖尿病风险吗')[0]
        self.assertEqual(increase['direction'],decrease['direction'])
        self.assertEqual(increase['alignment'],'same_direction')
        self.assertEqual(decrease['alignment'],'opposite_direction')

class EffectIntervalTests(unittest.TestCase):
    def test_ratio_crossing_one_is_not_a_clear_direction(self):
        result=assess('RESULTS: Metformin reduced mortality (hazard ratio 0.90; 95% CI 0.70-1.30).')[0]
        self.assertEqual(result['direction'],'uncertain')
    def test_ratio_interval_excluding_one_keeps_reported_direction(self):
        result=assess('RESULTS: Metformin reduced mortality (hazard ratio 0.80; 95% CI 0.70-0.90).')[0]
        self.assertEqual(result['direction'],'decrease')
    def test_difference_crossing_zero_is_uncertain(self):
        result=assess('RESULTS: Metformin reduced mortality (risk difference -0.01, 95% CI -0.05 to 0.03).')[0]
        self.assertEqual(result['direction'],'uncertain')
