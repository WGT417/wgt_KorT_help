from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit, parse_qs
import os, json, re, threading, secrets, mimetypes, time, subprocess, gzip
from core import ROOT, DATA, connect, init_db, search_pages, route_question, pymupdf, normalized, quality, ocr_page
from explanation import collect_evidence, prompt_for, validate, ANSWER_SCHEMA,MODEL_ANSWER_SCHEMA,evidence_packet,resolve_evidence,add_cited_pages
import quota, access
import anthropic  # after core, which puts .runtime on sys.path

# PUBLIC=1 is set in the Dockerfile: bind all interfaces, trust the platform's
# routing instead of the localhost Host check, count AI usage in Firestore,
# refuse the local key-saving endpoint, and show whole pages only to the
# admins and the readers they let in (access.py). Everything else stays the
# desktop behaviour so start.cmd keeps working unchanged.
PUBLIC=os.environ.get('PUBLIC','')=='1'
PORT=int(os.environ.get('PORT','8765'))
HOST=os.environ.get('HOST','0.0.0.0' if PUBLIC else '127.0.0.1')
ADMIN_TOKEN=os.environ.get('ADMIN_TOKEN','')
ADMIN_EMAILS=access.admin_emails()
ALLOWED_HOSTS={h.strip() for h in os.environ.get('ALLOWED_HOSTS','').split(',') if h.strip()}
if not PUBLIC:
    for line in (ROOT/'.env').read_text(encoding='utf-8').splitlines() if (ROOT/'.env').exists() else []:
        if '=' in line and not line.lstrip().startswith('#'):
            name,value=line.split('=',1)
            if name.strip() == 'ANTHROPIC_API_KEY':os.environ.setdefault(name.strip(),value.strip().strip('"').strip("'"))
API_KEY=os.environ.get('ANTHROPIC_API_KEY','')
# The search plan is a list of keywords: the small tier does it. The 해설 is where the
# model shows: with GPT (2026-10-11) the nano tier wrote 하향 이중 모음 /əy/ as "/y/ 뒤에
# /ə/", dropped the books' proofs and listed classes without their members, and the
# flagship did none of that. Moved to Claude on 2026-11-22 with the same split.
MODEL='claude-haiku-5-5'
ANSWER_MODEL=os.environ.get('ANSWER_MODEL','claude-opus-5-5')
ANSWER_EFFORT=os.environ.get('ANSWER_EFFORT','medium')
CSRF=secrets.token_urlsafe(32)
AI_LOCK=threading.Lock()
OCR_LOCK=threading.Lock()
init_db()
QUOTA_BACKEND=os.environ.get('QUOTA_BACKEND','firestore' if PUBLIC else 'none')
try:QUOTA=quota.make(QUOTA_BACKEND)
except Exception as error:
    # Fail closed: keep the site up for search, but never generate without counting.
    print(f'quota backend unavailable ({QUOTA_BACKEND}): {error}',flush=True);QUOTA=None
READERS_BACKEND=os.environ.get('READERS_BACKEND','firestore' if PUBLIC else 'none')
try:READERS=access.make(READERS_BACKEND)
except Exception as error:
    # Fail closed like the quota: the site stays up, whole pages go to the admins only.
    print(f'readers backend unavailable ({READERS_BACKEND}): {error}',flush=True);READERS=None

def save_api_key(key):
    path=ROOT/'.env'
    lines=path.read_text(encoding='utf-8').splitlines() if path.exists() else []
    lines=[line for line in lines if line.split('=',1)[0].strip()!='ANTHROPIC_API_KEY']
    if key:lines.append('ANTHROPIC_API_KEY='+key)
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

def log_event(event,**fields):
    """One JSON line per event. Cloud Logging reads it as jsonPayload, so
    jsonPayload.event="ai_job" lists every 해설 with how long each step took."""
    print(json.dumps({'event':event,**{k:v for k,v in fields.items() if v is not None}},ensure_ascii=False),flush=True)

