from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from scripts.expert_validation import freeze_package, load_package, template, evaluate_package, write, DOMAINS


class ExpertValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)/'package'
        self.materials={'tasks':[{'task_id':'T1','pmids':['123'],'query':'A clinical question','outcome':'mortality'}],
                        'documents':{'123':{'abstract':'An original abstract quote.', 'fulltext':{'blocks':[{'id':'b1','text':'The source supports this clinical judgment.'}]}}}}
        self.predictions=[{'task_id':'T1','direction':'decrease','certainty':'moderate'}]
        self.manifest=freeze_package(self.folder,self.materials,self.predictions)

    def review(self,person):
        review=template(self.materials['tasks'],self.manifest['materials_sha256'])
        review['reviewer']={'id':person,'role':'clinical specialist','expertise':'evidence synthesis','human_expert':True,'independent_review':True,'reviewed_at':'2026-10-27T12:00:00+08:00'}
        quote={'pmid':'123','block_id':'b1','quote':'The source supports this clinical judgment.'}
        decision=review['decisions'][0]
        decision.update(direction='decrease',certainty='moderate',rationale='Human reviewed clinical source and certainty rationale.',evidence=[quote])
        for domain in decision['domains'].values():
            domain.update(judgment='not_serious',rationale='Human checked the relevant source and trial methods.',evidence=[quote])
        return review

    def test_blind_materials_have_no_system_labels_and_no_expert_accuracy_is_invented(self):
        from scripts.expert_validation import read
        self.assertNotIn('predictions',read(self.folder/'blind/materials.json'))
        self.assertIsNone(read(self.folder/'validation_status.json')['expert_accuracy'])
        self.assertFalse(read(self.folder/'reviews/reviewer_A.json')['reviewer']['human_expert'])
        with self.assertRaises(FileExistsError):freeze_package(self.folder,self.materials,self.predictions)

    def test_blank_or_model_labels_are_refused(self):
        a,b=self.review('A'),self.review('B')
        for changed in ('human_expert','independent_review'):
            invalid=deepcopy(a);invalid['reviewer'][changed]=False
            with self.assertRaises(ValueError):evaluate_package(self.folder,invalid,b)
        with self.assertRaises(ValueError):evaluate_package(self.folder,template(self.materials['tasks'],self.manifest['materials_sha256']),b)

    def test_identical_reviewers_are_not_two_independent_experts(self):
        with self.assertRaises(ValueError):evaluate_package(self.folder,self.review('same'),self.review(' SAME '))

    def test_complete_consensus_scores_coverage_and_accuracy(self):
        result=evaluate_package(self.folder,self.review('A'),self.review('B'))
        self.assertEqual(result['status'],'expert_reviewed_pilot')
        self.assertEqual(result['expert_accuracy']['certainty']['accuracy_all_cases'],1)
        self.assertEqual(result['agreement']['direction']['agreement'],1)
        self.assertIsNone(result['agreement']['direction']['cohen_kappa'])
        self.assertFalse(result['clinical_generalization_validated'])

    def test_disagreement_requires_third_expert_and_scores_against_adjudication(self):
        a,b=self.review('A'),self.review('B');b['decisions'][0]['certainty']='low'
        result=evaluate_package(self.folder,a,b)
        self.assertEqual(result['status'],'awaiting_adjudication')
        self.assertIsNone(result['expert_accuracy'])
        with self.assertRaises(ValueError):evaluate_package(self.folder,a,b,b)
        judge=self.review('C');judge['decisions'][0]['certainty']='low'
        result=evaluate_package(self.folder,a,b,judge)
        self.assertEqual(result['adjudicated_tasks'],1)
        self.assertEqual(result['expert_accuracy']['certainty']['accuracy_all_cases'],0)

    def test_unknown_domain_differences_also_require_adjudication(self):
        a,b=self.review('A'),self.review('B')
        b['decisions'][0]['domains']['publication_bias']['judgment']='unknown'
        self.assertEqual(evaluate_package(self.folder,a,b)['status'],'awaiting_adjudication')

    def test_sources_blocks_quotes_and_case_identity_cannot_be_substituted(self):
        for change in ({'pmid':'999'},{'block_id':'missing'},{'quote':'Invented quote.'}):
            a,b=self.review('A'),self.review('B');a['decisions'][0]['evidence'][0].update(change)
            with self.assertRaises(ValueError):evaluate_package(self.folder,a,b)
        a,b=self.review('A'),self.review('B');a['package_sha256']='wrong'
        with self.assertRaises(ValueError):evaluate_package(self.folder,a,b)

    def test_partial_or_duplicate_reviews_cannot_inflate_scores(self):
        a,b=self.review('A'),self.review('B');a['decisions']=[]
        with self.assertRaises(ValueError):evaluate_package(self.folder,a,b)
        a=self.review('A');a['decisions']*=2
        with self.assertRaises(ValueError):evaluate_package(self.folder,a,b)

    def test_modified_predictions_or_materials_are_rejected(self):
        from scripts.expert_validation import read
        path=self.folder/'system/predictions.json'
        changed=read(path);changed[0]['certainty']='high';path.write_text(__import__('json').dumps(changed),encoding='utf-8')
        with self.assertRaises(ValueError):load_package(self.folder)

    def test_abstentions_stay_in_the_all_case_denominator(self):
        self.folder=Path(self.tmp.name)/'abstentions'
        freeze_package(self.folder,self.materials,[{'task_id':'T1','direction':'insufficient','certainty':'insufficient'}])
        result=evaluate_package(self.folder,self.review('A'),self.review('B'))
        self.assertEqual(result['expert_accuracy']['certainty']['accuracy_all_cases'],0)
        self.assertEqual(result['expert_accuracy']['certainty']['coverage'],0)
        self.assertIsNone(result['expert_accuracy']['certainty']['accuracy_when_answered'])

