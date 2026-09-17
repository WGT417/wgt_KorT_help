from pathlib import Path
import sys, sqlite3, re, json, hashlib, time, math

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / '.runtime'))
import pymupdf
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
DB = DATA / 'library.sqlite3'

def connect():
    db = sqlite3.connect(DB, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    return db

def init_db():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS books(id TEXT PRIMARY KEY,title TEXT,category TEXT,path TEXT,pages INTEGER,processed INTEGER DEFAULT 0,status TEXT DEFAULT 'pending',sha256 TEXT);
        CREATE TABLE IF NOT EXISTS pages(id INTEGER PRIMARY KEY,book_id TEXT,pdf_page INTEGER,text TEXT,method TEXT,quality TEXT,printed_page INTEGER,candidate INTEGER,number_status TEXT DEFAULT 'unverified',compact TEXT, UNIQUE(book_id,pdf_page));
        CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(text,compact,content='pages',content_rowid='id',tokenize='trigram');
        CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT);
        ''')
        if 'compact' not in {r[1] for r in db.execute('PRAGMA table_info(pages)')}:
            db.execute('ALTER TABLE pages ADD COLUMN compact TEXT')
        db.create_function('compact_text',1,normalized)
        db.execute('UPDATE pages SET compact=compact_text(text) WHERE compact IS NULL')

def normalized(text):
    return re.sub(r'\s+', '', text).lower()

def page_number(page):
    candidates=[]
    for word in page.get_text('words'):
        x0,y0,x1,y1,txt,*_=word
        if re.fullmatch(r'\d{1,4}',txt) and (y0>page.rect.height*.90 or y1<page.rect.height*.09):
            n=int(txt)
            if 0<n<3000: candidates.append(n)
    candidates=list(set(candidates))
    return candidates[0] if len(candidates)==1 else footer_number(page.get_text(sort=True))

def footer_number(text):
    lines=[s.strip() for s in text.splitlines() if s.strip()]
    for line in reversed(lines[-2:]):
        match=re.fullmatch(r'(\d{1,4})(?:\s+[^\d].*)?',line)
        if not match:match=re.fullmatch(r'.*[가-힣]\s+(\d{1,4})',line)
        if match and 0<int(match[1])<3000:return int(match[1])
    return None

def ocr_page(page,dpi=300):
    """Tesseract text plus line geometry so passages can be laid out like embedded text."""
    from text_pipeline import page_lines
    tp=page.get_textpage_ocr(language='kor+eng',dpi=dpi,full=True,tessdata=str(DATA/'tessdata'))
    return page.get_text(textpage=tp,sort=True),page_lines(page,textpage=tp)

def quality(text):
    letters=len(re.findall(r'[가-힣A-Za-z0-9]',text))
    if letters<30: return 'sparse'
    if text.count('\ufffd')>max(3,len(text)*.01): return 'review'
    return 'extracted'

def index_library():
    init_db()
    paths=sorted((ROOT/'개론서 파일').rglob('*.pdf'),key=lambda p:(p.parent.name!='문식성',p.name))
    with connect() as db:
        for path in paths:
            bid=hashlib.sha256(str(path.relative_to(ROOT)).encode()).hexdigest()[:16]
            with pymupdf.open(path) as doc:
                db.execute('INSERT OR IGNORE INTO books(id,title,category,path,pages) VALUES(?,?,?,?,?)',(bid,path.stem.replace(' OCR',''),path.parent.name,str(path.relative_to(ROOT)),len(doc)))
        db.execute("INSERT OR REPLACE INTO state VALUES('indexing','running')")
    for path in paths:
        bid=hashlib.sha256(str(path.relative_to(ROOT)).encode()).hexdigest()[:16]
        with connect() as db:
            book=db.execute('SELECT * FROM books WHERE id=?',(bid,)).fetchone()
            if book['status']=='ready': continue
            db.execute("UPDATE books SET status='indexing' WHERE id=?",(bid,))
        print('Indexing:',path.stem,flush=True)
        out=DATA/'text'/bid
        out.mkdir(parents=True,exist_ok=True)
        with pymupdf.open(path) as doc:
            for i in range(book['processed'],len(doc)):
                page=doc[i]
                txt=page.get_text(sort=True)
                candidate=page_number(page)
                record={'book_id':bid,'pdf_page':i+1,'text':txt,'method':'embedded','quality':quality(txt),'candidate':candidate}
                (out/f'{i+1:04}.json').write_text(json.dumps(record,ensure_ascii=False),encoding='utf-8')
                with connect() as db:
                    cursor=db.execute('INSERT INTO pages(book_id,pdf_page,text,method,quality,candidate,compact) VALUES(?,?,?,?,?,?,?)',(bid,i+1,txt,'embedded',quality(txt),candidate,normalized(txt)))
                    db.execute('INSERT INTO search(rowid,text,compact) VALUES(?,?,?)',(cursor.lastrowid,txt,normalized(txt)))
                    db.execute('UPDATE books SET processed=? WHERE id=?',(i+1,bid))
            # Accept a directly observed number only with agreement on both neighboring pages.
            with connect() as db:
                rows=db.execute('SELECT id,pdf_page,candidate FROM pages WHERE book_id=? ORDER BY pdf_page',(bid,)).fetchall()
                by={r['pdf_page']:r['candidate'] for r in rows}
                for r in rows:
                    n=r['candidate']; p=r['pdf_page']
                    if n and by.get(p-1)==n-1 and by.get(p+1)==n+1:
                        db.execute("UPDATE pages SET printed_page=?,number_status='sequence' WHERE id=? AND number_status!='manual'",(n,r['id']))
        with open(path,'rb') as stream: digest=hashlib.file_digest(stream,'sha256').hexdigest()
        with connect() as db: db.execute("UPDATE books SET status='ready',sha256=? WHERE id=?",(digest,bid))
    with connect() as db: db.execute("INSERT OR REPLACE INTO state VALUES('indexing','complete')")

from retrieval import terms as query_terms, retrieve

def search_pages(query,category='전체',book_id='',limit=8):
    with connect() as db:
        return retrieve(db,query,category,book_id,limit)

def route_question(mode):
    """The visitor chooses outright; nothing here guesses at the question."""
    if mode=='reason':return True,'AI 활용 해설입니다. 찾은 원문을 근거로 설명합니다.'
    return False,'원문 검색입니다. OpenAI API를 호출하지 않습니다.'