# The model calls of the 해설 being written on this thread (generate sets a list):
# seconds and tokens per call, so the log shows the plan and the answer apart.
CALLS=threading.local()

CLIENTS={}
def claude_client(key):
    # One client per key keeps its connection pool; the key changes only through /api/key.
    # Its retries also cover a connection the API drops before answering, which OpenAI
    # did to a 해설 after about a minute (RemoteDisconnected, 2026-11-04).
    if key not in CLIENTS:CLIENTS.clear();CLIENTS[key]=anthropic.Anthropic(api_key=key,timeout=anthropic.Timeout(300,connect=10),max_retries=2)
    return CLIENTS[key]

# A safety classifier can decline a benign request; with fallbacks the API reruns it on
# the model Anthropic recommends for that category inside the same call. Haiku has no
# server-side fallback, so its requests go without.
FALLBACK_BETA='server-side-fallback-2026-07-01'
def api_error(error,model):
    if isinstance(error,anthropic.APIConnectionError):return '앤트로픽 API 연결 시간이 초과되었거나 네트워크에 연결할 수 없습니다.'
    print(f'Anthropic API {getattr(error,"status_code","?")} {type(error).__name__} request_id={getattr(error,"request_id",None)}',flush=True)
    if isinstance(error,anthropic.AuthenticationError):return '앤트로픽 API 키 인증에 실패했습니다.'
    if isinstance(error,anthropic.PermissionDeniedError):return '앤트로픽 API 키의 사용 권한을 확인해 주세요.'
    if isinstance(error,anthropic.NotFoundError):return f'{model} 모델 접근 권한을 확인해 주세요.'
    if isinstance(error,(anthropic.PaymentRequiredError,anthropic.EnforcedSpendLimitReachedError,anthropic.ContractSpendLimitReachedError)):return '앤트로픽 API 크레딧 잔액이나 사용 한도를 확인해 주세요.'
    if isinstance(error,anthropic.RateLimitError):return '앤트로픽 API 요청 한도에 걸렸습니다. 잠시 후 다시 시도해 주세요.'
    if isinstance(error,anthropic.BadRequestError):
        # A spent balance comes back as a 400 that says so.
        if 'credit' in str(getattr(error,'message','')).lower():return '앤트로픽 API 크레딧 잔액을 확인해 주세요.'
        return '모델 또는 요청 설정을 확인해 주세요.'
    return '앤트로픽 API가 응답하지 못했습니다. 잠시 후 다시 시도해 주세요.'

def answer_text(message):
    """The JSON the model wrote. After a mid-stream fallback the declined model's
    partial text stays in front of a fallback block: read what follows the last
    one, and the whole run only if the fallback model continued the partial."""
    blocks=list(message.content)
    last=max((i for i,b in enumerate(blocks) if b.type=='fallback'),default=-1)
    tail=''.join(b.text for b in blocks[last+1:] if b.type=='text')
    whole=''.join(b.text for b in blocks if b.type=='text')
    for raw in dict.fromkeys((tail,whole)):
        try:return json.loads(raw)
        except ValueError:pass
    raise ValueError('해설 응답 형식이 올바르지 않습니다. 잠시 후 다시 시도해 주세요.')

