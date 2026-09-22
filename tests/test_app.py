import sys, unittest, json, threading, io, tempfile, time, secrets
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core,server

class RetrievalTests(unittest.TestCase):
    def test_writing_process_finds_stages_in_original_excerpt(self):
        rows=core.search_pages('작문의 과정에 대해 알려줘.','문식성')
        # Require the actual stages, not a fixed page whose OCR is damaged.
        self.assertTrue(rows)
        self.assertTrue(all(r['excerpt'] in r['text'] for r in rows))
        self.assertTrue(all(r['title'].startswith('작문') for r in rows[:3]))
        first=core.normalized(rows[0]['excerpt'])
        self.assertGreaterEqual(sum(t in first for t in ['계획하기','내용생성','내용조직','고쳐쓰기','수정하기']),3)
    def test_particles_and_lexical_endings(self):
        self.assertEqual(core.query_terms('작문의 과정에 대해 알려줘'),['작문','과정'])
        self.assertEqual(core.query_terms('화자 시가 의미 쓰기'),['화자','시가','의미','쓰기'])
    def test_literary_equivalent(self):
        rows=core.search_pages('자유간접화법','문학')
        self.assertEqual(rows[0]['pdf_page'],243)
        self.assertIn('자유간접문체',core.normalized(rows[0]['text']))
    def test_reading_concept_retrieves_actual_explanation(self):
        rows=core.search_pages('읽기의 목적에서 심미적 독서는 문학 작품을 읽는 것인가?','문식성')
        self.assertEqual(rows[0]['title'],'독서교육론 사회평론')
        self.assertEqual(rows[0]['pdf_page'],71)
        self.assertEqual(rows[0]['printed_page'],70)
        self.assertTrue(all('심미적독서' in core.normalized(r['text']) for r in rows))
    def test_grammar_uses_multiple_books(self):
        rows=core.search_pages('피동과 사동의 차이는 무엇인가?','문법')
        self.assertGreaterEqual(len({r['book_id'] for r in rows}),2)
        self.assertTrue(all(r['category']=='문법' for r in rows))
        self.assertTrue(all('피동' in core.normalized(r['excerpt']) and '사동' in core.normalized(r['excerpt']) for r in rows))
    def test_routing_and_no_result(self):
        # Two modes, chosen by the visitor: the question text never decides.
        self.assertFalse(core.route_question('search')[0])
        self.assertTrue(core.route_question('reason')[0])
        self.assertEqual(core.search_pages('zxqvnonexistent98765','문학'),[])
    def test_generated_citations_fail_closed(self):
        sources=core.search_pages('피동 사동','문법')
        a=sources[0];quote=a['text'][20:100]
        good={'label':'valid','text':'valid','examples':[],'citations':[{'source_id':a['source_id'],'quote':quote}]}
        bad={'label':'invalid','text':'invalid','examples':[],'citations':[{'source_id':'S99999999','quote':quote}]}
        model={'sections':[{'title':'비교','points':[good,bad],'subsections':[]}],'summary':{'columns':['개념','설명'],'rows':[]}}
        with patch.object(server,'openai_call',return_value=model):result=server.reason('compare',sources)
        self.assertEqual(len(result['sections'][0]['points']),1)
        self.assertEqual(result['rejected_count'],1)
    def test_bad_model_shape(self):
        with patch.object(server,'openai_call',return_value=[]):
            with self.assertRaises(ValueError):server.reason('test',[])

