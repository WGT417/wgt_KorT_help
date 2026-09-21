"""The topic map the books themselves draw: their headings, and whether a
concept entry covers each one.

The back-of-book indexes miss three 문학 books entirely (고전산문교육론 5 entries,
한국문학강의 6, 교과서 시 정본 해설 1), and an index lists words rather than
topics. A book's own headings are the other list: the authors' agreement on what
this field is made of. `text_pipeline.split_heading` already separates the
heading line the layout joined to the paragraph below it, and `layout_passages`
marks short lines that begin a block; both are reused here.

A heading counts as covered when a concept entry of that area is an exact match
for it (concepts.match_concepts), so the output is the list of topics the books
teach and the app cannot yet open a card for.

  python scripts/topic_map.py 문학            # one area
  python scripts/topic_map.py 문학 --book 시론  # one book
  python scripts/topic_map.py --all           # every area, summary only

Writes data/topic-map.json.
"""
import sys,re,json,argparse,collections,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core
import concepts as C
from text_pipeline import VERSION,split_heading,restore_terms,correct_display,tidy_display

# A heading is a short line that names a topic. Numbered section heads ("2.1.
# 자음", "제3장 시의 언어") are the reliable ones; the rest have to look like a
# title rather than a sentence.
NUMBER=re.compile(r'^\s*(?:제\s*\d+\s*[장절부편]|\d+(?:\.\d+)*\.?|[IVXivx]+\.|[①-⑳]|[가-하]\.|\(\d+\))\s*(.+)$')
# The book's own furniture, tolerant of the scan: 참고문헌 comes out 참고 문언,
# 잠 고문헌, 침 고문헌, so the compacted line is tested for a two-syllable core.
FURNITURE=re.compile(r'찾아보|고문헌|참고문|차례|목차|부록|판권|지은이|저자소개|미주|일러두|머리말|서문|발간사|연습문제|학습활동|참고자료|출판|역락|사회평론|집문당')
# Words that make a line a sentence, not a title.
SENTENCE=re.compile(r'[다요][.!?]|[은는이가을를]\s|하였|한다|이다|있다|없다')
from text_pipeline import SURNAMES,strange_ratio
PERSON=re.compile(r'^['+SURNAMES+r'][가-힣]{1,2}$')
PART=re.compile(r'^\s*[•·\|lI]*\s*\d*\s*\d*\s*부\b|^\s*제?\s*\d+\s*부')

ONLY_NUMBER=re.compile(r'^[\s\d.·\-—()]*(?:제?\s*\d+\s*[장절부편항]?)?[\s\d.·\-—()]*$')
READING=re.compile(r'^(?:작품\s*읽기|더\s*읽기|읽기\s*자료|감상|중략|전략|후략|양주동|해독)')
# A quoted line of a poem or a work title is not a topic: 시행은 /로 갈라 적고,
# 작품 제목은 「」·『』로 묶는다. 차례 줄은 제목 사이에 쪽 번호가 끼어 있다.
QUOTED_LINE=re.compile(r'/|[「」『』〈〉]|[가-힣]\s*\d{1,3}\s+\d')
# A line from the table of contents carries the page it points at ("제1장 바리공주
# _61", "눈물. 384"); a title page carries who made the book; 교과서 시 정본 해설
# separates a poem from its poet with a bar ("진달래꽃 | 김소월").
CONTENTS=re.compile(r'[_.]\s*\d{1,3}\s*$|\d{2,3}\s*$|\|')
MADE_BY=re.compile(r'지음|옮김|엮음|편저|일동|편역|해제했다|개정판')

def topic_of(line,book=''):
    """The topic a heading names, or '' when the line is not a heading."""
    line=re.sub(r'\s+',' ',line).strip(' .·­-—•|lI')
    if not line:return ''
    flat=re.sub(r'\s','',line)
    if FURNITURE.search(flat):return ''
    if PART.match(line):return ''                      # 부 제목은 너무 굵어 주제가 아니다
    if ONLY_NUMBER.fullmatch(line) or READING.match(line.lstrip('( ')):return ''
    if QUOTED_LINE.search(line) or CONTENTS.search(line) or MADE_BY.search(flat):return ''
    # A running head repeats the book's own title.
    title=re.sub(r'\s','',book)
    if title and len(flat)>=4 and (flat in title or title in flat):return ''
    m=NUMBER.match(line)
    body=(m.group(1) if m else line).strip(' .·­-—()')
    if not 3<=len(body)<=40:return ''
    if not m and (SENTENCE.search(body) or len(body)>26):return ''
    if PERSON.fullmatch(body.replace(' ','')):return ''  # 작가 이름은 개념이 아니다
    # A title ends in a noun; a broken line ends in a particle or an ending.
    if re.search(r'[가-힣](?:고|며|서|면|은|는|을|를|의|에|와|과|도|만|나|랑)$',body) and not m:return ''
    if len(re.findall(r'[가-힣]',body))<len(re.sub(r'\s','',body))*.5:return ''
    # A heading the scan mangled ("쩌12잠", "I 햄문햄의") is not a topic.
    if strange_ratio(body)>.5:return ''
    return body