def claude_call(prompt,key,*,schema=None,max_tokens=16000,effort='medium',model=None):
    model=model or MODEL
    params={'model':model,'max_tokens':max_tokens,'messages':[{'role':'user','content':prompt}],'output_config':{'effort':effort}}
    if schema:params['output_config']['format']={'type':'json_schema','schema':schema}
    if not model.startswith('claude-haiku'):params.update(betas=[FALLBACK_BETA],fallbacks='default')
    started=time.monotonic()
    try:
        # Streamed: thinking counts toward max_tokens, and the SDK refuses long non-streamed calls.
        with claude_client(key).beta.messages.stream(**params) as stream:message=stream.get_final_message()
    except anthropic.APIError as error:raise ValueError(api_error(error,model)) from None
    usage=message.usage;seconds=round(time.monotonic()-started,1)
    calls=getattr(CALLS,'log',None)
    # Inside a 해설 job the call goes into its ai_job log line; a script gets a line of its own.
    if calls is not None:calls.append({'model':message.model,'effort':effort,'s':seconds,'status':message.stop_reason,'in':usage.input_tokens,'out':usage.output_tokens})
    else:print(f'claude {message.model} effort={effort} in={usage.input_tokens} out={usage.output_tokens} stop={message.stop_reason} {seconds:.0f}s',flush=True)
    if message.stop_reason=='refusal':raise ValueError('모델이 이 질문에 대한 답을 거절했습니다. 질문을 바꿔 다시 시도해 주세요.')
    if message.stop_reason=='max_tokens':raise ValueError('해설이 길어져 끝까지 쓰지 못했습니다. 질문을 좁혀 다시 시도해 주세요.')
    return answer_text(message)

def reason(query,sources,concepts=()):
    packet,registry=evidence_packet(sources,concepts)
    answer=resolve_evidence(claude_call(prompt_for(query,sources,packet),API_KEY,schema=MODEL_ANSWER_SCHEMA,max_tokens=64000,effort=ANSWER_EFFORT,model=ANSWER_MODEL),registry)
    add_cited_pages(answer,sources)
    return validate(answer,sources)

# Firebase Hosting cuts a proxied request at 60s, and an AI 해설 often takes
# 45–70s. The answer is generated in a thread; a request waits at most AI_WAIT
# and otherwise hands back a job id the page asks for again. Jobs live in this
# process. deploy.json asks for one instance, but Cloud Run still starts a new
# one now and then (2026-11-04 03:12, 2026-11-13 05:28), and a poll that lands
# there finds no job (404): the page then says so instead of waiting.
AI_WAIT=48
AI_JOBS={};JOBS_LOCK=threading.Lock()
JOB_ID=re.compile(r'[A-Za-z0-9_-]{16,40}')

def refund_quota(admin):
    if admin or QUOTA is None:return
    try:QUOTA.refund(quota.today())
    except Exception as error:print(f'quota refund error: {error}',flush=True)

def spent_notice():
    return f"오늘 서재 전체에 열어 둔 AI 해설 {quota.LIMIT}회를 모두 사용했습니다. 한국 시각 자정에 다시 채워지니 내일 다시 이용해 주세요. 용어의 뜻은 용어 카드에서 바로 볼 수 있습니다."
PAUSED='지금은 해설 사용량을 기록할 수 없어 AI 해설을 잠시 중단했습니다. 잠시 후 다시 시도해 주세요.'
# The 해설 condenses the books' pages, book by book, so on the public site it follows the same
# rule as their quotes: only the admins and the accounts they let in (2026-09-29).
ASK_CLOSED='AI 해설은 개론서의 내용을 추려 쓰는 것이어서, 저작권을 지키기 위해 관리자가 열람을 허락해 드린 분께만 열어 두었습니다. 너그러이 양해해 주시면 감사하겠습니다. 용어의 뜻은 로그인하지 않아도 용어 카드에서 바로 보실 수 있습니다.'
NO_KEY='AI 해설을 쓰려면 앤트로픽 API 키를 연결해 주세요. 용어의 뜻은 용어 카드에서 바로 볼 수 있습니다.'

NOT_FOUND='관련 근거를 찾지 못했습니다. 용어를 짧게 바꾸거나 검색 영역을 넓혀 주세요.'
# Only another question meets this now: the same question joins the job (running_job).
BUSY='다른 질문의 해설을 쓰고 있습니다. 1~2분 뒤에 다시 시도해 주세요.'
LOST='작성 중이던 해설을 찾지 못했습니다. 서버가 바뀌었을 수 있으니 질문을 그대로 두고 다시 눌러 주세요.'

def strip_sources(result):
    for source in result['sources']:
        source.pop('text',None);source.pop('evidence_text',None)
    return result