class OpenAITransportTests(unittest.TestCase):
    def test_saved_key_can_be_replaced_and_deleted(self):
        with tempfile.TemporaryDirectory(dir=core.DATA) as directory,patch.object(server,'ROOT',Path(directory)),patch.object(server,'restrict_secret_file') as restrict:
            path=Path(directory)/'.env'
            path.write_text('OTHER=value\n',encoding='utf-8')
            server.save_api_key('test-first')
            server.save_api_key('test-second')
            self.assertEqual(restrict.call_count,2)
            self.assertEqual(path.read_text(encoding='utf-8'),'OTHER=value\nOPENAI_API_KEY=test-second\n')
            server.save_api_key('')
            self.assertEqual(restrict.call_count,3)
            self.assertEqual(path.read_text(encoding='utf-8'),'OTHER=value\n')
            self.assertFalse((Path(directory)/'.env.tmp').exists())

    def test_key_is_not_present_in_public_assets(self):
        secret='SENSITIVE_TEST_VALUE_FOR_PUBLIC_ASSET_AUDIT'
        for path in (server.ROOT/'dist').iterdir():
            if path.is_file():self.assertNotIn(secret,path.read_bytes().decode('utf-8',errors='ignore'))
    def test_fixed_model_auth_and_response_parsing(self):
        response={'status':'completed','output':[{'type':'reasoning'},{'type':'message','content':[{'type':'output_text','text':'{"claims":[]}'}]}]}
        with patch.object(server,'urlopen',return_value=io.BytesIO(json.dumps(response).encode())) as call:
            self.assertEqual(server.openai_call('Return JSON','test-secret'),{'claims':[]})
        request=call.call_args.args[0];payload=json.loads(request.data)
        self.assertEqual(request.full_url,'https://api.openai.com/v1/responses')
        self.assertEqual(request.get_header('Authorization'),'Bearer test-secret')
        self.assertEqual(payload['model'],'gpt-5.6-luna')
        self.assertFalse(payload['store'])
        self.assertNotIn('test-secret',request.full_url)
        self.assertNotIn('test-secret',request.data.decode())
    def test_incomplete_refusal_and_malformed_responses(self):
        responses=[{'status':'incomplete','output':[]},{'status':'completed','output':[{'type':'message','content':[{'type':'refusal','refusal':'No'}]}]},None]
        for response in responses:
            with self.subTest(response=response),patch.object(server,'urlopen',return_value=io.BytesIO(json.dumps(response).encode())):
                with self.assertRaises(ValueError):server.openai_call('JSON','test-secret')
    def test_api_errors_do_not_expose_secrets(self):
        for code in [401,403,404,429,500]:
            with self.subTest(code=code),patch.object(server,'urlopen',side_effect=HTTPError('https://api.openai.com/v1/responses',code,'test-secret',{},None)):
                with self.assertRaises(ValueError) as error:server.openai_call('JSON','test-secret')
                self.assertNotIn('test-secret',str(error.exception))

