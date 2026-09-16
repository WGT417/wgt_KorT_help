import sys,unittest,random
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core
import vector_search as vs
from passage_text import chunks,windows
from text_pipeline import compact

SENTENCES=['독서는 독자가 글과 상호작용하며 의미를 능동적으로 구성하는 과정이다.','독자는 배경지식을 활용하여 글에 드러나지 않은 내용을 추론한다.',
    '읽기 전략은 목적에 따라 의식적으로 선택되는 방법이다.','초인지는 자신의 이해 과정을 점검하고 조정하는 사고를 말한다.',
    '교사는 전략을 시범 보이고 학생이 점차 스스로 적용하게 한다.','평가는 학생의 읽기 수준을 진단하여 수업을 조정하는 데 쓰인다.']

def source(display):
    """Extracted text with OCR-like spacing: same glyphs, different whitespace."""
    return display.replace(' 의미를',' 의미\n를').replace('독자는 ','독자는').replace('. ','.\n')

class ChunkTests(unittest.TestCase):
    def test_chunks_cover_each_clean_sentence_once_in_source_order(self):
        display=' '.join(SENTENCES);raw=source(display)
        parts=chunks(raw,display,target=90,limit=200)
        self.assertGreater(len(parts),1)
        position=0
        for excerpt,text in parts:
            found=raw.find(excerpt,position)
            self.assertGreaterEqual(found,position);position=found+len(excerpt)
            self.assertEqual(compact(excerpt),compact(text))
            self.assertTrue(text.endswith('다.'))
        self.assertEqual(compact(''.join(t for _,t in parts)),compact(display))
    def test_damaged_sentence_is_left_out_but_neighbors_are_indexed(self):
        damaged='이 학습X까 독7-}를 이해한다.'
        display=' '.join(SENTENCES[:3]+[damaged]+SENTENCES[3:]);raw=source(display)
        texts=[t for _,t in chunks(raw,display,target=90,limit=200)]
        self.assertFalse(any('독7' in t for t in texts))
        self.assertTrue(any('추론한다' in t for t in texts) and any('진단하여' in t for t in texts))
    def test_block_ending_without_period_and_short_definition_are_indexed(self):
        display='가정 소설이란 가정 안에서의 생활을 주로 표현한 작품을 말한다. 고전소설 중에는 처첩 갈등을 다룬 작품이 많다'
        raw=display.replace(' ','')
        self.assertEqual(windows(raw,display),[])
        self.assertEqual([t for _,t in chunks(raw,display)],[display])

@unittest.skipUnless(vs.ready(),'BGE-M3 색인 없음: python scripts/build_vectors.py')
class VectorIndexTests(unittest.TestCase):
    def test_index_chunks_still_match_the_passages(self):
        db=vs.connect_index()
        try:rows=db.execute('SELECT passage_id,excerpt FROM chunks').fetchall()
        finally:db.close()
        random.seed(5);sample=random.sample(rows,min(300,len(rows)))
        with core.connect() as library:
            raw={r[0]:r[1] for r in library.execute('SELECT id,raw FROM passages WHERE id IN (%s)'%','.join('?'*len(sample)),[p for p,_ in sample])}
        self.assertTrue(all(excerpt in raw.get(p,'') for p,excerpt in sample))
    def test_nearest_stays_inside_the_category(self):
        hits=vs.nearest(vs.embed(['시적 화자와 어조'])[0],'문학',k=20)
        with core.connect() as db:
            categories={r[0] for r in db.execute('SELECT DISTINCT b.category FROM pages p JOIN books b ON b.id=p.book_id WHERE p.id IN (%s)'%','.join('?'*len(hits)),[h['page_id'] for h in hits])}
        self.assertEqual(categories,{'문학'})
        self.assertEqual([h['semantic'] for h in hits],sorted((h['semantic'] for h in hits),reverse=True))
    def test_paraphrase_without_the_term_finds_the_rule(self):
        # Lexical search alone returned nothing: no passage has all of these words.
        rows=core.search_pages('조사는 앞말에 붙이고 단어마다 떼어 적는 규정','문법')
        self.assertTrue(any(r['title']=='한국어표준문법' and abs(r['pdf_page']-232)<=1 for r in rows[:3]))
        found=[r for r in rows if r['match']=='semantic']
        self.assertTrue(found)
        self.assertTrue(all(r['excerpt'] in r['text'] and r['semantic_score']>=.55 for r in found))
    def test_named_concept_keeps_passages_that_name_it_first(self):
        rows=core.search_pages('자유간접화법','문학')
        self.assertEqual(rows[0]['match'],'lexical')

if __name__=='__main__':unittest.main()
