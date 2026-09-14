import unittest
from unittest.mock import Mock
import core,server
from explanation import validate,collect_evidence

class ExplanationTests(unittest.TestCase):
    def setUp(self):
        self.source={'source_id':'S1','text':'원문에 실제로 있는 인용문입니다. 충분히 길게 작성하여 대조합니다.'}
        self.citation={'source_id':'S1','quote':self.source['text']}
    def point(self):return {'label':'분류','text':'설명','examples':['형태'],'citations':[self.citation]}
    def answer(self):return {'title':'어미','sections':[{'title':'분류','points':[self.point()],'subsections':[]}],'summary':{'columns':['유형','기능'],'rows':[{'cells':['유형','기능'],'citations':[self.citation]}]},'limitations':'','insufficient':False}
    def test_nested_answer_and_table_citations(self):
        answer=self.answer();answer['sections'][0]['subsections']=[{'title':'하위 유형','points':[self.point()]}]
        result=validate(answer,[self.source])
        self.assertEqual(len(result['sections'][0]['subsections']),1)
        self.assertEqual(len(result['summary']['rows']),1)
        self.assertEqual(result['rejected_count'],0)
    def test_invalid_citations_remove_whole_claim_and_table_row(self):
        answer=self.answer();answer['sections'][0]['points'][0]['citations'].append({'source_id':'unknown','quote':self.source['text']})
        answer['summary']['rows'][0]['citations']=[{'source_id':'S1','quote':'조작한 인용문이므로 실제 원문에 존재하지 않습니다.'}]
        result=validate(answer,[self.source]);self.assertEqual(result['sections'],[]);self.assertEqual(result['summary']['rows'],[]);self.assertTrue(result['insufficient']);self.assertEqual(result['rejected_count'],2)
    def test_malformed_model_fields_fail_closed(self):
        answer=self.answer();answer['sections'][0]['points'][0]['citations']=[{'source_id':[],'quote':'anything'}]
        self.assertEqual(validate(answer,[self.source])['sections'],[])
    def test_definition_query_is_not_limited_to_word_kinds(self):
        rows=core.search_pages('어미의 종류에 대해 설명해줘','문법')
        self.assertTrue(any(r['title'] in ['우리말문법론','한국어문법총론 1','한국어표준문법'] for r in rows[:3]))
    def test_expansion_covers_subtopics_and_preserves_page_identity(self):
        initial=core.search_pages('어미의 종류에 대해 설명해줘','문법')
        call=Mock(return_value={'queries':['선어말어미','종결어미','연결어미','전성어미','명사형 어미','관형사형 어미']})
        rows=collect_evidence('어미의 종류','문법',initial,call,'test')
        self.assertEqual(len({r['id'] for r in rows}),len(rows));self.assertLessEqual(len(rows),28)
        self.assertTrue(all(r['source_id']==f"S{r['id']}" for r in rows))
        text=''.join(core.normalized(r['text']) for r in rows)
        for term in ['선어말어미','종결어미','연결어미','전성어미']:self.assertIn(term,text)
    def test_structured_schema_is_sent_to_api(self):
        import io,json
        from unittest.mock import patch
        with patch.object(server,'urlopen',return_value=io.BytesIO(json.dumps({'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'{}'}]}]}).encode())) as call:
            server.openai_call('JSON','test',schema={'type':'object'})
        payload=json.loads(call.call_args.args[0].data)
        self.assertEqual(payload['text']['format']['type'],'json_schema');self.assertTrue(payload['text']['format']['strict'])

if __name__=='__main__':unittest.main()