class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.old_port=server.PORT;server.PORT=cls.http.server_port
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start()
        cls.base=f'http://127.0.0.1:{server.PORT}'
    @classmethod
    def tearDownClass(cls):cls.http.shutdown();cls.http.server_close();server.PORT=cls.old_port
    def request(self,path,body=None,headers=None):
        h={'Origin':self.base,'X-CSRF-Token':server.CSRF,'Content-Type':'application/json'}
        if headers:h.update(headers)
        # A reason request runs one search per planned subtopic (about 15s here). A
        # client timeout leaves the server thread running into the next test's mocks.
        return urlopen(Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers=h),timeout=60)
    def test_search_does_not_call_openai_even_with_key(self):
        with patch.object(server,'API_KEY','not-a-real-secret-for-testing'),patch.object(server,'openai_call') as call:
            with self.request('/api/ask',{'question':'피동과 사동의 차이','category':'문법','mode':'search'}) as r:data=json.load(r)
            call.assert_not_called();self.assertFalse(data['ai_used']);self.assertGreater(len(data['sources']),0)
    def test_no_key_graceful_fallback(self):
        with patch.object(server,'API_KEY',''):
            with self.request('/api/ask',{'question':'심미적 독서인가?','category':'문식성','mode':'reason'}) as r:data=json.load(r)
            self.assertFalse(data['ai_used']);self.assertIn('키',data['notice'])
    def test_reason_pipeline_returns_sections_and_cited_table(self):
        source=core.search_pages('어미의 종류에 대해 설명해줘','문법')[0]
        citation={'source_id':source['source_id'],'quote':source['text'][20:100]}
        point={'label':'유형','text':'근거에 따른 설명','examples':[],'citations':[citation]}
        answer={'title':'어미의 분류','sections':[{'title':'분류','points':[point]*7,'subsections':[]}],'summary':{'columns':['유형','기능'],'rows':[{'cells':['어미','기능'],'citations':[citation]}]},'insufficient':False,'limitations':''}
        with patch.object(server,'API_KEY','mock-key'),patch.object(server,'openai_call',side_effect=[{'queries':['선어말어미','종결어미','연결어미','전성어미']},answer]) as call:
            with self.request('/api/ask',{'question':'어미의 종류에 대해 설명해줘','category':'문법','mode':'reason'}) as r:data=json.load(r)
        self.assertEqual(call.call_count,2);self.assertTrue(data['ai_used'])
        self.assertEqual(len(data['answer']['sections'][0]['points']),7)
        self.assertEqual(len(data['answer']['summary']['rows']),1)
        self.assertGreater(len(data['sources']),8)
        self.assertTrue(all('text' not in s for s in data['sources']))
    def test_secret_not_exposed_and_no_pdf(self):
        secret='not-a-real-secret-for-testing'
        with patch.object(server,'API_KEY',secret):
            with self.request('/api/status') as r:
                body=r.read().decode();self.assertNotIn(secret,body);self.assertNotIn('OPENAI_API_KEY',body)
                self.assertEqual(len(json.loads(body)['books']),26)
        for path in ['/.env','/server.py','/data/library.sqlite3','/api/books/0000000000000000/pdf']:
            with self.assertRaises(HTTPError) as e:self.request(path)
            self.assertEqual(e.exception.code,404)
    def test_bad_origin_and_host_and_category(self):
        for headers in [{'Origin':'https://evil.example'},{'Host':'evil.example'},{'X-CSRF-Token':'wrong'}]:
            with self.assertRaises(HTTPError) as e:self.request('/api/ask',{'question':'문법'},headers)
            self.assertEqual(e.exception.code,403)
        with self.assertRaises(HTTPError) as e:self.request('/api/ask',{'question':'문법','category':'참고자료'})
        self.assertEqual(e.exception.code,400)
    def test_assets(self):
        for path in ['/','/app.js','/style.css','/ux.css','/manifest.webmanifest','/sw.js','/icon-192.png','/icon-512.png']:
            with self.request(path) as r:self.assertEqual(r.status,200)
    def test_term_list_and_card(self):
        import gzip
        with self.request('/api/terms') as r:plain=json.load(r)
        with self.request('/api/terms',headers={'Accept-Encoding':'gzip'}) as r:
            self.assertEqual(r.headers['Content-Encoding'],'gzip');zipped=json.loads(gzip.decompress(r.read()))
        self.assertEqual(plain,zipped);self.assertGreater(len(plain['items']),6000)
        with self.request('/api/terms/card?q='+__import__('urllib.parse').parse.quote('관형절')) as r:data=json.load(r)
        self.assertIn('관형사절',data['terms'][0]['label'])
        # The same cards a question naming the term gets: 안은문장 names 관형절 only as an alias,
        # and the books define 관형절, so the entry is offered as background.
        with self.request('/api/ask',{'question':'관형절','category':'전체','mode':'search'}) as r:asked=json.load(r)
        self.assertEqual([(c['id'],c['match']) for c in data['concepts']],[(c['id'],c['match']) for c in asked['concepts']])
        # A card is about the whole term: one word of it (순서) does not bring in 서술 시간.
        with self.request('/api/terms/card?q='+__import__('urllib.parse').parse.quote('말차례 순서 정하기')) as r:data=json.load(r)
        self.assertEqual(data['concepts'],[])
        with self.request('/api/terms/card?q='+__import__('urllib.parse').parse.quote('안긴문장')) as r:data=json.load(r)
        self.assertEqual([(c['label'],c['match']) for c in data['concepts']],[('안은문장','exact')])
        # A concept no index names still opens as a card.
        with self.request('/api/terms/card?q='+__import__('urllib.parse').parse.quote('국어의 통시적 변화')) as r:data=json.load(r)
        self.assertEqual(data['terms'],[]);self.assertEqual(data['concepts'][0]['match'],'exact')
        for q in ['','zxqv%20%EC%97%86%EB%8A%94%20%EC%9A%A9%EC%96%B4']:
            with self.assertRaises(HTTPError) as e:self.request('/api/terms/card?q='+q)
            self.assertIn(e.exception.code,(400,404))