# 개론서는 판매 중인 책이라, 책 문장을 그대로 옮긴 인용문과 참고 원문은 관리자가
# 허락한 계정에만 보낸다. 다른 방문자는 풀이·해설·개념 정리와 책·쪽까지 받는다.
# 출처는 남길 것만 고른다: 빼는 목록으로 두면 새로 붙는 본문 필드가 그대로 샌다.
SOURCE_KEYS=('id','source_id','book_id','title','category','pdf_page','printed_page','number_status','quality','match','kind')
def closed_view(result):
    """The same answer or card without the books' own sentences. Pure: the AI job
    result is shared by every poll, so it is copied, never changed in place."""
    if not isinstance(result,dict):return result
    view=json.loads(json.dumps(result,ensure_ascii=False))
    def unquote(node):
        if isinstance(node,dict):
            node.pop('quote',None)
            for value in node.values():unquote(value)
        elif isinstance(node,list):
            for value in node:unquote(value)
    if isinstance(view.get('sources'),list):view['sources']=[{k:s[k] for k in SOURCE_KEYS if k in s} for s in view['sources']]
    unquote(view.get('answer'))
    if isinstance(view.get('note'),dict):unquote(view['note'].get('citations'))
    for term in view.get('terms') or []:
        for s in term.get('sources',[]):
            # Which pages define the term stays known, so the card still lists them first.
            s['defines']=bool(s.pop('quote',None));s.pop('more',None)
    view['quotes_hidden']=True
    return view

def generate(job,query,category,state,admin):
    result=job['result'];CALLS.log=[];times={};outcome='ok'
    try:
        # The concept entries the question names are verified notes on the books, with
        # the old letters and jamo intact: the 해설 reads them first.
        concepts=result.get('concepts') or []
        began=time.monotonic()
        sources=collect_evidence(query,category,result['sources'],claude_call,API_KEY,concepts,result.get('terms') or [])
        times['evidence_s']=round(time.monotonic()-began,1)
        if not sources:raise ValueError(NOT_FOUND)
        result['sources']=sources
        began=time.monotonic()
        result['answer']=reason(query,sources,concepts);result['ai_used']=True
        times['answer_s']=round(time.monotonic()-began,1)
        answer=result['answer']
        if answer.get('insufficient') and category!='전체':
            answer['limitations']=(answer.get('limitations','')+' 검색 영역을 ‘전체’로 바꾸면 다른 영역의 개론서까지 함께 찾아봅니다.').strip()
    except Exception as error:
        outcome='notice' if isinstance(error,ValueError) else 'error'
        if not isinstance(error,ValueError):print(f'AI 해설 실패: {error!r}',flush=True)
        result['notice']=str(error) if isinstance(error,ValueError) else '해설을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.'
        refund_quota(admin)
        if 'remaining' in state:state['remaining']+=1
    finally:
        try:
            strip_sources(result)
            # Before done is set, so the line is out by the time any page has the answer. A 해설 that
            # ended in a notice used to leave no trace: 2026-11-13 05:26 ended after 25s, nobody knows why.
            # evidence_s holds the plan call (calls[0]); the rest of it is the searches.
            log_event('ai_job',severity={'ok':'INFO','notice':'WARNING'}.get(outcome,'ERROR'),job=job['id'][:8],outcome=outcome,notice=result.get('notice') or None,context_s=job.get('context_s'),total_s=round(time.monotonic()-job['at'],1),**times,pages=len(result.get('sources') or []),calls=CALLS.log)
        except Exception as error:print(f'job wrap-up error: {error!r}',flush=True)
        finally:CALLS.log=None;AI_LOCK.release();job['done'].set()

