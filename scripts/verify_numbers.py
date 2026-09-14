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
    print('Confirmed printed numbers:',db.execute("SELECT COUNT(*) FROM pages WHERE number_status!='unverified'").fetchone()[0])