if __name__=='__main__':unittest.main(verbosity=2)

class ConceptTests(unittest.TestCase):
    def test_prewritten_concepts_match_by_term_without_ai(self):
        from concepts import match_concepts
        hits=match_concepts('SQ3R 모형에 대해 알려줘','문식성')
        self.assertEqual(hits[0]['id'],'reading-instruction/sq3r')
        self.assertTrue(all(s['id'] for s in hits[0]['sources']))
        self.assertEqual(match_concepts('zxqv 없는 개념','전체'),[])
        # A category filter hides concepts of other areas.
        self.assertEqual(match_concepts('SQ3R','문법'),[])
    def test_concept_files_pass_checker(self):
        import subprocess, os
        # Windows에서는 자식이 콘솔 코드페이지(cp949)로 한글을 내보내 utf-8 디코딩이 깨진다.
        env={**os.environ,'PYTHONIOENCODING':'utf-8'}
        result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'scripts'/'check_concepts.py')],capture_output=True,text=True,encoding='utf-8',env=env)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

class ConceptPrecisionTests(unittest.TestCase):
    def test_partial_word_match_is_background_not_answer(self):
        from concepts import match_concepts
        hits=match_concepts('재귀대명사','문법')
        self.assertEqual(hits[0]['id'],'parts-of-speech/reflexive-pronoun');self.assertEqual(hits[0]['match'],'exact')
        self.assertTrue(all(h['match']=='related' for h in hits[1:]))
        hits=match_concepts('재귀 대명사','문법')
        self.assertEqual(hits[0]['id'],'parts-of-speech/reflexive-pronoun')
        # The entry's own name in the question is an exact match.
        self.assertEqual(match_concepts('체언의 종류','문법')[0]['match'],'exact')
        self.assertEqual(match_concepts('체언의 종류','문법')[0]['id'],'parts-of-speech/nominals')
    def test_latin_extended_letters_are_ocr_noise(self):
        from passage_text import noise
        self.assertGreater(noise('재귀칭을 사용하나 Ð"표준국어대사전』에서는 재귀 대명사만을 표제어로 삼는다.'),0)

