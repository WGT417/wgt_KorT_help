import unittest
from unittest.mock import patch
import explanation
from text_pipeline import compact

class EvidenceIdTests(unittest.TestCase):
    def test_server_resolves_existing_evidence_without_model_retyping(self):
        raw='독자는 자신의 읽기 목적을 확인한다. 글을 읽으며 배경 지식을 활용하고 이해한 내용을 점검하여 의미를 능동적으로 구성한다. 독자는 필요한 전략을 선택하고 조절한다.'
        source={'source_id':'S1','title':'테스트 자료','text':raw,'evidence_text':raw}
        packet,registry=explanation.evidence_packet([source])
        self.assertTrue(registry)
        for eid,citation in registry.items():
            self.assertIn(compact(citation['quote']),compact(raw))
            resolved=explanation.resolve_evidence({'citations':[{'evidence_id':eid}]},registry)
            self.assertEqual(resolved['citations'][0],citation)
        bad=explanation.resolve_evidence({'evidence_id':'not-provided'},registry)
        self.assertEqual(bad['source_id'],'invalid')

    def test_expansion_keeps_reading_domain_for_shared_concepts(self):
        initial=[{'id':1,'source_id':'S1','title':'독서','book_id':'none','pdf_page':1,'text':'독서의 개념과 의미 구성'}]
        with patch.object(explanation,'search_pages',return_value=[]) as search:
            explanation.collect_evidence('능동적으로 읽기','문식성',initial,lambda *a,**k:{'queries':['초인지','배경지식']},'mock')
        self.assertEqual([c.args[0] for c in search.call_args_list],['초인지 독서','배경지식 독서'])
