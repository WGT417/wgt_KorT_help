import unittest
from unittest.mock import Mock
import core,server
from explanation import validate,collect_evidence,MAX_PAGES,resolve_evidence,mark_damage,scrub

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
        self.assertEqual(len({r['id'] for r in rows}),len(rows));self.assertLessEqual(len(rows),MAX_PAGES)
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

class EvidenceResolutionTests(unittest.TestCase):
    """The model names evidence ids; the server turns them into citations."""
    QUOTES=['간접 인용절은 원래 발화를 화자의 관점으로 바꾸어 전달하는 절이다.','직접 인용절에는 조사 라고가 붙고 원래 발화의 억양이 유지된다.']
    def setUp(self):
        self.source={'source_id':'S1','text':' '.join(self.QUOTES)}
        self.registry={'S1P1':{'source_id':'S1','quotes':self.QUOTES},'S1P2':{'source_id':'S1','quotes':[]},'K1-1':{'pages':[1,2,3]}}
    def answer(self,*ids,text='직접 인용절은 라고와 함께 억양을 유지한다.'):
        return {'title':'인용절','lead':{'text':'결론이다.','citations':[]},'sections':[{'title':'비교','subsections':[],'points':[{'label':'직접 인용','text':text,'examples':[],'citations':[{'evidence_id':i} for i in ids]}]}],'summary':{'columns':[],'rows':[]},'limitations':'','insufficient':False}
    def test_paragraph_cites_its_closest_clean_sentence(self):
        cited=resolve_evidence(self.answer('S1P1'),self.registry)['sections'][0]['points'][0]['citations']
        self.assertEqual(cited,[{'source_id':'S1','quote':self.QUOTES[1]}])
    def test_paragraph_without_clean_sentence_cites_the_page(self):
        cited=resolve_evidence(self.answer('S1P2'),self.registry)['sections'][0]['points'][0]['citations']
        self.assertEqual(cited,[{'source_id':'S1','quote':''}])
        self.assertEqual(validate(resolve_evidence(self.answer('S1P2'),self.registry),[self.source])['rejected_count'],0)
    def test_concept_item_cites_the_pages_it_rests_on(self):
        cited=resolve_evidence(self.answer('K1-1'),self.registry)['sections'][0]['points'][0]['citations']
        self.assertEqual([c['source_id'] for c in cited],['S1','S2'])
    def test_unknown_id_rejects_the_claim(self):
        result=validate(resolve_evidence(self.answer('S1P1','S9P9'),self.registry),[self.source])
        self.assertEqual(result['sections'],[]);self.assertEqual(result['rejected_count'],1)
    def test_lead_is_kept_and_meta_sentences_removed(self):
        answer=self.answer('S1P1',text='직접 인용절은 억양을 유지한다. 제공된 발췌문에서는 해당 문자가 OCR로 명확하게 보존되지 않았다.')
        result=validate(resolve_evidence(answer,self.registry),[self.source])
        self.assertEqual(result['lead']['text'],'결론이다.')
        self.assertEqual(result['sections'][0]['points'][0]['text'],'직접 인용절은 억양을 유지한다.')
        self.assertEqual(scrub('개론서에서는 다루지 않는다. 깨진 글자는 복원하지 않았다.'),'개론서에서는 다루지 않는다.')
    def test_damage_is_marked_by_sentence(self):
        text,damaged=mark_damage('중세 국어의 단모음은 일곱 개였다. 그 가운데 모Ab음은 깨졌다.')
        self.assertTrue(damaged)
        self.assertEqual(text,'중세 국어의 단모음은 일곱 개였다. ⟦그 가운데 모Ab음은 깨졌다.⟧')

class QuestionTermsTests(unittest.TestCase):
    """Every lexical term must appear in a paragraph, so the words that only ask are dropped."""
    def test_asking_words_are_not_search_terms(self):
        from retrieval import terms
        self.assertEqual(terms('소설의 시점에는 어떤 것들이 있나요?'),['소설','시점'])
        self.assertEqual(terms('음운 변동 중 교체에 해당하는 것을 알려줘'),['음운','변동','교체'])
        self.assertEqual(terms("중세국어에서 'ㅔ'는 단모음이 아니었지? 그리고 중세국어의 모음조화에 대해 설명해줘"),['중세국어','단모음','모음조화'])
    def test_names_keep_their_endings(self):
        from retrieval import terms
        for name in ['소설가','메타인지','미닫이','어린이','지도','태도']:self.assertEqual(terms(name),[name])

class ConceptPagesTests(unittest.TestCase):
    """A concept entry's pages lead the evidence, unless the entry is about the other genre."""
    def test_genre_of_the_question(self):
        from explanation import asked_genre
        for q,genre in [('1930년대 모더니즘 시의 특징과 대표 시인은?','poem'),('시조와 가사는 어떻게 다른가요?','poem'),('소설의 시점에는 어떤 것들이 있나요?','novel'),('시점이란',None),('시와 소설의 차이',None)]:
            self.assertEqual(asked_genre(q),genre,q)
    def test_entry_about_the_novel_does_not_lead_a_poem_question(self):
        from explanation import concept_pages
        from concepts import match_concepts
        q='1930년대 모더니즘 시의 특징과 대표 시인은?'
        self.assertEqual(concept_pages(q,match_concepts(q,'문학')),[])
        q='모더니즘 소설의 특징'
        self.assertTrue(concept_pages(q,match_concepts(q,'문학')))

if __name__=='__main__':unittest.main()