def start_job(result,query,category,state,admin,wanted=None,context_s=None):
    # The page names the job before sending, so a reload during the first AI_WAIT can still ask for it.
    job={'done':threading.Event(),'result':result,'question':query,'category':category,'quota':state,'at':time.monotonic(),'delivered':False,'context_s':context_s}
    with JOBS_LOCK:
        for old in [k for k,j in AI_JOBS.items() if time.monotonic()-j['at']>1800]:del AI_JOBS[old]
        job_id=wanted if isinstance(wanted,str) and JOB_ID.fullmatch(wanted) and wanted not in AI_JOBS else secrets.token_urlsafe(18)
        job['id']=job_id;AI_JOBS[job_id]=job
    threading.Thread(target=generate,args=(job,query,category,state,admin),daemon=True).start()
    return job_id

def running_job(query,category,wanted=None):
    """The job an ask joins instead of starting one or meeting 429: the same question
    still being written, or written and not yet handed to any page. 2026-11-13 a phone
    sent its question twice while a fresh instance took 17s over its first status; the
    second ask met 429, the page let go of the first, eight more taps met 429, and the
    first answer was written for nobody. The page's own job id (a retry after a dropped
    connection) joins its job even once handed over, so it is asked for, not paid for, again."""
    with JOBS_LOCK:
        jobs=([(wanted,AI_JOBS[wanted])] if isinstance(wanted,str) and wanted in AI_JOBS else [])+sorted(AI_JOBS.items(),key=lambda item:-item[1]['at'])
        for job_id,job in jobs:
            if job['question']!=query or job['category']!=category:continue
            if not job['done'].is_set():return job_id,job
            if job['result'].get('ai_used') and (job_id==wanted or not job['delivered']):return job_id,job
    return None,None

def wait_job(job_id,job,deadline):
    if job['done'].wait(max(1.0,deadline-time.monotonic())):
        job['delivered']=True
        return job['result']
    return {'question':job['question'],'pending':job_id,'quota':job['quota']}

def question_context(query,category,bid=''):
    """Search results, index term cards and concept entries for a question. When its
    examples show a sound change the question does not name ('국물'이 [궁물]로 …,
    phonology.change_names), the change is looked up as if named, ahead of the
    question's own words: those name nothing the books index, and search found
    0% and 8% of the pages for 국물 and 솜이불 (2026-11-04)."""
    from concepts import match_concepts
    from term_index import match_terms
    from phonology import change_names
    names=change_names(query)
    sources=search_pages(query,category,bid)
    terms=match_terms(query,category);concepts=match_concepts(query,category)
    if names:
        found=[search_pages(n,category,bid,limit=4) for n in names]+[sources]
        sources=list({r['id']:r for i in range(max(map(len,found))) for g in found if i<len(g) for r in [g[i]]}.values())[:8]
        terms=list({t['key']:t for t in [t for n in names for t in match_terms(n,category)]+terms}.values())[:4]
        concepts=list({c['id']:c for c in [c for n in names for c in match_concepts(n,category) if c['match']=='exact']+concepts}.values())[:4]
    return sources,terms,rank_concepts(concepts,terms)

def rank_concepts(concepts,terms):
    """관형절 asked, 안은문장 entry matched only through its alias, and the
    books' index has 관형절 itself: the index card answers, the entry is
    background. Only an index card that actually carries a defining sentence
    may push an entry down — a row that just says "쪽을 열어 확인하세요"
    answers nothing, and since the heading-derived pseudo index
    (build_term_index.heading_terms) added 228 such terms, that was demoting
    문학의 갈래 체계 behind an empty 갈래론 row."""
    covered={s['term'].replace(' ','').lower() for t in terms for s in t['sources'] if s['quote']}
    covered|={t['key'] for t in terms if any(s['quote'] for s in t['sources'])}
    for c in concepts:
        if c['match']=='exact' and not c['by_label'] and any(c['matched_term'] in k for k in covered):c['match']='related'
    return concepts

