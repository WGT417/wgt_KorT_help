"""Validate the pre-written concept entries in concepts/*.json.

Checks shape, minimum content, unique ids and aliases, that every linked
concept exists, and that every cited book page exists in the library.
Exit code 1 on any error so it can run in the test suite.
"""
import sys,json,re
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core

REQUIRED=['id','label','parent','aliases','summary','explanation','steps','examples','counter_examples','common_errors','confused_with','sources','review']
MIN_EXPLANATION=400   # characters without spaces across all explanation paragraphs

def compact(t):return re.sub(r'\s+','',t)

def main():
    errors=[];warnings=[];entries=[];alias_owner={}
    for path in sorted((core.ROOT/'concepts').glob('*.json')):
        data=json.loads(path.read_text(encoding='utf-8'))
        if data.get('area') not in {'문식성','문법','문학'}:errors.append(f'{path.name}: area가 문식성·문법·문학 중 하나가 아님')
        for c in data.get('concepts',[]):
            c['_file']=path.name;entries.append(c)
    ids={c['id'] for c in entries}
    if len(ids)!=len(entries):errors.append('개념 id 중복')
    with core.connect() as db:
        titles={r['title']:r['id'] for r in db.execute('SELECT id,title FROM books')}
        for c in entries:
            where=f"{c['_file']} {c.get('id','?')}"
            for key in REQUIRED:
                if key not in c:errors.append(f'{where}: {key} 없음')
            if any(k not in c for k in REQUIRED):continue
            if len(compact(c['summary']))<40:errors.append(f'{where}: summary가 짧음')
            if len(compact(''.join(c['explanation'])))<MIN_EXPLANATION or len(c['explanation'])<3:errors.append(f'{where}: explanation이 3문단·공백 제외 {MIN_EXPLANATION}자보다 짧음')
            if len(c['steps'])<2:errors.append(f'{where}: steps가 2개보다 적음')
            if not c['examples']:errors.append(f'{where}: 예가 없음')
            for ex in c['examples']+c['counter_examples']:
                if not all(ex.get(k,'').strip() for k in ('case','verdict','why','source')):errors.append(f'{where}: 예·반례의 사례·판정·이유·출처가 비었음')
            if len(c['common_errors'])<1:errors.append(f'{where}: common_errors가 없음')
            for linked in c['confused_with']:
                if linked not in ids:errors.append(f'{where}: 없는 confused_with {linked}')
            for alias in [c['label']]+c['aliases']:
                key=compact(alias).lower()
                # Shared aliases are allowed (the matcher shows both); report them so authors can tighten.
                if key in alias_owner and alias_owner[key]!=c['id']:warnings.append(f'{where}: 별칭 "{alias}"이 {alias_owner[key]}와 겹침')
                alias_owner.setdefault(key,c['id'])
            if not c['sources']:errors.append(f'{where}: 개론서 근거가 없음')
            for s in c['sources']:
                book=titles.get(s.get('book'))
                if not book:errors.append(f'{where}: 서재에 없는 책 {s.get("book")}');continue
                row=db.execute('SELECT id FROM pages WHERE book_id=? AND pdf_page=?',(book,int(s.get('pdf_page',0)))).fetchone()
                if not row:errors.append(f'{where}: {s["book"]} 자료 {s.get("pdf_page")}페이지가 없음')
                if s.get('status') not in {'verified','candidate'}:errors.append(f'{where}: 근거 status는 verified 또는 candidate여야 함')
            if c['review'].get('status') not in {'draft','reviewed'}:errors.append(f'{where}: review.status는 draft 또는 reviewed여야 함')
    for w in warnings:print(' (참고)',w)
    if errors:
        print('개념 사전 검사 실패');[print(' -',e) for e in errors];sys.exit(1)
    by_area={}
    for c in entries:by_area[c['_file']]=by_area.get(c['_file'],0)+1
    print(f'개념 {len(entries)}개 · 검수 완료 {sum(c["review"].get("status")=="reviewed" for c in entries)}개 · 파일별 {by_area}')
    print(f'근거 쪽 {sum(len(c["sources"]) for c in entries)}곳 · 대조 완료 {sum(s.get("status")=="verified" for c in entries for s in c["sources"])}곳')

if __name__=='__main__':main()