def headings(area,book=None):
    """(book, pdf_page, topic) for every heading line in the area's books."""
    where="b.category=?";args=[area]
    if book:where+=" AND b.title=?";args.append(book)
    out=[]
    with core.connect() as db:
        rows=db.execute(f"""SELECT x.raw,x.display,x.kind,p.pdf_page,b.title FROM passages x
          JOIN pages p ON p.id=x.page_id JOIN books b ON b.id=p.book_id
          WHERE x.version=? AND {where} AND x.kind IN ('body','fragment','note')""",[VERSION]+args).fetchall()
    for r in rows:
        display=restore_terms(r['display'])
        lines=[]
        if r['kind']=='fragment':lines=[display]
        else:
            head=split_heading(r['raw'],display)[0]
            if head:lines=[head]
        for line in lines:
            topic=topic_of(correct_display(line)[0],r['title'])
            if topic:out.append((r['title'],r['pdf_page'],topic))
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument('area',nargs='?');ap.add_argument('--book');ap.add_argument('--all',action='store_true')
    ap.add_argument('--min',type=int,default=1,help='이 횟수 이상 나온 제목만 본다')
    ap.add_argument('--show',type=int,default=25,help='책마다 화면에 보일 제목 수')
    args=ap.parse_args()
    areas=['문식성','문법','문학'] if args.all or not args.area else [args.area]
    report={'generated':time.strftime('%Y-%m-%d %H:%M'),'areas':{}}
    for area in areas:
        rows=headings(area,args.book)
        # A line printed at the top of many pages of one book is a running head,
        # not a heading: "시와 함께 배우는 시론" 150 times in one book.
        per_book=collections.Counter((b,t) for b,_,t in rows)
        running={t for (b,t),n in per_book.items() if n>=8}
        rows=[r for r in rows if r[2] not in running]
        counts=collections.Counter(t for _,_,t in rows)
        where=collections.defaultdict(list)
        for b,p,t in rows:where[t].append((b,p))
        covered=[];missing=[]
        for topic,n in counts.most_common():
            if n<args.min:continue
            hit=[h['label'] for h in C.match_concepts(topic,area) if h['match']=='exact']
            (covered if hit else missing).append({'topic':topic,'count':n,'concept':hit[0] if hit else None,
                                                  'where':[{'book':b,'pdf_page':p} for b,p in where[topic][:4]]})
        report['areas'][area]={'headings':len(rows),'distinct':len(counts),
                               'checked':len(covered)+len(missing),'covered':len(covered),'missing':len(missing),
                               'missing_topics':missing,'covered_topics':covered[:80]}
        print(f'{area}: 제목 {len(rows)}줄 · 서로 다른 제목 {len(counts)}개 · {args.min}회 이상 {len(covered)+len(missing)}개 '
              f'(카드 있음 {len(covered)} / 없음 {len(missing)})')
        if not args.all:
            # In page order, book by book: that is the table of contents.
            by_book=collections.defaultdict(list)
            for m in covered+missing:
                spot=m['where'][0];by_book[spot['book']].append((spot['pdf_page'],m))
            for book in sorted(by_book,key=lambda b:-len(by_book[b])):
                items=sorted(by_book[book],key=lambda x:x[0])
                gap=sum(1 for _,m in items if not m['concept'])
                print(f"\n== {book} — 제목 {len(items)}개, 카드 없음 {gap}개")
                for page,m in items[:args.show]:
                    mark='  ' if m['concept'] else '->'
                    print(f"   {mark} {page:4d}쪽  {m['topic'][:38]:38s} {m['concept'] or ''}")
    (core.DATA/'topic-map.json').write_text(json.dumps(report,ensure_ascii=False,indent=1),encoding='utf-8')
    print('data/topic-map.json')

if __name__=='__main__':main()
