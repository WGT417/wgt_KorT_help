from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import os, json, re, threading, secrets, mimetypes, time, subprocess
from core import ROOT, DATA, connect, init_db, search_pages, route_question, pymupdf, normalized, quality, ocr_page
from explanation import collect_evidence, prompt_for, validate, ANSWER_SCHEMA,MODEL_ANSWER_SCHEMA,evidence_packet,resolve_evidence
import quota

# PUBLIC=1 is set in the Dockerfile: bind all interfaces, trust the platform's
# routing instead of the localhost Host check, count AI usage in Firestore,
# and refuse the local key-saving endpoint. Everything else stays the
# desktop behaviour so start.cmd keeps working unchanged.
PUBLIC=os.environ.get('PUBLIC','')=='1'
PORT=int(os.environ.get('PORT','8765'))
HOST=os.environ.get('HOST','0.0.0.0' if PUBLIC else '127.0.0.1')
ADMIN_TOKEN=os.environ.get('ADMIN_TOKEN','')
ALLOWED_HOSTS={h.strip() for h in os.environ.get('ALLOWED_HOSTS','').split(',') if h.strip()}
if not PUBLIC:
    for line in (ROOT/'.env').read_text(encoding='utf-8').splitlines() if (ROOT/'.env').exists() else []:
        if '=' in line and not line.lstrip().startswith('#'):
            name,value=line.split('=',1)
            if name.strip() == 'OPENAI_API_KEY':os.environ.setdefault(name.strip(),value.strip().strip('"').strip("'"))
API_KEY=os.environ.get('OPENAI_API_KEY','')
MODEL='gpt-5.6-luna'
CSRF=secrets.token_urlsafe(32)
AI_LOCK=threading.Lock()
OCR_LOCK=threading.Lock()
init_db()
QUOTA_BACKEND=os.environ.get('QUOTA_BACKEND','firestore' if PUBLIC else 'none')
try:QUOTA=quota.make(QUOTA_BACKEND)
except Exception as error:
    # Fail closed: keep the site up for search, but never generate without counting.
    print(f'quota backend unavailable ({QUOTA_BACKEND}): {error}',flush=True);QUOTA=None

