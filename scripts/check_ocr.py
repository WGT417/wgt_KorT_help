import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import *
b=connect().execute('SELECT * FROM books WHERE title=?',('독서교육론 사회평론',)).fetchone()
with pymupdf.open(ROOT/b['path']) as doc:
    doc[70].get_pixmap(matrix=pymupdf.Matrix(1.4,1.4)).save(str(DATA/'sample-reading.png'))
    page=doc[70]
    tp=page.get_textpage_ocr(language='kor+eng',dpi=200,full=True,tessdata=str(DATA/'tessdata'))
    print(page.get_text(textpage=tp)[:500])