def card_concepts(label,concepts):
    """The entries a term card shows. A question names an entry with any one of
    its words, but a card is about the whole term: 말차례 순서 정하기 is not
    서술 시간(순서·지속·빈도), which matched on 순서 alone — 586 of 1,638 card
    matches were one word, and 486 of those entries never use the term. An
    entry is the answer when the term is its name or alias, and background
    when its text at least uses the term."""
    from term_index import key_of
    from concepts import entry_text
    k=key_of(label);kept=[]
    for c in concepts:
        if k in {key_of(t) for t in [c.get('label','')]+list(c.get('aliases',[]))}:
            c.update(match='exact',matched_term=k,by_label=k==key_of(c.get('label','')))
        elif k in key_of(entry_text(c)):c['match']='related'
        else:continue
        kept.append(c)
    return kept

def term_card(label):
    """One card from the term list: the term exactly, from every area, with the
    concept entries that name it — the same card a question naming it gets.
    None when there is nothing to show. scripts/build_term_cards.py writes every
    card of the list ahead of time with this same function."""
    from concepts import match_concepts
    from term_index import card,note
    # rank_concepts는 여기서 부르지 않는다: 그 강등은 질문 경로의 판단이다.
    # 카드에서는 색인 카드가 같은 화면 아래에 이미 있으므로, 별칭으로 맞았다고
    # 개념 정리를 칩 뒤로 숨기면 손해만 난다 — 6,476장을 돌려 보니 508장이
    # 그렇게 숨었고 그중 506장은 풀이도 없어 책 정의 한 줄만 남았다
    # (간접인용 → 인용 표현 3,219자 + 안은문장 5,081자). 강등되던 550개 짝을
    # 모두 읽어 잘못 붙은 것은 없었다.
    terms=card(label);concepts=card_concepts(label,match_concepts(label,'전체'));written=note(label)
    if not terms and not written and not any(c['match']=='exact' for c in concepts):return None
    return {'label':label,'note':written,'concepts':concepts,'terms':terms}

