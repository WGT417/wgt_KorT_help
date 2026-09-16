import sys, unittest, json, threading, io, tempfile
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
        self.assertFalse(core.route_question('피동과 사동의 차이','search')[0])
        self.assertTrue(core.route_question('심미적 독서는 문학 작품 읽기인가?','auto')[0])
        self.assertFalse(core.route_question('자유간접화법','auto')[0])
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
            with self.request('/api/ask',{'question':'심미적 독서인가?','category':'문식성','mode':'auto'}) as r:data=json.load(r)
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
        import subprocess
        result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'scripts'/'check_concepts.py')],capture_output=True,text=True,encoding='utf-8')
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

class QuotaTests(unittest.TestCase):
    def test_memory_quota_counts_and_refunds(self):
        import quota
        q=quota.MemoryQuota()
        with patch.object(quota,'LIMITS',(3,15,300)):
            self.assertEqual(q.peek('d','v','ip'),3)
            results=[q.consume('d','v','ip') for _ in range(4)]
            self.assertEqual([ok for ok,_ in results],[True,True,True,False])
            self.assertEqual([left for _,left in results],[2,1,0,0])
            q.refund('d','v','ip');self.assertEqual(q.peek('d','v','ip'),1)
            # Another visitor on the same IP is limited by the IP bucket, not the visitor's.
            self.assertTrue(q.consume('d','other','ip')[0])
            # A new day starts fresh.
            self.assertEqual(q.peek('e','v','ip'),3)
    def test_ip_and_daily_buckets_cap_everyone(self):
        import quota
        q=quota.MemoryQuota()
        with patch.object(quota,'LIMITS',(3,2,300)):
            self.assertTrue(q.consume('d','a','ip')[0]);self.assertTrue(q.consume('d','b','ip')[0])
            self.assertFalse(q.consume('d','c','ip')[0])
        with patch.object(quota,'LIMITS',(3,15,1)):  # a fresh day so the daily bucket starts at zero
            self.assertTrue(q.consume('e','x','ip1')[0]);self.assertFalse(q.consume('e','y','ip2')[0])

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
        self.cookie=''
        patches=[patch.object(server,'PUBLIC',True),patch.object(server,'ADMIN_TOKEN','test-admin-token'),patch.object(server,'QUOTA',quota.MemoryQuota()),
                 patch.object(server,'API_KEY','mock-key'),patch.object(server,'collect_evidence',lambda q,c,s,call,key:s),patch.object(server,'reason',return_value={'title':'mock'}),
                 patch.object(quota,'LIMITS',(3,15,300))]
        for p in patches:p.start();self.addCleanup(p.stop)
    def request(self,path,body=None,headers=None,keep_cookie=True):
        h={'Origin':'https://kor-teacher.web.app','X-Forwarded-Host':'kor-teacher.web.app','X-CSRF-Token':server.CSRF,'Content-Type':'application/json'}
        if self.cookie and keep_cookie:h['Cookie']=self.cookie
        if headers:h.update(headers)
        response=urlopen(Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers=h),timeout=20)
        set_cookie=response.headers.get('Set-Cookie')
        if set_cookie and keep_cookie:self.cookie=set_cookie.split(';')[0]
        return response
    def ask(self,**headers):
        with self.request('/api/ask',{'question':'피동과 사동의 차이','category':'문법','mode':'reason'},headers or None) as r:return json.load(r)
    def test_visitor_gets_three_explanations_per_day_and_cookie(self):
        with self.request('/api/status') as r:status=json.load(r)
        self.assertTrue(status['public']);self.assertFalse(status['admin']);self.assertEqual(status['quota'],{'limit':3,'remaining':3})
        self.assertTrue(self.cookie.startswith('__session='))
        results=[self.ask() for _ in range(4)]
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
