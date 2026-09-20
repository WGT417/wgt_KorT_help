"""Accept directly read footer numbers only when consecutive neighbors agree."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import *
init_db()
with connect() as db:
    for book in db.execute('SELECT id FROM books').fetchall():
        rows=[dict(r) for r in db.execute('SELECT * FROM pages WHERE book_id=? ORDER BY pdf_page',(book['id'],))]
        candidates={r['pdf_page']:footer_number(r['text']) or r['candidate'] for r in rows}
        for r in rows:
            p=r['pdf_page'];n=candidates[p]
            if r['number_status']=='unverified' and n and candidates.get(p-1)==n-1 and candidates.get(p+1)==n+1:
                db.execute("UPDATE pages SET printed_page=?,candidate=?,number_status='sequence' WHERE id=?",(n,n,r['id']))
    # A page whose own footer number cannot be read still sits between two pages
    # whose numbers were confirmed, and a book numbers its pages consecutively, so
    # the page number follows from the offset those two share. Only the gap
    # BETWEEN two confirmed pages is filled: past the first or the last of them the
    # front matter numbers differently, and nothing says where that stops.
    # Checked against every readable footer number inside such a gap: 1,581 agree,
    # and the 142 that do not are damaged numbers (130 read as 13, 141 as 1) or not
    # page numbers at all (a year, a 차례 entry). No gap holds three pages agreeing
    # on some other offset, which is what a real change of numbering would look like.
    filled=0
    for book in db.execute('SELECT id,title FROM books').fetchall():
        confirmed=db.execute("""SELECT pdf_page,printed_page FROM pages
          WHERE book_id=? AND printed_page IS NOT NULL ORDER BY pdf_page""",(book['id'],)).fetchall()
        for (p1,n1),(p2,n2) in zip(confirmed,confirmed[1:]):
            if p1-n1!=p2-n2:continue
            for page in range(p1+1,p2):
                filled+=db.execute("""UPDATE pages SET printed_page=?,number_status='offset'
                  WHERE book_id=? AND pdf_page=? AND number_status='unverified'""",
                  (page-(p1-n1),book['id'],page)).rowcount
    print('Filled from the offset of the confirmed pages around them:',filled)
    print('Confirmed printed numbers:',db.execute("SELECT COUNT(*) FROM pages WHERE number_status!='unverified'").fetchone()[0])