class TermIndexTests(unittest.TestCase):
    def test_indexed_term_returns_every_book_that_lists_it(self):
        from term_index import match_terms
        hits=match_terms('재귀 대명사','문법')
        self.assertTrue(hits);self.assertIn('재귀대명사',hits[0]['label'].replace(' ',''))
        self.assertGreaterEqual(len({s['book'] for s in hits[0]['sources']}),2)
        self.assertTrue(all(s['id'] for s in hits[0]['sources']))
        self.assertTrue(any(s['quote'] and '재귀' in s['quote'] for s in hits[0]['sources']))
        self.assertEqual(match_terms('zxqv 없는 용어','문법'),[])
        # A word inside a longer term does not match the longer term's neighbours by substring.
        self.assertTrue(all(h['key']!='대명사' for h in match_terms('재귀대명사','문법')))
    def test_term_card_leads_with_the_books_definitions(self):
        from term_index import match_terms
        card=match_terms('관형절','문법')[0]
        pages=[(s['book'],s['pdf_page']) for s in card['sources']]
        self.assertEqual(len(pages),len(set(pages)))
        first=card['sources'][0];self.assertTrue(first['definition'] and first['quote'])
        # 한국어문법총론 1, 265쪽 defines it; the page is listed once although both names index it.
        page=next(s for s in card['sources'] if s['book']=='한국어문법총론 1' and s['printed_page']==265)
        self.assertIn('관형사절이라고 부른다',page['quote'])
        # Pages that define come before pages that only mention the term.
        flags=[(s['definition'],bool(s['quote'])) for s in card['sources']]
        self.assertEqual(flags,sorted(flags,reverse=True))
        self.assertFalse(any('쩌' in (s['quote'] or '') for s in card['sources']))
    def test_index_page_numbers_survive_look_alike_letters(self):
        import sys;sys.path.insert(0,str(core.ROOT/'scripts'))
        from build_term_index import entries
        self.assertEqual(list(entries('명사구    Z73, 321\n명사형 어미     17l, 176')),[('명사구',[273,321]),('명사형 어미',[171,176])])
    def test_catalog_lists_every_card_once(self):
        from term_index import catalog,display_label,key_of,DEFINED,CONCEPT
        items=catalog()
        labels=[i[0] for i in items]
        self.assertEqual(len(labels),len({key_of(l) for l in labels}))
        # Every term that carries a defining sentence is on the list.
        self.assertEqual(sum(1 for i in items if i[3]&DEFINED),959)
        # A written concept no index names is a card of its own.
        self.assertIn('국어의 통시적 변화',labels)
        self.assertEqual(next(i for i in items if i[0]=='국어의 통시적 변화')[3],CONCEPT)
        # Headings standing in for a missing index do not become cards.
        self.assertNotIn('할 수도 없었다',labels)
        # A work title gets its bracket back, and the card is still found by the index's spelling.
        self.assertIn('〈광장〉',labels);self.assertNotIn('〈광장)',labels)
        self.assertEqual(display_label('「봄봄J'),'「봄봄」');self.assertEqual(display_label('《사슴}'),'《사슴》')
        self.assertEqual(display_label('<이춘풍전>의 세태 소설적 특성'),'<이춘풍전>의 세태 소설적 특성')
        # Jamo the scan read as Latin letters, fixed from the page: E is ㄷ in one book, ㄹ in another.
        self.assertIn('ㄷ 불규칙',labels);self.assertIn('ㄹ의 비음화',labels);self.assertEqual(display_label('r등신불J'),'「등신불」')
        # 가나다 order: Hangul first, a lone jamo heading its consonant, then Latin, then numbers.
        self.assertLess(labels.index('ㄴ 첨가'),labels.index('나관중'));self.assertLess(labels.index('꿈하늘'),labels.index('ㄴ 첨가'))
        self.assertLess(labels.index('힘의 전략'),labels.index('SQ3R 모형'));self.assertLess(labels.index('SQ3R 모형'),labels.index('2015 개정 교육과정'))
    def test_the_books_own_index_headings_are_not_cards(self):
        from term_index import catalog,JUNK,card
        labels={i[0]:i for i in catalog()}
        # "찾아보기" is the index itself; 답1·장)·도록하 are what a broken heading left.
        self.assertFalse([j for j in JUNK if j in labels])
        # A name the scan misread is one card with the right spelling, keeping both books' pages.
        self.assertNotIn('김기립',labels);self.assertNotIn('겸손볍',labels)
        self.assertGreaterEqual(labels['김기림'][2],4)
        self.assertEqual({s['book'] for s in card('김기림')[0]['sources']}>={'문학의 이해'},True)
        # A quoted jamo is named, and a work keeps the bracket the scan turned into J.
        self.assertIn('ㅂ 불규칙 동사',labels);self.assertIn('「삼대」',labels)
    def test_notes_are_read_ahead_and_cite_library_pages(self):
        from term_index import notes,note,catalog,NOTE,key_of
        written=notes()
        if not written:self.skipTest('data/term-notes.json이 없습니다')
        items={key_of(i[0]):i for i in catalog()}
        shown=[k for k in written if k in items]
        self.assertGreater(len(shown),0.95*len(written))
        for k in shown[:50]:
            self.assertTrue(items[k][3]&NOTE)
            n=note(items[k][0])
            self.assertTrue(n['definition'])
            self.assertTrue(n['citations'] and all(c['id'] and c['quote'] for c in n['citations']))
    def test_card_is_the_term_itself_from_every_area(self):
        from term_index import card,match_terms
        hit=card('관형절')[0]
        # The school-grammar name and the books' name are one card, as in a question.
        self.assertIn('관형사절',hit['label']);self.assertTrue(hit['sources'][0]['quote'])
        # 시점 is not answered with 전지적 작가 시점 or any other term containing it.
        self.assertEqual({h['key'] for h in card('시점')},{'시점'})
        self.assertEqual(card('zxqv 없는 용어'),[])
        self.assertTrue(card('〈광장〉'))
        # A label fixed into one already indexed is one card with both books' pages:
        # 국어음운론 강의 prints its heading L ’첨가.
        books={s['book'] for s in card('ㄴ 첨가')[0]['sources']}
        self.assertTrue({'국어음운론 강의','한국어문법총론 1'}<=books)
        self.assertEqual({s['book'] for s in match_terms('ㄴ 첨가','문법')[0]['sources']},books)

