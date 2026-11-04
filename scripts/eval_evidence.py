"""Do the pages an AI 해설 is written from reach the model?

Runs the 해설's evidence step for the questions in eval_questions.json the way
/api/ask and generate() do (search, the concept entries and index terms the
question names, collect_evidence, evidence_packet) without calling a model: the
search plan the model would write is replaced by an empty one, so the numbers
measure what the library finds by itself. Gold pages are the verified sources of
the concept each question is about; a page or its neighbour counts. Because the
concept entries also feed the evidence, read 'gold pages' with --no-concepts for
what search (and the index terms' pages are left out too) finds alone. No OpenAI cost.

2026-11-04, c5b97de → the quoted-example search, the empty-search path, the index
pages, the book cap and the page before: questions whose search found nothing, so
that the server wrote no 해설, 5/24 → 0/24; gold pages of the questions answered
about 60% → 70%; pages 16.3 → 26.1 and books 2.5 → 3.0 a question; the largest
book's share 59% → 57%.

  python scripts/eval_evidence.py
  python scripts/eval_evidence.py --no-concepts
"""
import sys,json,argparse
from collections import Counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from concepts import all_concepts
import explanation
from server import question_context

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--no-concepts',action='store_true');args=parser.parse_args()
    questions=json.loads((Path(__file__).parent/'eval_questions.json').read_text(encoding='utf-8'))['questions']
    entries={c['id']:c for c in all_concepts()}
    no_plan=lambda *a,**k:{'queries':[]}
    total=Counter()
    for question,(category,cid) in questions.items():
        initial,terms,concepts=question_context(question,category)
        if args.no_concepts:terms,concepts=[],[]
        gold={(s['book'],int(s['pdf_page'])) for s in entries[cid]['sources'] if s.get('status')=='verified'}
        # As /api/ask and generate() run it; the server writes nothing when this step finds nothing.
        selected=[s for s in explanation.collect_evidence(question,category,initial,no_plan,'',concepts,terms) if s.get('id')]
        have={(s['title'],s['pdf_page']) for s in selected}
        recall=sum(any(t==b and abs(p-g)<=1 for t,p in have) for b,g in gold)/len(gold)
        books={b for b,_ in gold};covered=len(books&{t for t,_ in have})/len(books)
        packet,_=explanation.evidence_packet(selected,concepts)
        chars=len(json.dumps(packet,ensure_ascii=False))
        spread=Counter(s['title'] for s in selected)
        share=max(spread.values())/len(selected) if selected else 0
        total.update(nosearch=not initial,zero=not selected,recall=recall,books=covered,pages=len(selected),nbooks=len(spread),chars=chars,share=share)
        print(f"{category:4} search {len(initial)} pages {len(selected):2} books {len(spread)} top-book {share:4.0%} "
              f"gold {recall:4.0%} gold-books {covered:4.0%} chars {chars:6}  {question[:40]}")
    n=len(questions)
    print(f"\nno search hits {total['nosearch']}/{n} | no evidence {total['zero']}/{n} | gold pages {total['recall']/n:.0%} | gold books {total['books']/n:.0%} | "
          f"pages/q {total['pages']/n:.1f} | books/q {total['nbooks']/n:.1f} | top book share {total['share']/n:.0%} | packet chars/q {total['chars']//n}")

if __name__=='__main__':main()