_catalog_body={'items':None,'plain':b'','gzip':b''}
def catalog_body():
    """The term list as sent: 6,500 entries are 170KB of JSON but 47KB gzipped."""
    from term_index import catalog
    items=catalog()
    if _catalog_body['items'] is not items:
        plain=json.dumps({'items':items},ensure_ascii=False,separators=(',',':')).encode()
        _catalog_body.update(items=items,plain=plain,gzip=gzip.compress(plain))
    return _catalog_body

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
    def signed_in(self):
        """The Google account the page signed in with (X-Id-Token), or ''."""
        token=self.headers.get('X-Id-Token','')
        if getattr(self,'_token',None)!=token:self._token=token;self._email=access.verify_token(token) if token else ''
        return self._email
    def is_admin(self):
        if ADMIN_TOKEN and secrets.compare_digest(self.headers.get('X-Admin-Token',''),ADMIN_TOKEN):return True
        email=self.signed_in()
        return bool(email) and email in ADMIN_EMAILS
    def can_read_pages(self):
        """Whole pages: always on this computer; on the public site only the admins and the
        readers they let in. The books are sold, so everyone else gets the quoted part."""
        if not PUBLIC or self.is_admin():return True
        email=self.signed_in()
        if not email or READERS is None:return False
        try:return READERS.allowed(email)
        except Exception as error:print(f'readers error: {error}',flush=True);return False
    def view(self,result):
        """What this visitor may receive of an answer or a card (closed_view)."""
        return result if self.can_read_pages() else closed_view(result)
    def join_job(self,job_id,job,started):
        log_event('ai_attach',job=job_id[:8],done=job['done'].is_set())
        return self.send(200,self.view(wait_job(job_id,job,started+AI_WAIT)))
    def user_state(self):
        email=self.signed_in()
        return {'email':email,'admin':self.is_admin(),'reader':self.can_read_pages()} if email else None
    def readers_body(self):
        return {'readers':READERS.list(),'admins':sorted(ADMIN_EMAILS)}
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
                return self.send(200,{'books':books,'quality':counts,'verified_pages':verified,'reading_pages':reading_pages,'passage_count':passage_count,'ocr':json.loads(ocr[0]) if ocr else None,'key_configured':bool(API_KEY),'model':ANSWER_MODEL,'csrf':CSRF,'ocr_available':(DATA/'tessdata'/'kor.traineddata').exists(),'public':PUBLIC,'admin':self.is_admin(),'user':self.user_state(),'whole_pages':self.can_read_pages(),'quota':self.quota_state(),'semantic_search':semantic_ready()})
            match=re.fullmatch(r'/api/pages/(\d+)',path)
            if match:
                with connect() as db:row=db.execute('SELECT p.*,b.title FROM pages p JOIN books b ON p.book_id=b.id WHERE p.id=?',(int(match[1]),)).fetchone()
                if not row:return self.send(404,{'error':'페이지를 찾을 수 없습니다.'})
                result=dict(row)
                if not self.can_read_pages():
                    # The quote the page asked about is already on screen; this adds only which book and page.
                    return self.send(200,{**{k:result[k] for k in ('id','book_id','title','pdf_page','printed_page','number_status','quality')},'restricted':True})
                from passage_search import layout_source
                with connect() as db:text,blocks,reading=layout_source(db,result['id'])
                if text:result.update(original_text=result['text'],text=text,reading_blocks=reading,corrections=sum(b.get('corrections',0) for b in reading))
                return self.send(200,result)
            if path=='/api/terms':
                body=catalog_body()
                zipped='gzip' in self.headers.get('Accept-Encoding','')
                data=body['gzip' if zipped else 'plain']
                self.send_response(200)
                self.send_header('Content-Type','application/json; charset=utf-8')
                if zipped:self.send_header('Content-Encoding','gzip')
                self.send_header('Vary','Accept-Encoding')
                self.send_header('Content-Length',str(len(data)))
                self.headers_safe();self.end_headers();self.wfile.write(data);return
            if path=='/api/terms/card':
                label=parse_qs(urlsplit(self.path).query).get('q',[''])[0].strip()
                if not 1<=len(label)<=100:return self.send(400,{'error':'용어를 확인해 주세요.'})
                result=term_card(label)
                if result is None:return self.send(404,{'error':'이 용어의 카드를 찾지 못했습니다.'})
                return self.send(200,self.view(result))
            if path=='/api/readers':
                if not PUBLIC or not self.is_admin():return self.send(403,{'error':'관리자만 볼 수 있습니다.'})
                if READERS is None:return self.send(503,{'error':'열람 허용 목록을 불러올 수 없습니다. 잠시 후 다시 시도해 주세요.'})
                return self.send(200,self.readers_body())
            match=re.fullmatch(r'/api/ask/([A-Za-z0-9_-]{16,40})',path)
            if match:
                job=AI_JOBS.get(match[1])
                # Counted so the log shows how often a new instance loses a job (see AI_WAIT).
                if not job:log_event('ai_lost',job=match[1][:8]);return self.send(404,{'error':LOST})
                return self.send(200,self.view(wait_job(match[1],job,time.monotonic()+AI_WAIT)))
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
                use_ai,why=route_question(mode)
                if use_ai:
                    # Not let in: answered before the search and the day's count, which it never touches.
                    if not self.can_read_pages():return self.send(200,{'question':query,'route':'reason','route_reason':why,'sources':[],'answer':None,'ai_used':False,'notice':ASK_CLOSED,'ask_closed':True,'concepts':[],'terms':[],'quota':None})
                    # A question already being written (a second tap, a retry) joins that job:
                    # no search, no count, even on the day's last one.
                    job_id,job=running_job(query,category,body.get('job'))
                    if job:return self.join_job(job_id,job,started)
                    # The page shows only a 해설 now, so when none can be written there is nothing to
                    # search for: the visitor reads why at once instead of after a search.
                    state=self.quota_state() if API_KEY else None
                    closed=NO_KEY if not API_KEY else PAUSED if state.get('unavailable') else spent_notice() if state.get('remaining')==0 else None
                    if closed:return self.send(200,{'question':query,'route':'reason','route_reason':why,'sources':[],'answer':None,'ai_used':False,'notice':closed,'concepts':[],'terms':[],'quota':state})
                    if AI_LOCK.locked():log_event('ai_busy');return self.send(429,{'error':BUSY})
                sources,terms,concepts=question_context(query,category,bid)
                result={'question':query,'route':'reason' if use_ai else 'search','route_reason':why,'sources':sources,'answer':None,'ai_used':False,'notice':'','concepts':concepts,'terms':terms,'quota':None}
                # A 해설 does not stop at an empty search. '두 사람이 손을 잡고 걷는다.'는 종속적으로
                # 이어진 문장인가? found no paragraph, while its concept entry and the books' indexes
                # named the very pages (2026-11-04: 5 of 24 eval questions stopped here). generate()
                # gives the count back when the evidence step finds nothing either.
                if not sources and not use_ai:result['notice']=NOT_FOUND
                elif use_ai:
                    # Two asks of one question sent together both pass the check above and search side
                    # by side. The one that misses the lock joins the other's job once it is registered,
                    # a count away (Firestore), instead of meeting 429.
                    waiting=time.monotonic()+5
                    while not AI_LOCK.acquire(blocking=False):
                        job_id,job=running_job(query,category,body.get('job'))
                        if job:return self.join_job(job_id,job,started)
                        if time.monotonic()>waiting:log_event('ai_busy');return self.send(429,{'error':BUSY})
                        time.sleep(.2)
                    job_id=None
                    try:
                        allowed,state=self.quota_state(consume=True);result['quota']=state
                        if not allowed:result['notice']=PAUSED if state.get('unavailable') else spent_notice()
                        else:job_id=start_job(result,query,category,state,self.is_admin(),body.get('job'),round(time.monotonic()-started,1))
                    finally:
                        if job_id is None:AI_LOCK.release()  # otherwise the job's thread releases it
                    if job_id:return self.send(200,self.view(wait_job(job_id,AI_JOBS[job_id],started+AI_WAIT)))
                return self.send(200,self.view(strip_sources(result)))
            if path in {'/api/readers','/api/readers/remove'}:
                if not PUBLIC or not self.is_admin():return self.send(403,{'error':'관리자만 바꿀 수 있습니다.'})
                if READERS is None:return self.send(503,{'error':'열람 허용 목록을 불러올 수 없습니다. 잠시 후 다시 시도해 주세요.'})
                email=access.normal(body.get('email'))
                if not email:return self.send(400,{'error':'구글 계정 이메일 주소를 확인해 주세요.'})
                if path=='/api/readers/remove':
                    removed=READERS.remove(email)
                    return self.send(200,{**self.readers_body(),'message':f'{email}의 전문 열람을 해제했습니다.' if removed else f'{email}은 목록에 없습니다.'})
                if email in ADMIN_EMAILS:return self.send(400,{'error':'관리자 계정은 따로 넣지 않아도 전문을 볼 수 있습니다.'})
                note=body.get('note','')
                if not isinstance(note,str) or len(note.strip())>60:return self.send(400,{'error':'메모는 60자 이내로 적어 주세요.'})
                READERS.add(email,note.strip(),self.signed_in() or 'admin-token')
                return self.send(200,{**self.readers_body(),'message':f'{email}에게 전문 열람을 허용했습니다. 그 계정으로 로그인하면 바로 보입니다.'})
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
        except Exception:return self.send(500,{'error':'처리하지 못했습니다. 잠시 후 다시 시도해 주세요.'})

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

def warm_catalog():
    """Build the term list before the first visitor opens it."""
    try:catalog_body()
    except Exception as error:print('용어 목록을 준비하지 못했습니다:',error,flush=True)

if __name__=='__main__':
    threading.Thread(target=warm_semantic_search,daemon=True).start()
    threading.Thread(target=warm_catalog,daemon=True).start()
    print(f'{"Public" if PUBLIC else "Local"} server on {HOST}:{PORT} (quota: {QUOTA.name if QUOTA else "unavailable"})' if PUBLIC else f'Local URL: http://localhost:{PORT}',flush=True)
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
