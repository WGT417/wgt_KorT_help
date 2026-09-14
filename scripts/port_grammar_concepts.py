"""Import the grammar concept dictionary exported from kor-eduai-site into concepts/문법.json.

Input: a JSON export of GRAMMAR_CONCEPT_DICTIONARY and the concept→page candidate
file. Text is copied as drafts written for exam learners; each entry is marked so
the teacher-facing wording can be reviewed. Book pages are mapped onto this
library by title and PDF page, and rechecked against the page text before being
kept.
"""
import sys,json,re,argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core

BOOKS={'grammar-phonology':'국어음운론 강의','grammar-korean-overview-1':'한국어문법총론 1','grammar-standard-korean':'한국어표준문법','grammar-korean-language-history':'쉽게 풀어 쓴 국어사 개론','grammar-korean-grammar':'우리말문법론'}
PARENTS={'phoneme-system':'음운 체계','phonological-change':'음운 변동','morpheme-word':'형태소와 단어 형성','parts-of-speech':'품사','sentence-structure':'문장 성분과 문장 구조','grammar-elements':'문법 요소','meaning-pragmatics':'의미·화용·담화','language-history':'국어사','orthography-pronunciation':'어문 규범과 표준 발음'}

def compact(t):return re.sub(r'\s+','',t).lower()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('export');parser.add_argument('references');parser.add_argument('--out',default=str(core.ROOT/'concepts'/'문법.json'))
    args=parser.parse_args()
    data=json.loads(Path(args.export).read_text(encoding='utf-8'))
    refs={c['conceptId']:c['pages'] for c in json.loads(Path(args.references).read_text(encoding='utf-8'))['concepts']}
    out=[];dropped=0;kept=0
    with core.connect() as db:
        titles={r['title']:r['id'] for r in db.execute('SELECT id,title FROM books')}
        for c in data['concepts']:
            sources=[]
            for page in refs.get(c['id'],[]):
                title=BOOKS.get(page['bookId']);book=titles.get(title)
                if not book:continue
                # A history-of-Korean book is evidence only for historical concepts.
                if page['bookId']=='grammar-korean-language-history' and c.get('era')=='modern':dropped+=1;continue
                row=db.execute('SELECT id,text,printed_page FROM pages WHERE book_id=? AND pdf_page=?',(book,page['page'])).fetchone()
                if not row:dropped+=1;continue
                text=compact(row['text'])
                present=[t for t in page.get('matchedTerms',[]) if compact(t) in text]
                # Keep only pages where the concept's own terms are actually on the page.
                if len(present)<max(2,len(page.get('matchedTerms',[]))//2):dropped+=1;continue
                kept+=1
                sources.append({'book':title,'pdf_page':page['page'],'terms':present[:6],'status':'candidate','note':'용어 일치로 찾은 후보 쪽. 본문과 대조해 확정 필요.'})
            if not sources:
                # No candidate page survived; ask this library's own retrieval for pages that explain the label.
                for r in core.search_pages(c['label'],'문법','',3):
                    sources.append({'book':r['title'],'pdf_page':r['pdf_page'],'terms':r.get('matched',[]),'status':'candidate','note':'개념 이름으로 검색해 찾은 후보 쪽. 본문과 대조해 확정 필요.'})
            out.append({
                'id':c['id'],'label':c['label'],'parent':PARENTS.get(c['parent'],c['parent']),'era':c.get('era','modern'),
                'aliases':[t for t in c.get('terms',[]) if t!=c['label']],
                'summary':c['summary'],'explanation':c.get('explanation',[]),'steps':c.get('decisionSteps',[]),
                'examples':c.get('examples',[]),'counter_examples':c.get('counterExamples',[]),'common_errors':c.get('commonErrors',[]),
                'confused_with':c.get('confusedWith',[]),'standards':c.get('standards',[]),
                'sources':sources[:6],
                'review':{'status':'draft','origin':'kor-eduai-site 고등 문법 학습관 개념 사전','audience_note':'수능 학습자 대상 문장으로 작성됨. 교사·임용 관점의 어투와 예시로 검수 필요.','examples_note':'예와 반례의 출처는 고1~고3 모의고사 문항 번호임.'}
            })
    Path(args.out).parent.mkdir(exist_ok=True)
    Path(args.out).write_text(json.dumps({'area':'문법','schema':1,'note':'런타임 AI 없이 표시되는 개념 정리. 각 항목의 review.status가 reviewed가 될 때까지 초안임.','concepts':out},ensure_ascii=False,indent=1),encoding='utf-8')
    print(f'concepts={len(out)} sources kept={kept} dropped={dropped} -> {args.out}')

if __name__=='__main__':main()
