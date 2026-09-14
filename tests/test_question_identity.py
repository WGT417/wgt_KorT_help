import unittest,threading,json
from urllib.request import urlopen,Request
from urllib.error import HTTPError
import core
from scripts.preview_explanation import Preview
from http.server import ThreadingHTTPServer

class QuestionIdentityTests(unittest.TestCase):
    def test_active_reading_has_reading_evidence(self):
        rows=core.search_pages('능동적으로 읽기에 대해 알려줘','문식성')
        self.assertTrue(rows)
        self.assertTrue(any('독서교육론' in r['title'] for r in rows[:3]))
        self.assertTrue(all('능동적' in core.normalized(r['text']) for r in rows))
        self.assertIn('의미를구성',core.normalized(rows[0]['display_excerpt']))
        self.assertNotIn('독독자가',core.normalized(rows[0]['display_excerpt']))
        self.assertTrue(all('비상교과서' not in r['display_excerpt'] and '지학사' not in r['display_excerpt'] for r in rows))
        self.assertTrue(all('작문' not in r['title'] for r in rows))
        self.assertTrue(core.route_question('능동적으로 읽기에 대해 알려줘','auto')[0])
    def test_retired_preview_never_returns_canned_answer(self):
        http=ThreadingHTTPServer(('127.0.0.1',0),Preview)
        threading.Thread(target=http.serve_forever,daemon=True).start()
        try:
            for question in ['어미의 종류','능동적으로 읽기']:
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(f'http://127.0.0.1:{http.server_port}/api/ask',data=json.dumps({'question':question}).encode()))
                self.assertEqual(error.exception.code,410)
                self.assertNotIn('answer',json.load(error.exception))
        finally:http.shutdown();http.server_close()