class QuotaTests(unittest.TestCase):
    def test_memory_quota_counts_the_day_and_refunds(self):
        import quota
        q=quota.MemoryQuota()
        with patch.object(quota,'LIMIT',3):
            self.assertEqual(q.peek('d'),3)
            results=[q.consume('d') for _ in range(4)]
            self.assertEqual([ok for ok,_ in results],[True,True,True,False])
            self.assertEqual([left for _,left in results],[2,1,0,0])
            q.refund('d');self.assertEqual(q.peek('d'),1)
            # A new day starts fresh.
            self.assertEqual(q.peek('e'),3)

class PublicModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.old_port=server.PORT;server.PORT=cls.http.server_port
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start()
        cls.base=f'http://127.0.0.1:{server.PORT}'
    @classmethod
    def tearDownClass(cls):cls.http.shutdown();cls.http.server_close();server.PORT=cls.old_port
    def setUp(self):
        import quota
        patches=[patch.object(server,'PUBLIC',True),patch.object(server,'ADMIN_TOKEN','test-admin-token'),patch.object(server,'QUOTA',quota.MemoryQuota()),
                 patch.object(server,'API_KEY','mock-key'),patch.object(server,'collect_evidence',lambda q,c,s,call,key:s),patch.object(server,'reason',return_value={'title':'mock'}),
                 patch.object(quota,'LIMIT',3)]
        for p in patches:p.start();self.addCleanup(p.stop)
    def request(self,path,body=None,headers=None):
        h={'Origin':'https://kor-teacher.web.app','X-Forwarded-Host':'kor-teacher.web.app','X-CSRF-Token':server.CSRF,'Content-Type':'application/json'}
        if headers:h.update(headers)
        return urlopen(Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers=h),timeout=60)  # a cold vector search can take tens of seconds
    def ask(self,**headers):
        with self.request('/api/ask',{'question':'피동과 사동의 차이','category':'문법','mode':'reason'},headers or None) as r:return json.load(r)
    def test_everyone_shares_one_daily_pool_and_no_cookie_is_set(self):
        with self.request('/api/status') as r:
            status=json.load(r);self.assertIsNone(r.headers.get('Set-Cookie'))
        self.assertTrue(status['public']);self.assertFalse(status['admin']);self.assertEqual(status['quota'],{'limit':3,'remaining':3})
        # Separate visitors, each with their own cookie: the count still runs down together.
        results=[self.ask(Cookie=f'__session=visitor{n}') for n in range(4)]
        self.assertEqual([d['ai_used'] for d in results],[True,True,True,False])
        self.assertEqual([d['quota']['remaining'] for d in results],[2,1,0,0])
        self.assertIn('3회',results[3]['notice']);self.assertGreater(len(results[3]['sources']),0)
    def test_admin_token_bypasses_quota(self):
        for _ in range(4):data=self.ask(**{'X-Admin-Token':'test-admin-token'})
        self.assertTrue(data['ai_used']);self.assertEqual(data['quota'],{'admin':True})
        self.assertFalse(self.ask(**{'X-Admin-Token':'wrong'})['quota'].get('admin'))
    def test_failed_generation_refunds_the_attempt(self):
        with patch.object(server,'reason',side_effect=ValueError('OpenAI 실패')):data=self.ask()
        self.assertFalse(data['ai_used']);self.assertEqual(data['quota']['remaining'],3);self.assertIn('실패',data['notice'])
    def test_slow_generation_hands_back_a_job_and_finishes_on_poll(self):
        # Firebase Hosting drops a request at 60s, so past AI_WAIT the page gets a job id and asks again.
        def slow(query,sources):time.sleep(2.5);return {'title':'slow mock'}
        with patch.object(server,'AI_WAIT',0),patch.object(server,'reason',side_effect=slow):
            first=self.ask()
            self.assertIn('pending',first);self.assertEqual(first['question'],'피동과 사동의 차이');self.assertNotIn('answer',first)
            for _ in range(10):
                with self.request('/api/ask/'+first['pending']) as r:data=json.load(r)
                if not data.get('pending'):break
        self.assertTrue(data['ai_used']);self.assertEqual(data['answer'],{'title':'slow mock'});self.assertEqual(data['quota']['remaining'],2)
        self.assertTrue(all('text' not in s for s in data['sources']))
        self.assertTrue(server.AI_LOCK.acquire(blocking=False));server.AI_LOCK.release()
        with self.assertRaises(HTTPError) as e:self.request('/api/ask/'+'x'*20)
        self.assertEqual(e.exception.code,404)
    def test_page_named_job_can_be_asked_for_after_a_reload(self):
        # The page picks the job id before sending, so a reload inside the first AI_WAIT still finds the answer.
        def slow(query,sources):time.sleep(1.5);return {'title':'slow mock'}
        def start(job):
            with self.request('/api/ask',{'question':'피동과 사동의 차이','category':'문법','mode':'reason','job':job},{'X-Admin-Token':'test-admin-token'}) as r:first=json.load(r)  # more asks than the day's 3
            for _ in range(10):
                with self.request('/api/ask/'+first['pending']) as r:data=json.load(r)
                if not data.get('pending'):break
            return first['pending'],data
        wanted='reload-test-'+secrets.token_urlsafe(12)
        with patch.object(server,'AI_WAIT',0),patch.object(server,'reason',side_effect=slow):
            job,data=start(wanted)
            self.assertEqual(job,wanted);self.assertEqual(data['answer'],{'title':'slow mock'})
            # An id already taken, or one that is not a plain token, gets a fresh one from the server.
            for bad in [wanted,'bad id!','x'*41,123]:
                job,data=start(bad);self.assertNotEqual(job,bad);self.assertEqual(data['answer'],{'title':'slow mock'})
    def test_unexpected_generation_error_refunds_and_frees_the_lock(self):
        with patch.object(server,'reason',side_effect=KeyError('boom')):data=self.ask()
        self.assertFalse(data['ai_used']);self.assertEqual(data['quota']['remaining'],3);self.assertIn('만들지 못했습니다',data['notice'])
        self.assertTrue(server.AI_LOCK.acquire(blocking=False));server.AI_LOCK.release()
    def test_quota_backend_down_refuses_generation(self):
        with patch.object(server,'QUOTA',None):data=self.ask()
        self.assertFalse(data['ai_used']);self.assertIn('중단',data['notice']);self.assertTrue(data['quota']['unavailable'])
    def test_public_origin_rules(self):
        body={'question':'문법','category':'문법','mode':'search'}
        with self.request('/api/ask',body,{'Origin':'https://evil.example','Sec-Fetch-Site':'same-origin'}) as r:self.assertEqual(r.status,200)
        for headers in [{'Origin':'https://evil.example'},{'Origin':'http://kor-teacher.web.app'},{'Origin':''}]:
            with self.assertRaises(HTTPError) as e:self.request('/api/ask',body,headers)
            self.assertEqual(e.exception.code,403)
        with self.request('/api/ask',body,{'Origin':'https://svc-abc.a.run.app','X-Forwarded-Host':'','Host':'svc-abc.a.run.app'}) as r:self.assertEqual(r.status,200)
    def test_key_endpoint_and_page_edits_are_locked(self):
        with self.assertRaises(HTTPError) as e:self.request('/api/key',{'key':'not-a-real-secret-for-testing'})
        self.assertEqual(e.exception.code,404)
        with self.assertRaises(HTTPError) as e:self.request('/api/pages/1/verify',{'printed_page':3})
        self.assertEqual(e.exception.code,403)
        # The admin path is not exercised here: it would write into the real library database.