def save_api_key(key):
    path=ROOT/'.env'
    lines=path.read_text(encoding='utf-8').splitlines() if path.exists() else []
    lines=[line for line in lines if line.split('=',1)[0].strip()!='OPENAI_API_KEY']
    if key:lines.append('OPENAI_API_KEY='+key)
    temporary=ROOT/'.env.tmp'
    try:
        temporary.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        restrict_secret_file(temporary)
        temporary.replace(path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise

def restrict_secret_file(path):
    if os.name=='nt':
        account='\\'.join(filter(None,(os.environ.get('USERDOMAIN'),os.environ.get('USERNAME'))))
        if not account:raise OSError('현재 Windows 계정을 확인할 수 없습니다.')
        try:subprocess.run(['icacls',str(path),'/inheritance:r','/grant:r',f'{account}:(F)','*S-1-5-18:(F)','*S-1-5-32-544:(F)'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        except (OSError,subprocess.SubprocessError) as error:raise OSError('키 파일 권한을 제한할 수 없습니다.') from error
    else:os.chmod(path,0o600)

def openai_call(prompt,key,*,schema=None,max_tokens=16000):
    format={'type':'json_schema','name':'library_response','schema':schema,'strict':True} if schema else {'type':'json_object'}
    payload={'model':MODEL,'input':prompt,'reasoning':{'effort':'medium'},'max_output_tokens':max_tokens,'text':{'format':format},'store':False}
    request=Request('https://api.openai.com/v1/responses',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Authorization':f'Bearer {key}'},method='POST')
    try:
        with urlopen(request,timeout=180) as response: result=json.load(response)
    except HTTPError as error:
        code=error.code
        raise ValueError({400:'모델 또는 요청 설정을 확인해 주세요.',401:'OpenAI API 키 인증에 실패했습니다.',403:'OpenAI API 키의 사용 권한을 확인해 주세요.',404:'GPT-5.6 Luna 모델 접근 권한을 확인해 주세요.',429:'OpenAI API 잔액 또는 요청 한도를 확인해 주세요.'}.get(code,'OpenAI API가 응답하지 못했습니다. 잠시 후 다시 시도해 주세요.')) from None
    except (URLError,TimeoutError):raise ValueError('OpenAI 연결 시간이 초과되었거나 네트워크에 연결할 수 없습니다.') from None
    except ValueError:raise ValueError('OpenAI 응답을 읽을 수 없습니다. 잠시 후 다시 시도해 주세요.') from None
    try:
        if result.get('status')!='completed':raise ValueError('incomplete response')
        raw=''.join(part['text'] for item in result['output'] if item.get('type')=='message' for part in item.get('content',[]) if part.get('type')=='output_text')
        return json.loads(raw)
    except (KeyError,IndexError,ValueError,TypeError,AttributeError):raise ValueError('OpenAI 해설을 완성하지 못했거나 응답 형식이 올바르지 않습니다. 원문 검색 결과를 확인해 주세요.') from None

def reason(query,sources):
    packet,registry=evidence_packet(sources)
    answer=openai_call(prompt_for(query,sources,packet),API_KEY,schema=MODEL_ANSWER_SCHEMA)
    return validate(resolve_evidence(answer,registry),sources)

# Firebase Hosting cuts a proxied request at 60s, and an AI 해설 often takes
# 45–70s. The answer is generated in a thread; a request waits at most AI_WAIT
# and otherwise hands back a job id the page asks for again. Jobs live in this
# process, which is enough because deploy.json runs one instance.
AI_WAIT=48
AI_JOBS={};JOBS_LOCK=threading.Lock()

def refund_quota(admin):
    if admin or QUOTA is None:return
    try:QUOTA.refund(quota.today())
    except Exception as error:print(f'quota refund error: {error}',flush=True)

def strip_sources(result):
    for source in result['sources']:
        source.pop('text',None);source.pop('evidence_text',None)
    return result

def generate(job,query,category,state,admin):
    result=job['result']
    try:
        sources=collect_evidence(query,category,result['sources'],openai_call,API_KEY)
        result['sources']=sources
        result['answer']=reason(query,sources);result['ai_used']=True
    except Exception as error:
        if not isinstance(error,ValueError):print(f'AI 해설 실패: {error!r}',flush=True)
        result['notice']=str(error) if isinstance(error,ValueError) else '해설을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.'
        refund_quota(admin)
        if 'remaining' in state:state['remaining']+=1
    finally:
        AI_LOCK.release();strip_sources(result);job['done'].set()

def start_job(result,query,category,state,admin):
    job={'done':threading.Event(),'result':result,'question':query,'quota':state,'at':time.monotonic()}
    job_id=secrets.token_urlsafe(18)
    with JOBS_LOCK:
        for old in [k for k,j in AI_JOBS.items() if time.monotonic()-j['at']>1800]:del AI_JOBS[old]
        AI_JOBS[job_id]=job
    threading.Thread(target=generate,args=(job,query,category,state,admin),daemon=True).start()
    return job_id

def wait_job(job_id,job,deadline):
    if job['done'].wait(max(1.0,deadline-time.monotonic())):return job['result']
    return {'question':job['question'],'pending':job_id,'quota':job['quota']}

class Handler(BaseHTTPRequestHandler):
    server_version='LocalLibrary'
    def log_message(self,*args):pass
    def send(self,status,body,kind='application/json; charset=utf-8'):
        if isinstance(body,(dict,list)):body=json.dumps(body,ensure_ascii=False).encode()
        if isinstance(body,str):body=body.encode()
        self.send_response(status)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(body)))
        self.headers_safe()
        self.end_headers();self.wfile.write(body)
    def is_admin(self):
        return bool(ADMIN_TOKEN) and secrets.compare_digest(self.headers.get('X-Admin-Token',''),ADMIN_TOKEN)
    def quota_state(self,consume=False):
        """Return the quota dict for the response; (allowed, state) when consuming.

        The pool is one shared day's budget for the whole server, so the request
        itself tells us nothing: no cookie, no IP, no per-person share.
        """
        if self.is_admin():return (True,{'admin':True}) if consume else {'admin':True}
        if QUOTA is None:return (False,{'unavailable':True}) if consume else {'unavailable':True}
        if QUOTA.name=='none':return (True,{'unlimited':True}) if consume else {'unlimited':True}
        try:
            if consume:
                ok,remaining=QUOTA.consume(quota.today())
                return ok,{'limit':quota.LIMIT,'remaining':remaining}
            return {'limit':quota.LIMIT,'remaining':QUOTA.peek(quota.today())}
        except Exception as error:
            print(f'quota error: {error}',flush=True)
            return (False,{'unavailable':True}) if consume else {'unavailable':True}
    def headers_safe(self):
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('X-Frame-Options','SAMEORIGIN')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; object-src 'self'; frame-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'")
    def host_ok(self):
        if PUBLIC:return True  # Cloud Run / Firebase Hosting only route our own hostnames here
        return self.headers.get('Host') in {f'localhost:{PORT}',f'127.0.0.1:{PORT}'}
    def origin_ok(self):
        origin=self.headers.get('Origin','')
        if not PUBLIC:return origin in {f'http://localhost:{PORT}',f'http://127.0.0.1:{PORT}'}
        if self.headers.get('Sec-Fetch-Site')=='same-origin':return True
        parts=urlsplit(origin)
        if parts.scheme!='https' or not parts.netloc:return False
        forwarded={h.strip() for h in self.headers.get('X-Forwarded-Host','').split(',') if h.strip()}
        return parts.netloc in ({self.headers.get('Host','')}|forwarded|ALLOWED_HOSTS)
    def do_GET(self):
        if not self.host_ok():return self.send(403,{'error':'로컬 주소로 접속해 주세요.'})
        path=urlsplit(self.path).path
        try:
            if path=='/api/status':
                with connect() as db:
                    books=[dict(r) for r in db.execute("SELECT id,title,category,pages,processed,status FROM books WHERE category!='참고자료' ORDER BY category,title")]
                    counts=dict(db.execute('SELECT quality,COUNT(*) FROM pages GROUP BY quality').fetchall())
                    verified=db.execute("SELECT COUNT(*) FROM pages WHERE number_status!='unverified'").fetchone()[0]
                    ocr=db.execute("SELECT value FROM state WHERE key='ocr'").fetchone()
                    from text_pipeline import init_passages,VERSION
                    init_passages(db)
                    reading_pages=db.execute('SELECT COUNT(*) FROM text_build WHERE version=?',(VERSION,)).fetchone()[0]
                    passage_count=db.execute("SELECT COUNT(*) FROM passages WHERE kind='body'").fetchone()[0]
                return self.send(200,{'books':books,'quality':counts,'verified_pages':verified,'reading_pages':reading_pages,'passage_count':passage_count,'ocr':json.loads(ocr[0]) if ocr else None,'key_configured':bool(API_KEY),'model':MODEL,'csrf':CSRF,'ocr_available':(DATA/'tessdata'/'kor.traineddata').exists(),'public':PUBLIC,'admin':self.is_admin(),'quota':self.quota_state(),'semantic_search':semantic_ready()})
            match=re.fullmatch(r'/api/pages/(\d+)',path)
            if match:
                with connect() as db:row=db.execute('SELECT p.*,b.title FROM pages p JOIN books b ON p.book_id=b.id WHERE p.id=?',(int(match[1]),)).fetchone()
                if not row:return self.send(404,{'error':'페이지를 찾을 수 없습니다.'})
                result=dict(row)
                from passage_search import layout_source
                with connect() as db:text,blocks,reading=layout_source(db,result['id'])
                if text:result.update(original_text=result['text'],text=text,reading_blocks=reading,corrections=sum(b.get('corrections',0) for b in reading))
                return self.send(200,result)
            match=re.fullmatch(r'/api/ask/([A-Za-z0-9_-]{16,40})',path)
            if match:
                job=AI_JOBS.get(match[1])
                if not job:return self.send(404,{'error':'작성 중이던 해설을 찾지 못했습니다. 서버가 다시 시작되었을 수 있으니 다시 질문해 주세요.'})
                return self.send(200,wait_job(match[1],job,time.monotonic()+AI_WAIT))
            allowed={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/ux.css':'ux.css','/sw.js':'sw.js','/manifest.webmanifest':'manifest.webmanifest','/icon.svg':'icon.svg','/icon-192.png':'icon-192.png','/icon-512.png':'icon-512.png'}
            if path not in allowed:return self.send(404,{'error':'찾을 수 없습니다.'})
            file=ROOT/'dist'/allowed[path]
            return self.send(200,file.read_bytes(),mimetypes.guess_type(str(file))[0] or 'application/octet-stream')
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
        except Exception:return self.send(500,{'error':'요청을 처리하지 못했습니다. 서버와 자료 상태를 확인해 주세요.'})
    def do_POST(self):
        global API_KEY
        if not self.host_ok() or not self.origin_ok() or not secrets.compare_digest(self.headers.get('X-CSRF-Token',''),CSRF):return self.send(403,{'error':'허용되지 않은 요청입니다.','csrf_expired':True})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=16384:return self.send(413,{'error':'요청이 너무 큽니다.'})
            body=json.loads(self.rfile.read(length));path=urlsplit(self.path).path
            if path=='/api/key':
                if PUBLIC:return self.send(404,{'error':'공개 서버에서는 키를 화면에서 설정하지 않습니다.'})
                key=body.get('key','')
                if not isinstance(key,str) or len(key)>512:return self.send(400,{'error':'키 형식을 확인해 주세요.'})
                if key and (len(key)<20 or not re.fullmatch(r'[A-Za-z0-9_\-]+',key)):return self.send(400,{'error':'키 형식을 확인해 주세요.'})
                try:save_api_key(key)
                except OSError:return self.send(500,{'error':'자동 연결을 위한 키 저장에 실패했습니다. 폴더 쓰기 권한을 확인해 주세요.'})
                API_KEY=key
                return self.send(200,{'configured':bool(API_KEY),'message':'이 컴퓨터에 키를 저장했습니다. 다음 실행부터 자동 연결됩니다.' if API_KEY else '연결을 해제하고 이 앱에 저장한 키를 삭제했습니다.'})
            if path=='/api/ask':
                started=time.monotonic()
                query=body.get('question','');category=body.get('category','문식성');mode=body.get('mode','search');bid=''
                if not isinstance(query,str) or not 2<=len(query.strip())<=1000:return self.send(400,{'error':'질문을 2~1,000자로 입력해 주세요.'})
                if category not in {'전체','문식성','문법','문학'} or mode not in {'search','reason'}:return self.send(400,{'error':'검색 조건을 확인해 주세요.'})
                use_ai,why=route_question(mode);sources=search_pages(query,category,bid)
                from concepts import match_concepts
                from term_index import match_terms
                concepts=match_concepts(query,category);terms=match_terms(query,category)
                # 관형절 asked, 안은문장 entry matched only through its alias, and the
                # books' index has 관형절 itself: the index card answers, the entry is
                # background. Only an index card that actually carries a defining
                # sentence may push an entry down — a row that just says "쪽을 열어
                # 확인하세요" answers nothing, and since the heading-derived pseudo
                # index (build_term_index.heading_terms) added 228 such terms, that
                # was demoting 문학의 갈래 체계 behind an empty 갈래론 row.
                covered={s['term'].replace(' ','').lower() for t in terms for s in t['sources'] if s['quote']}
                covered|={t['key'] for t in terms if any(s['quote'] for s in t['sources'])}
                for c in concepts:
                    if c['match']=='exact' and not c['by_label'] and any(c['matched_term'] in k for k in covered):c['match']='related'
                result={'question':query,'route':'reason' if use_ai else 'search','route_reason':why,'sources':sources,'answer':None,'ai_used':False,'notice':'','concepts':concepts,'terms':terms,'quota':None}
                if not sources:result['notice']='관련 근거를 찾지 못했습니다. 용어를 짧게 바꾸거나 검색 영역을 넓혀 주세요.'
                elif use_ai and not API_KEY:result['notice']='해설이 필요한 질문입니다. OpenAI API 키를 연결하면 근거를 바탕으로 설명합니다. 지금은 찾은 원문을 보여드립니다.'
                elif use_ai:
                    if not AI_LOCK.acquire(blocking=False):return self.send(429,{'error':'다른 해설을 생성 중입니다. 잠시 후 시도해 주세요.'})
                    job_id=None
                    try:
                        allowed,state=self.quota_state(consume=True);result['quota']=state
                        if not allowed:
                            result['notice']=('지금은 해설 사용량을 기록할 수 없어 AI 해설을 잠시 중단했습니다. 원문 검색과 개념 정리는 계속 이용할 수 있습니다.' if state.get('unavailable')
                                else f"오늘 서재 전체에 열어 둔 AI 해설 {quota.LIMIT}회를 모두 사용했습니다. 한국 시각 자정에 다시 채워지며, 원문 검색과 개념 정리는 계속 볼 수 있습니다.")
                        else:job_id=start_job(result,query,category,state,self.is_admin())
                    finally:
                        if job_id is None:AI_LOCK.release()  # otherwise the job's thread releases it
                    if job_id:return self.send(200,wait_job(job_id,AI_JOBS[job_id],started+AI_WAIT))
                return self.send(200,strip_sources(result))
            match=re.fullmatch(r'/api/pages/(\d+)/(verify|ocr)',path)
            if match:
                if PUBLIC and not self.is_admin():return self.send(403,{'error':'관리자만 사용할 수 있습니다.'})
                with connect() as db:row=db.execute('SELECT p.*,b.path FROM pages p JOIN books b ON p.book_id=b.id WHERE p.id=?',(int(match[1]),)).fetchone()
                if not row:return self.send(404,{'error':'페이지를 찾을 수 없습니다.'})
                if match[2]=='verify':
                    number=body.get('printed_page')
                    if type(number) is not int or not 1<=number<=5000:return self.send(400,{'error':'책에 인쇄된 쪽수를 입력해 주세요.'})
                    with connect() as db:db.execute("UPDATE pages SET printed_page=?,number_status='manual' WHERE id=?",(number,row['id']))
                    return self.send(200,{'message':'대조한 책 쪽수를 저장했습니다.'})
                if not OCR_LOCK.acquire(False):return self.send(429,{'error':'다른 페이지를 OCR 처리 중입니다.'})
                try:
                    with pymupdf.open(ROOT/row['path']) as doc:
                        txt,lines=ocr_page(doc[row['pdf_page']-1])
                    # Preserve original extraction, saving a separate OCR version for audit.
                    record={'text':txt,'lines':lines,'method':'tesseract-kor-eng-300dpi','pdf_page':row['pdf_page'],'book_id':row['book_id']}
                    (DATA/'text'/row['book_id']/f"{row['pdf_page']:04}.ocr.json").write_text(json.dumps(record,ensure_ascii=False),encoding='utf-8')
                    with connect() as db:
                        db.execute("INSERT INTO search(search,rowid,text,compact) VALUES('delete',?,?,?)",(row['id'],row['text'],normalized(row['text'])))
                        db.execute('UPDATE pages SET text=?,compact=?,method=?,quality=? WHERE id=?',(txt,normalized(txt),record['method'],quality(txt),row['id']))
                        db.execute('INSERT INTO search(rowid,text,compact) VALUES(?,?,?)',(row['id'],txt,normalized(txt)))
                    return self.send(200,{'message':'한국어 OCR을 다시 수행했습니다. 원문 이미지와 대조해 주세요.'})
                finally:OCR_LOCK.release()
            return self.send(404,{'error':'찾을 수 없습니다.'})
        except ValueError as e:return self.send(400,{'error':'입력값 또는 OCR 환경을 확인해 주세요.'})
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception:return self.send(500,{'error':'처리하지 못했습니다. 원문 검색은 계속 사용할 수 있습니다.'})

def semantic_ready():
    try:
        import vector_search
        return vector_search.ready()
    except Exception:return False

def warm_semantic_search():
    """Load the query model and vector index before the first question arrives."""
    try:
        import vector_search
        if vector_search.ready():vector_search.embed(['준비'])
    except Exception as error:print('의미 검색을 준비하지 못했습니다:',error,flush=True)

if __name__=='__main__':
    threading.Thread(target=warm_semantic_search,daemon=True).start()
    print(f'{"Public" if PUBLIC else "Local"} server on {HOST}:{PORT} (quota: {QUOTA.name if QUOTA else "unavailable"})' if PUBLIC else f'Local URL: http://localhost:{PORT}',flush=True)
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
