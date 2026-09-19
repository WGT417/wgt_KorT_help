"""Whole-library check of what the 찾아보기 cards and source cards show.

1. Term index: how many terms have a defining sentence, how many were found
   away from the index pages, how many carry visible OCR damage.
2. Concept benchmark: for each of the concept entries (concepts/*.json) whose
   name is an indexed term, does its card show a definition from a page a
   person verified (±1)?
3. Screen text: the source-card excerpts for every concept name, counted by
   the kinds of OCR damage still visible after display cleanup.
4. Display cleanup over every body and note paragraph: footnote marks and the
   books' own cross-reference marks dropped, the sentence periods and commas
   those marks took with them read back, misread terms corrected, heading lines
   set apart; and how many card definitions carry the sentences that follow them.

Result: data/term-card-audit.json. Precision of the definition rules was
judged by reading samples; see README (찾아보기 용어 사전).

  python scripts/audit_term_cards.py
"""
import sys,re,json,time,collections
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core
from concepts import all_concepts
from retrieval import ALIASES
from term_index import match_terms
from text_pipeline import VERSION,note_marks,callout_marks,tidy_display,split_heading,restore_terms
from passage_text import noise,ocr_damage

def key_of(term):return re.sub(r'[\s\-‘’\'"·]','',term).lower()

def main():
    start=time.time();report={'generated':time.strftime('%Y-%m-%d %H:%M'),'text_version':VERSION}
    terms=json.loads((core.DATA/'term-index.json').read_text(encoding='utf-8'))['terms']
    sources=[s for e in terms.values() for s in e['sources']]
    report['index']={'definitions_with_following_sentences':sum(bool(s.get('more')) for s in sources),'terms':len(terms),'terms_with_definition':sum(any(s['quote'] for s in e['sources']) for e in terms.values()),
        'index_pages':sum(s.get('indexed',True) for s in sources),'definitions':sum(bool(s['quote']) for s in sources),
        'definitions_away_from_index':sum(bool(s['quote']) and not s.get('indexed',True) for s in sources),
        'definitions_with_ocr_damage':sum(bool(s.get('ocr')) for s in sources)}
    bench=collections.Counter();lists=collections.defaultdict(list);screen=collections.Counter();damaged=[];cards=0
    for c in all_concepts():
        name=re.sub(r'\(.*?\)','',c['label'].split(':')[0]).strip()
        query=name if len(name)<=20 else c.get('aliases',[name])[0]
        keys=[k for k in dict.fromkeys(key_of(n) for n in [name,*c.get('aliases',[])]) if k in terms]
        gold={(s['book'],int(s['pdf_page'])) for s in c.get('sources',[]) if s.get('status')=='verified'}
        if not keys:state='not in index'
        else:
            found=[s for k in keys for g in [next((g for g in ALIASES if k in g),(k,))] for kk in g if kk in terms for s in terms[kk]['sources'] if s['quote']]
            state='definition from a verified page' if any(s['book']==b and abs(s['pdf_page']-p)<=1 for s in found for b,p in gold) else 'definition from another page' if found else 'no definition'
        bench[state]+=1;lists[state].append(c['label'])
        for s in core.search_pages(query,c['area']):
            cards+=1;text=s['display_excerpt']
            kinds=sorted(set(ocr_damage(text)+(['noise'] if noise(text) else [])))
            for k in kinds:screen[k]+=1
            if kinds:damaged.append({'query':query,'book':s['title'],'pdf_page':s['pdf_page'],'kinds':kinds,'text':text[:200]})
    report['concept_benchmark']={'counts':dict(bench),'no_definition':lists['no definition'],'not_in_index':lists['not in index']}
    report['screen']={'queries':sum(bench.values()),'source_cards':cards,'cards_with_visible_damage':len(damaged),'kinds':dict(screen),'examples':damaged[:60]}
    dropped=commas=periods=misread=headings=callouts=0
    with core.connect() as db:
        for r in db.execute("SELECT x.raw,x.display,x.kind FROM passages x JOIN pages p ON p.id=x.page_id JOIN books b ON b.id=p.book_id WHERE x.version=? AND x.kind IN ('body','note') AND b.category!='참고자료'",(VERSION,)):
            marks=note_marks(r['raw']);cross=len(callout_marks(r['raw']))
            for _,_,replacement in marks:
                if replacement=='.':periods+=1
                elif replacement:commas+=1
                else:dropped+=1
            # note_marks carries the cross-reference marks; count them apart.
            callouts+=cross;dropped-=cross
            display=restore_terms(r['display'])
            # tidy_display leaves a paragraph whose spacing does not map to the source untouched.
            if re.sub(r'\s','',r['raw'])==re.sub(r'\s','',display):misread+=tidy_display(r['raw'],display)[1]-len(marks)
            if r['kind']=='body' and split_heading(r['raw'],display)[0]:headings+=1
    report['display_cleanup']={'footnote_marks_dropped':dropped,'cross_reference_marks_dropped':callouts,'sentence_periods_restored':periods,'commas_restored':commas,'misread_terms_corrected':misread,'headings_set_apart':headings}
    report['seconds']=round(time.time()-start)
    (core.DATA/'term-card-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=1),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='screen'},ensure_ascii=False,indent=1))
    print(json.dumps({k:v for k,v in report['screen'].items() if k!='examples'},ensure_ascii=False))

if __name__=='__main__':main()
