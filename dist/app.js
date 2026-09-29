'use strict';
const $=s=>document.querySelector(s);
let statusData=null,csrf='',installPrompt=null;
const number=n=>Number(n||0).toLocaleString('ko-KR');
function el(tag,text,cls){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;}
function notice(text,isError=false){const target=$('#feedback');target.replaceChildren();if(text)target.append(el('p',text,'notice'+(isError?' error':'')));}
let adminToken='';try{adminToken=localStorage.getItem('adminToken')||'';}catch{}
// 구글 로그인(Firebase): 공개 서재에서 쪽 전문은 관리자와, 관리자가 허용한 계정에만 보인다.
// SDK는 로그인 버튼을 누르거나 이 브라우저에서 로그인한 적이 있을 때만 불러온다.
const FIREBASE='https://www.gstatic.com/firebasejs/12.19.0/';
let auth=null,authLoading=null;
function wasSignedIn(){try{return localStorage.getItem('signedIn')==='1';}catch{return false;}}
function rememberSignedIn(on){try{if(on)localStorage.setItem('signedIn','1');else localStorage.removeItem('signedIn');}catch{}}
function loadAuth(){
    authLoading??=(async()=>{
        const [app,fb]=await Promise.all([import(FIREBASE+'firebase-app.js'),import(FIREBASE+'firebase-auth.js')]);
        const config=await (await fetch('/__/firebase/init.json')).json();
        const instance=fb.getAuth(app.initializeApp(config));
        await instance.authStateReady();
        if(!instance.currentUser)rememberSignedIn(false);
        return auth={instance,fb};
    })().catch(error=>{authLoading=null;throw error;});
    return authLoading;
}
async function idToken(){
    if(!auth&&!wasSignedIn())return '';
    try{const {instance}=await loadAuth();return instance.currentUser?await instance.currentUser.getIdToken():'';}catch{return '';}
}
async function authHeaders(extra={}){const headers={...extra};if(adminToken)headers['X-Admin-Token']=adminToken;const token=await idToken();if(token)headers['X-Id-Token']=token;return headers;}
const SIGN_IN_ERRORS={'auth/popup-blocked':'로그인 창이 막혔습니다. 브라우저에서 이 사이트의 팝업을 허용해 주세요.','auth/operation-not-allowed':'구글 로그인이 아직 켜져 있지 않습니다. 관리자에게 알려 주세요.','auth/unauthorized-domain':'이 주소에서는 로그인할 수 없습니다. kor-teacher-help.web.app에서 로그인해 주세요.','auth/network-request-failed':'네트워크에 연결할 수 없어 로그인하지 못했습니다.'};
// 팝업은 누른 그 순간에 열려야 막히지 않으므로(특히 Safari), 로그인 단추가 보일 때 SDK를 미리 불러 둔다.
function preloadAuth(){if(statusData?.public&&!statusData.user)loadAuth().catch(()=>{});}
async function signIn(){
    try{const {instance,fb}=auth||await loadAuth();await fb.signInWithPopup(instance,new fb.GoogleAuthProvider());rememberSignedIn(true);await loadStatus();return true;}
    catch(error){if(['auth/popup-closed-by-user','auth/cancelled-popup-request'].includes(error?.code))return false;const message=SIGN_IN_ERRORS[error?.code]||'로그인하지 못했습니다. 잠시 후 다시 시도해 주세요.';$('#account-status').textContent=message;notice(message,true);return false;}
}
async function signOutUser(){
    try{if(auth)await auth.fb.signOut(auth.instance);}catch{}
    rememberSignedIn(false);setAdminToken('');await loadStatus();
    if(location.hash==='#admin')showView('search');
}
function renderAccount(){
    const user=statusData?.user,admin=Boolean(statusData?.admin);
    $('#sign-in').hidden=Boolean(user);$('#sign-out').hidden=!user&&!adminToken;$('#admin-open').hidden=!admin;
    $('#account-status').textContent=user?(admin?`${user.email} · 관리자로 로그인했습니다. 인용문과 원문, 쪽 전문을 볼 수 있고 AI 해설 횟수 제한이 없습니다.`:user.reader?`${user.email} · 인용문과 원문, 쪽 전문을 볼 수 있는 계정입니다.`:`${user.email} · 아직 인용문과 원문 열람을 허락받지 않은 계정입니다. 관리자에게 이 주소를 알려 주세요.`):admin?'관리자 토큰으로 확인되었습니다.':'로그인하지 않았습니다.';
    $('#nav-admin').hidden=!(statusData?.public&&admin);
}
// 개론서는 판매 중인 책이라, 공개 서재에서 책 문장을 그대로 옮긴 인용문과 참고 원문은
// 관리자가 허락한 계정에만 보인다. 가려진 자리에는 이 안내가 대신 선다.
const CLOSED_TEXT='개론서는 판매 중인 책이어서, 책의 문장을 그대로 옮긴 인용문과 원문은 저작권을 지키기 위해 관리자가 열람을 허락해 드린 분께만 보여 드리고 있습니다. 너그러이 양해해 주시면 감사하겠습니다.';
function closedNotice(rest='',after=null,text=CLOSED_TEXT){
    const box=el('div',undefined,'notice restricted-note');box.setAttribute('role','note');
    box.append(el('p',text+(rest?' '+rest:'')));
    const user=statusData?.user;
    if(user)box.append(el('p',`지금 로그인하신 계정(${user.email})은 아직 열람을 허락받지 않았습니다.`,'small'));
    else if(statusData?.public){preloadAuth();const login=el('button','허락받은 계정으로 로그인');login.type='button';login.onclick=async()=>{if(await signIn()&&after)after();};box.append(login);}
    return box;
}
// 허락받은 계정이면 공개 파일(인용문이 없다) 대신 서버에서 카드를 받는다.
const readsQuotes=()=>Boolean(statusData?.public&&statusData.whole_pages);
// AI 해설도 개론서 내용을 추려 쓰는 것이라 같은 기준이다: 공개 서재에서는 허락받은 계정만 쓴다.
// 서버도 같은 기준으로 거절하므로(server.ASK_CLOSED) 이것은 누르기 전에 알려 주는 안내일 뿐이다.
const ASK_CLOSED_TEXT='AI 해설은 개론서의 내용을 추려 쓰는 것이어서, 저작권을 지키기 위해 관리자가 열람을 허락해 드린 분께만 열어 두었습니다. 너그러이 양해해 주시면 감사하겠습니다.';
const askClosed=()=>Boolean(statusData?.public&&!statusData.whole_pages);
let askGate='';
function renderAskGate(){
    const closed=askClosed(),box=$('#ask-closed');
    $('#ask-button').disabled=closed||$('#ask-button').textContent!=='해설 받기 →';
    if(closed){
        $('#side-connection').textContent='AI 해설은 허락받은 계정만';$('#mode-label').textContent='공개 서재';
    }
    // Rebuilt only when it changes: the status is asked for every 15 seconds.
    const key=closed?'closed:'+(statusData.user?.email||''):'';
    if(key===askGate)return;askGate=key;
    box.hidden=!closed;box.replaceChildren();
    if(closed)box.append(closedNotice('용어의 뜻은 로그인하지 않아도 용어 카드에서 바로 보실 수 있습니다.',null,ASK_CLOSED_TEXT));
}
async function api(path,body,retried=false){const response=await fetch(path,body===undefined?{headers:await authHeaders()}:{method:'POST',headers:await authHeaders({'Content-Type':'application/json','X-CSRF-Token':csrf}),body:JSON.stringify(body)});let result;try{result=await response.json();}catch{throw new Error(response.ok?'서버 응답을 읽지 못했습니다. 다시 시도해 주세요.':'서버 응답이 늦어 연결이 끊겼습니다. 잠시 후 다시 시도해 주세요.');}if(!response.ok){if(response.status===403&&result.csrf_expired&&!retried&&body!==undefined){await loadStatus();return api(path,body,true);}throw Object.assign(new Error(result.error||'요청을 처리하지 못했습니다.'),{status:response.status});}if(path==='/api/status'){$('#settings-open').hidden=result.public?false:Boolean(result.key_configured);$('#settings-label').textContent=result.public?(result.admin?'관리자':result.user?'내 계정':'로그인'):'연결 설정';}return result;}
function quotaText(q){if(!q)return '';if(q.admin)return '관리자 · AI 해설 제한 없음';if(q.unavailable)return 'AI 해설 일시 중단';if(q.unlimited)return '';return `오늘 남은 AI 해설 ${q.remaining}회 / 전체 ${q.limit}회`;}
function showQuota(q){if(!q||q.unlimited)return;const text=quotaText(q);if(text)$('#side-connection').textContent=text;$('#connection-dot').classList.toggle('off',Boolean(q.unavailable||q.remaining===0));}
async function loadStatus(){try{statusData=await api('/api/status');csrf=statusData.csrf;const books=statusData.books;for(const cat of ['문식성','문법','문학']){const count=books.filter(b=>b.category===cat).length;$('#count-'+cat).textContent=count;$('#card-count-'+cat).textContent=count+'권';}const done=books.reduce((a,b)=>a+b.processed,0),total=books.reduce((a,b)=>a+b.pages,0);$('#index-title').textContent=`${books.length}권의 개론서를 함께 살펴봅니다`;$('#index-detail').textContent=`${number(statusData.reading_pages)} / ${number(total)}페이지 문단 정리 · 띄어쓰기 자동 처리${statusData.semantic_search?' · 뜻으로도 찾기':''}`;$('#index-badge').textContent=statusData.ocr?.status==='running'?`OCR 보완 ${statusData.ocr.done}/${statusData.ocr.total}`:statusData.reading_pages===total&&total?'문단 정리 완료':'문단 정리 중';$('#side-connection').textContent=statusData.key_configured?(statusData.public?'AI 해설 사용 가능':'OpenAI 키 연결됨'):'AI 해설에는 OpenAI 키 연결 필요';$('#mode-label').textContent=statusData.public?(statusData.admin?'공개 서재 · 관리자':'공개 서재 · AI 해설 하루 전체 '+(statusData.quota?.limit??100)+'회'):'개인 로컬 서재';$('#key-section').hidden=Boolean(statusData.public);$('#account-section').hidden=!statusData.public;$('#settings-title').textContent=statusData.public?'계정':'OpenAI 자동 연결';if(statusData.key_configured)showQuota(statusData.quota);if(!$('#settings-dialog').open)$('#key-status').textContent=statusData.key_configured?'키가 연결되어 있습니다. 첫 해설 요청에서 API 사용 가능 여부를 확인합니다.':'현재 연결된 키가 없습니다.';renderAccount();renderAskGate();if(location.hash==='#admin'&&!statusData.admin)showView('search',false);}catch(error){notice(statusData?.public?'서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.':'로컬 서버에 연결할 수 없습니다. 앱 실행 파일로 서버를 시작해 주세요.',true);$('#side-connection').textContent='서버 연결 안 됨';}}
function chooseCategory(category){$('#category').value=category;$('#question').focus();}
function pageLabel(s){return s.printed_page?`책 ${s.printed_page}쪽${s.number_status==='offset'?'(계산)':''} · 자료 ${s.pdf_page}페이지`:`자료 ${s.pdf_page}페이지 · 책 쪽수 미확인`;}
function qualityLabel(s){return s.number_status==='manual'?'책 쪽수 원문 대조 완료':s.number_status==='sequence'?'책 쪽수 연속 번호로 자동 확인':s.number_status==='offset'?'책 쪽수 여백에서 읽지 못해 앞뒤 확정 쪽의 간격으로 계산 · 인용 전 확인 권장':'책 쪽수 확인 전 · 자료 페이지 기준';}
function referenceButton(source,quote=''){
    const quotes=Array.isArray(quote)?quote:quote?[quote]:[];
    const button=el('button',`${source.title} · ${source.printed_page?'책 '+source.printed_page+'쪽':'자료 '+source.pdf_page+'페이지'}${quotes.length>1?' · 근거 '+quotes.length+'곳':''}`,'reference-button citation-chip');
    button.type='button';button.title=pageLabel(source)+(quotes.length?'\n'+quotes.join('\n\n'):'');
    button.onclick=()=>openSource(source.id,quote);return button;
}
function appendCitations(target,citations,sources){
    const span=el('span',undefined,'inline-citations');
    const grouped=new Map();
    // Without a let-in account the citations carry only the page, not its sentence.
    for(const citation of citations||[]){if(!grouped.has(citation.source_id))grouped.set(citation.source_id,[]);const quotes=grouped.get(citation.source_id);if(citation.quote&&!quotes.includes(citation.quote))quotes.push(citation.quote);}
    for(const [id,quotes] of grouped){const source=sources.find(s=>s.source_id===id);if(source)span.append(referenceButton(source,quotes));}
    target.append(span);
}
// Numbering follows Korean document order: section 1. → subsection 가. → point ①.
const circled='①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳',hangulOrder='가나다라마바사아자차카타파하';
function numberedHeading(tag,mark,title,markClass){const h=el(tag);h.append(el('span',mark,markClass),el('span',title));return h;}
function renderPoints(target,points,sources){
    if(!points?.length)return;
    const list=el('ol',undefined,'explanation-points');
    points.forEach((point,i)=>{
        const item=el('li',undefined,'explanation-point');item.append(el('span',circled[i]||`(${i+1})`,'point-num'));
        if(point.label)item.append(el('p',point.label,'point-label'));
        item.append(el('p',point.text,'point-text'));
        if(point.examples?.length){const box=el('div',undefined,'point-examples');box.append(el('span','예','example-tag'));const examples=el('ul',undefined,'example-list');for(const example of point.examples)examples.append(el('li',example));box.append(examples);item.append(box);}
        if(point.citations?.length){const refs=el('div',undefined,'point-refs');refs.append(el('span','근거','refs-tag'));appendCitations(refs,point.citations,sources);item.append(refs);}
        list.append(item);
    });
    target.append(list);
}
function renderExplanation(answer,sources){
    const article=el('article',undefined,'explanation');
    const top=el('div',undefined,'explanation-top');top.append(el('span','AI 해설','badge ai-badge'),el('span','개론서 원문을 근거로 작성 · '+(answer.validation||'항목마다 근거 쪽을 표시했습니다.'),'small muted'));
    article.append(top,el('h3',answer.title,'explanation-title'));
    const sections=answer.sections||[];
    if(sections.length>=3){
        const toc=el('nav',undefined,'explanation-toc');toc.setAttribute('aria-label','해설 차례');toc.append(el('p','차례','toc-label'));
        const ol=el('ol');sections.forEach((section,i)=>{const li=el('li'),a=el('a');a.href='#ai-section-'+(i+1);a.append(el('span',`${i+1}.`,'toc-num'),document.createTextNode(section.title));li.append(a);ol.append(li);});
        toc.append(ol);article.append(toc);
    }
    sections.forEach((section,i)=>{
        const part=el('section',undefined,'explanation-section');part.id='ai-section-'+(i+1);
        part.append(numberedHeading('h4',String(i+1),section.title,'section-num'));renderPoints(part,section.points,sources);
        (section.subsections||[]).forEach((sub,j)=>{const child=el('section',undefined,'explanation-subsection');child.append(numberedHeading('h5',`${hangulOrder[j]||j+1}.`,sub.title,'sub-num'));renderPoints(child,sub.points,sources);part.append(child);});
        article.append(part);
    });
    if(answer.summary?.rows?.length){
        const section=el('section',undefined,'explanation-section summary-section');section.append(numberedHeading('h4','표','종합 일람표','section-num summary-num'));
        const scroll=el('div',undefined,'table-scroll');scroll.tabIndex=0;scroll.setAttribute('role','region');scroll.setAttribute('aria-label','개념 종합 일람표');
        const table=el('table',undefined,'concept-table');table.append(el('caption','분류와 핵심 내용을 한눈에 정리했습니다. 출처를 누르면 해당 근거를 확인할 수 있습니다.'));
        const head=el('thead'),tr=el('tr');for(const label of [...answer.summary.columns,'출처']){const th=el('th',label);th.scope='col';tr.append(th);}head.append(tr);table.append(head);
        const body=el('tbody');for(const row of answer.summary.rows){const tr=el('tr');row.cells.forEach((cell,i)=>{const td=el(i===0?'th':'td',cell);if(i===0)td.scope='row';tr.append(td);});const refs=el('td');appendCitations(refs,row.citations,sources);tr.append(refs);body.append(tr);}table.append(body);scroll.append(table);section.append(scroll);article.append(section);
    }
    if(answer.limitations)article.append(el('p',answer.limitations,'notice'));
    if(answer.rejected_count)article.append(el('p','원문 인용을 확인하지 못한 설명 일부를 제외했습니다. 이 답변은 불완전할 수 있습니다.','notice'));
    else if(answer.insufficient)article.append(el('p','일부 항목은 확보한 자료만으로 충분히 설명하지 못했습니다.','notice'));
    return article;
}
function renderTable(block,caption){
    // Small-print tables keep their source rows; a two-column table becomes term → items.
    const wrap=el('div',undefined,'source-table');wrap.append(el('p',block.caption?`${block.caption} · ${caption}`:caption,'source-table-caption'));
    const list=el('ul');
    for(const row of block.rows||[]){const li=el('li');if(row.length>1){li.append(el('strong',row[0]));li.append(document.createTextNode(' '+row.slice(1).join(' · ')));}else li.textContent=row[0];list.append(li);}
    wrap.append(list);return wrap;
}
function conceptSourceButton(source){
    const label=`${source.title||source.book} · ${source.printed_page?'책 '+source.printed_page+'쪽'+(source.number_status==='offset'?'(계산)':''):'자료 '+source.pdf_page+'페이지'}`;
    const button=el('button',label,'reference-button citation-chip');button.type='button';
    if(source.id){button.title=(source.note||'')+(source.terms?.length?'\n일치 용어: '+source.terms.join(', '):'');button.onclick=()=>openSource(source.id,'');}
    else{button.disabled=true;button.title='이 서재에서 해당 책을 찾지 못했습니다.';}
    return button;
}
function inlineText(text){
    // Authored markup is limited to **emphasis** and `ending`; everything else is literal text.
    const frag=document.createDocumentFragment();const re=/\*\*([^*]+)\*\*|`([^`]+)`/g;let last=0,m;
    while((m=re.exec(text))){if(m.index>last)frag.append(document.createTextNode(text.slice(last,m.index)));frag.append(m[1]!==undefined?el('strong',m[1]):el('code',m[2],'ending'));last=re.lastIndex;}
    if(last<text.length)frag.append(document.createTextNode(text.slice(last)));return frag;
}
function refChips(refs,sources){
    const row=el('span',undefined,'inline-citations concept-refs');
    for(const i of refs||[]){const s=sources[i];if(s)row.append(conceptSourceButton(s));}
    return row;
}
function conceptItem(item,sources){
    const li=el('li');
    if(typeof item==='string'){li.append(inlineText(item));return li;}
    const p=el('p');
    if(item.label)p.append(el('strong',item.label+(item.text?': ':'')));
    if(item.text)p.append(inlineText(item.text));
    if(item.refs?.length)p.append(' ',refChips(item.refs,sources));
    li.append(p);
    if(item.sub?.length){const ul=el('ul',undefined,'concept-sub');for(const s of item.sub)ul.append(conceptItem(s,sources));li.append(ul);}
    if(item.examples?.length){const ul=el('ul',undefined,'concept-usage');for(const e of item.examples){const x=el('li');x.append(inlineText(e));ul.append(x);}li.append(ul);}
    return li;
}
function renderConcept(entry){
    // Fixed, pre-written content laid out as one document. Nothing here is generated at query time.
    const card=el('article',undefined,'concept-card');
    const head=el('div',undefined,'concept-head');head.append(el('span',entry.area,'badge'),el('span',entry.parent||'','concept-parent'),el('h3',entry.label));
    const status=entry.review?.status==='reviewed'?'검수 완료':'초안 · 검수 전';head.append(el('span',status,'badge concept-status'));
    card.append(head);
    if(entry.review?.audience_note&&entry.review.status!=='reviewed')card.append(el('p',entry.review.audience_note,'small muted'));
    const body=el('div',undefined,'concept-body concept-doc');const sources=entry.sources||[];
    if(entry.summary)body.append(el('p',entry.summary,'concept-lead'));
    if(entry.sections?.length){
        entry.sections.forEach((section,i)=>{
            body.append(el('h4',`${i+1}. ${section.heading}`));
            if(section.intro)body.append(el('p',section.intro,'concept-intro'));
            const ul=el('ul',undefined,'concept-items');for(const item of section.items||[])ul.append(conceptItem(item,sources));body.append(ul);
        });
    }else for(const p of entry.explanation||[])body.append(el('p',p));
    if(sources.length){
        const foot=el('div',undefined,'concept-sources');foot.append(el('p','개론서 근거 · 누르면 해당 쪽 본문을 엽니다.','small muted'));
        const row=el('div',undefined,'inline-citations');for(const src of sources)row.append(conceptSourceButton(src));foot.append(row);
        const pending=sources.filter(x=>x.status!=='verified').length;if(pending)foot.append(el('p',`${pending}곳은 용어 일치로 찾은 후보 쪽이며 본문 대조 전입니다.`,'small muted'));
        body.append(foot);
    }
    card.append(body);return card;
}
const conceptLabels=new Map();
function renderConcepts(concepts,target=$('#concepts'),relatedLead='질문한 개념의 정리는 아직 없습니다. 상위 개념 정리 보기: '){
    target.replaceChildren();
    if(!concepts?.length)return;
    for(const c of concepts)conceptLabels.set(c.id,c.label);
    const exact=concepts.filter(c=>c.match!=='related'),related=concepts.filter(c=>c.match==='related');
    if(exact.length){
        const heading=el('div',undefined,'section-heading concept-heading');heading.append(el('h3','개념 정리'),el('span','미리 작성한 정리 · AI 미사용','small muted'));target.append(heading);
        for(const entry of exact)target.append(renderConcept(entry));
    }
    if(related.length){
        // A broader entry that only contains the asked word is offered, not shown as the answer.
        const row=el('p',undefined,'concept-related');row.append(document.createTextNode(relatedLead));
        for(const entry of related){const b=el('button',`${entry.label} (${entry.parent||entry.area})`,'citation-chip');b.type='button';b.onclick=()=>{row.after(renderConcept(entry));b.disabled=true;};row.append(b);}
        target.append(row);
    }
}
function renderTerms(terms,target=$('#concepts')){
    // Straight from the books' back-of-book indexes: the sentences that define or explain the term (definitions first), then the other pages that list it.
    for(const term of terms||[]){
        const card=el('article',undefined,'concept-card term-card');
        const head=el('div',undefined,'concept-head');head.append(el('span','찾아보기','badge'),el('h3',term.label));
        // A card without the books' sentences (quotes_hidden) still marks the defining pages (defines).
        const defines=s=>Boolean(s.quote||s.defines);
        const books=new Set(term.sources.map(s=>s.book)).size,defined=term.sources.filter(defines).length;head.append(el('span',`개론서 ${books}권 · 정의 ${defined}곳 · AI 미사용`,'concept-parent'));card.append(head);
        if(term.variants.length>1)card.append(el('p','표기: '+term.variants.join(' · '),'small muted'));
        const quoted=term.sources.filter(defines),others=term.sources.filter(s=>!defines(s));
        if(quoted.length&&!quoted.some(s=>s.quote)){
            // Without the sentences a box per page would stand empty: one line of the defining pages.
            const line=el('div',undefined,'term-more');line.append(el('span','이 용어를 정의한 쪽','small muted'));
            for(const s of quoted)line.append(conceptSourceButton(s));
            card.append(line);
        }else if(quoted.length){
            const list=el('div',undefined,'term-sources');
            for(const s of quoted){
                const row=el('div',undefined,'term-source');row.append(conceptSourceButton(s));
                if(!s.indexed)row.append(el('span','찾아보기 밖','term-tag'));
                if(s.ocr)row.append(el('span','오인식 있음','term-tag warn'));
                // The defining sentence, then what the paragraph says next about the term.
                if(s.quote){const p=el('p',s.quote,'term-quote');if(s.more)p.append(document.createTextNode(' '),el('span',s.more,'term-quote-more'));row.append(p);}
                list.append(row);
            }
            card.append(list);
        }
        // Pages that only mention the term get one line of page buttons, not a row each.
        if(others.length){
            const more=el('div',undefined,'term-more');more.append(el('span',quoted.length?'이 용어가 나오는 다른 쪽':'이 용어가 나오는 쪽','small muted'));
            for(const s of others)more.append(conceptSourceButton(s));
            card.append(more);
        }
        target.append(card);
    }
}
function renderResults(data,restoring=false){
    $('#welcome').hidden=true;$('#results').hidden=false;
    renderConcepts(data.concepts);renderTerms(data.terms);
    $('#result-title').textContent=data.question;$('#route-badge').textContent='개론서 근거 기반 해설';
    const hidden=Boolean(data.quotes_hidden);
    $('#route-reason').textContent=hidden?'각 설명마다 근거가 실린 책과 쪽을 표시했습니다. 인용한 원문은 열람을 허락받은 계정에만 보입니다.':'각 설명의 출처를 누르면 인용한 원문을 확인할 수 있습니다.';notice(data.notice);
    if(data.quota&&!restoring)showQuota(data.quota);  // a saved count is stale; loadStatus shows today's
    const answer=$('#answer');answer.replaceChildren();
    if(data.answer)answer.append(renderExplanation(data.answer,data.sources));
    const bookCount=new Set(data.sources.map(s=>s.book_id)).size;
    $('#source-count').textContent=`${bookCount}권 · ${data.sources.length}개 페이지`;
    $('#source-details').open=false;
    const target=$('#sources');target.replaceChildren();
    if(hidden)target.append(closedNotice('해설에 쓴 책과 쪽은 아래에 그대로 적어 두었습니다.',reloadAnswer));
    for(const s of data.sources){
        const card=el('article',undefined,'source-card');const meta=el('div',undefined,'source-meta');meta.append(el('span',s.category,'badge'),el('strong',s.title));if(s.match==='semantic')meta.append(el('span','뜻이 가까운 문단','badge meaning-badge'));meta.append(el('span',pageLabel(s),'page-label'));
        if(hidden){const bottom=el('div',undefined,'source-bottom');bottom.append(referenceButton(s));card.append(meta,bottom);target.append(card);continue;}
        const bottom=el('div',undefined,'source-bottom');bottom.append(el('p',(s.match==='semantic'?'질문의 낱말이 그대로 나오지 않지만 의미가 가까워 찾은 문단 · ':'')+(s.quality==='review'?'글자 오인식이 많은 페이지 · 원문 이미지와 대조 필요':'띄어쓰기 자동 정리 · 원문 대조 가능')+(s.corrections?` · 오인식 낱말 ${s.corrections}곳 화면 교정`:'')),referenceButton(s,s.excerpt));card.append(meta,el('p',s.display_excerpt||s.excerpt.replace(/\s+/g,' ').trim(),'reading-passage'));
        for(const block of s.structured||[])card.append(renderTable(block,'같은 쪽의 표'));
        if(s.quality==='review')card.append(el('p','이 페이지는 OCR을 다시 수행한 뒤에도 오인식이 많습니다. 인용 전 원문 이미지를 확인하세요.','notice'));
        card.append(bottom);target.append(card);
    }
    // On a reload the browser puts the scroll back where it was; jumping to the top would undo that.
    if(!restoring){$('#results').focus({preventScroll:true});$('#results').scrollIntoView({behavior:'auto',block:'start'});}
}
// A reload keeps what was on screen: this tab's sessionStorage holds the last answer, and while an AI 해설
// is still being written, the job id the page chose for it, so the new page can ask the server again.
const SAVED_ASK='lastAsk';
function saveAsk(entry){
    try{
        if(!entry){sessionStorage.removeItem(SAVED_ASK);return;}
        try{sessionStorage.setItem(SAVED_ASK,JSON.stringify(entry));}
        catch{const {data,...rest}=entry;sessionStorage.setItem(SAVED_ASK,JSON.stringify({...rest,pending:true}));}  // too big to keep: fetch it again after a reload
    }catch{}
}
function savedAsk(){try{return JSON.parse(sessionStorage.getItem(SAVED_ASK)||'null');}catch{return null;}}
function newJobId(){try{return crypto.randomUUID();}catch{return Array.from(crypto.getRandomValues(new Uint8Array(18)),b=>b.toString(16).padStart(2,'0')).join('');}}
async function resumeJob(entry){
    // A reload during the first request's search finds no job yet, so give that search a minute to start it.
    for(;;){
        try{return await api('/api/ask/'+entry.job);}
        catch(error){
            if(error.status!==404)throw error;
            if(Date.now()-entry.started>60000)throw Object.assign(new Error('새로고침하는 사이 해설을 이어 받지 못했습니다. 질문을 그대로 두었으니 다시 눌러 주세요.'),{status:404});
        }
        await new Promise(resolve=>setTimeout(resolve,3000));
    }
}
// Signing in from the 원문 notice asks for the answer just written again, now with its quotes.
// The job stays on the server for 30 minutes and asking for it again uses no AI 해설.
async function reloadAnswer(){
    const saved=savedAsk();if(!saved?.job)return;
    try{const data=await api('/api/ask/'+saved.job);if(data.ai_used&&data.question===saved.question){renderResults(data,true);saveAsk({...saved,data});}}catch{}
}
async function ask(question,category,mode,resume=null){
    if(mode==='reason'&&askClosed()){renderAskGate();$('#ask-closed').scrollIntoView({block:'nearest'});return;}
    const button=$('#ask-button');
    $('#answer').replaceChildren();$('#concepts').replaceChildren();$('#sources').replaceChildren();$('#results').hidden=true;
    button.disabled=true;button.textContent='해설 쓰는 중…';$('#results').setAttribute('aria-busy','true');
    notice(resume?'새로고침 전에 요청한 해설을 이어서 받고 있습니다.':'여러 개론서의 근거를 모아 해설을 작성하고 있습니다. 1분 남짓 걸릴 수 있습니다.');
    const entry=resume||{question,category,mode,started:Date.now(),pending:true};
    if(mode==='reason'&&!entry.job)entry.job=newJobId();
    saveAsk(entry);
    try{
        let data=resume?await resumeJob(entry):await api('/api/ask',{question,category,mode,job:entry.job});
        while(data.pending){
            if(data.quota)showQuota(data.quota);
            if(data.pending!==entry.job){entry.job=data.pending;saveAsk(entry);}
            notice(`여러 개론서의 근거를 모아 해설을 쓰고 있습니다. ${Math.round((Date.now()-entry.started)/1000)}초 지났습니다. 조금만 더 기다려 주세요.`);
            data=await api('/api/ask/'+data.pending);
        }
        if(data.question!==question)throw new Error('질문과 응답이 일치하지 않아 표시하지 않았습니다. 다시 질문해 주세요.');
        // No 해설 (the day's count used up, no key, nothing found, generation failed): the page shows why and nothing else.
        if(data.ask_closed)loadStatus();  // the page thought this account was let in; show the notice under the form
        if(!data.ai_used){if(data.quota)showQuota(data.quota);notice(data.notice||'해설을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.');saveAsk({question,category,mode});return;}
        renderResults(data);saveAsk({question,category,mode,job:entry.job,started:entry.started,data});
    }catch(error){
        notice(error.message,true);
        // The server answered with an error, so there is nothing left to wait for. A dropped connection
        // (no status) may still have a job running, and a reload will ask for it again.
        if(error.status||!entry.job)saveAsk({question,category,mode});
    }finally{button.disabled=false;button.textContent='해설 받기 →';$('#results').removeAttribute('aria-busy');}
}
$('#question-form').addEventListener('submit',async event=>{event.preventDefault();if(!csrf){await loadStatus();if(!csrf)return;}await ask($('#question').value.trim(),$('#category').value,'reason');});
// In the term cards view the side menu's areas filter the cards instead of the question.
document.querySelectorAll('[data-category]').forEach(button=>button.onclick=()=>{if(!$('#terms-view').hidden){termsState.area={'문식성':1,'문법':2,'문학':4}[button.dataset.category];termsState.initial='';termsState.shown=PAGE;renderTermsView();}else chooseCategory(button.dataset.category);});
document.querySelectorAll('[data-question]').forEach(button=>button.onclick=()=>{$('#question').value=button.dataset.question;$('#category').value=button.dataset.question.includes('피동')?'문법':'전체';$('#question').focus();});
$('#nav-search').onclick=()=>{showView('search');$('#question').focus();};
$('#nav-terms').onclick=()=>showView('terms');
$('#nav-admin').onclick=()=>showView('admin');
$('#terms-strip').onclick=$('#terms-guide').onclick=()=>showView('terms');
$('#settings-open').onclick=()=>{preloadAuth();$('#api-key').value='';$('#key-status').textContent=statusData?.key_configured?'키 연결됨 · 첫 해설 요청에서 API를 확인합니다.':'현재 연결된 키가 없습니다.';$('#settings-dialog').showModal();};
document.querySelectorAll('[data-close]').forEach(button=>button.onclick=()=>document.getElementById(button.dataset.close).close());
$('#settings-dialog').addEventListener('close',()=>{$('#api-key').value='';});
$('#key-form').onsubmit=async event=>{event.preventDefault();const field=$('#api-key');const key=field.value.trim();field.value='';try{const data=await api('/api/key',{key});await loadStatus();$('#key-status').textContent=data.message;}catch(error){$('#key-status').textContent=error.message;}};
$('#disconnect').onclick=async()=>{try{const data=await api('/api/key',{key:''});await loadStatus();$('#key-status').textContent=data.message;}catch(error){$('#key-status').textContent=error.message;}};
function setAdminToken(value){adminToken=value;try{if(value)localStorage.setItem('adminToken',value);else localStorage.removeItem('adminToken');}catch{}}
$('#sign-in').onclick=()=>signIn();
$('#sign-out').onclick=()=>signOutUser();
$('#admin-open').onclick=()=>{$('#settings-dialog').close();showView('admin');};
// 열람 허용 관리: 관리자만 본다. 넣고 빼면 서버의 목록(Firestore)이 바로 바뀐다.
const dateOf=iso=>{const d=new Date(iso);return iso&&!isNaN(d)?d.toLocaleDateString('ko-KR'):'';};  // 서버는 UTC로 적는다
function renderReaders(data){
    const list=$('#reader-list');list.replaceChildren();
    $('#reader-count').textContent=`${data.readers.length}명`;
    if(!data.readers.length)list.append(el('li','아직 허용한 계정이 없습니다.','reader-empty'));
    for(const r of data.readers){
        const row=el('li',undefined,'reader-row');const who=el('div');who.append(el('strong',r.email),el('small',[r.note,dateOf(r.added)&&dateOf(r.added)+' 허용'].filter(Boolean).join(' · ')));
        const remove=el('button','빼기');remove.type='button';
        remove.onclick=async()=>{if(!confirm(`${r.email}의 쪽 전문 열람을 해제할까요?`))return;try{const result=await api('/api/readers/remove',{email:r.email});renderReaders(result);$('#reader-status').textContent=result.message;}catch(error){$('#reader-status').textContent=error.message;}};
        row.append(who,remove);list.append(row);
    }
    $('#admin-list').textContent=data.admins.length?data.admins.join(', '):'관리자 토큰으로만 들어와 있습니다.';
}
async function loadReaders(){$('#reader-status').textContent='';try{renderReaders(await api('/api/readers'));}catch(error){$('#reader-status').textContent=error.message;}}
$('#reader-form').onsubmit=async event=>{
    event.preventDefault();const email=$('#reader-email').value.trim(),note=$('#reader-note').value.trim();if(!email)return;
    try{const data=await api('/api/readers',{email,note});$('#reader-email').value='';$('#reader-note').value='';renderReaders(data);$('#reader-status').textContent=data.message;}
    catch(error){$('#reader-status').textContent=error.message;}
};
function readableQuote(quote,blocks){
    const needle=quote.replace(/\s/g,'').toLowerCase();
    for(const block of blocks){
        const chars=[],positions=[];
        for(let i=0;i<block.text.length;i++)if(!/\s/.test(block.text[i])){chars.push(block.text[i].toLowerCase());positions.push(i);}
        const start=chars.join('').indexOf(needle);
        if(start>=0)return block.text.slice(positions[start],positions[start+needle.length-1]+1);
    }
    return quote.replace(/\s+/g,' ').trim();
}
async function openSource(id,quote=''){
    try{
        const source=await api('/api/pages/'+id);$('#source-title').textContent=source.title;$('#source-page').textContent=pageLabel(source);
        const target=$('#source-text');target.replaceChildren();
        const quotes=Array.isArray(quote)?quote:quote?[quote]:[];
        if(quotes.length){target.append(el('h3','이 설명의 근거'));for(const q of quotes)target.append(el('blockquote',readableQuote(q,source.reading_blocks||[]),'selected-quote'));}
        $('#source-help').hidden=Boolean(source.restricted);
        if(source.restricted){
            // 개론서는 판매 중인 책이라, 공개 서재에서는 책과 쪽까지만 보여 준다.
            target.append(closedNotice(`이 쪽의 내용은 책의 ${source.printed_page?source.printed_page+'쪽':'해당 쪽'}에서 확인하실 수 있습니다.`,()=>openSource(id,quote)));
            $('#verify-status').textContent=qualityLabel(source);if(!$('#source-dialog').open)$('#source-dialog').showModal();target.scrollTop=0;return;
        }
        const blocks=source.reading_blocks||[];
        for(const block of blocks){
            if(block.kind==='body'){
                // Whole paragraph, in order. Sentences with visible OCR damage stay in place but are flagged.
                if(block.heading)target.append(el('p',block.heading,'source-heading'));
                const p=el('p',undefined,'source-full-text');
                for(const seg of block.segments||[{text:block.text,suspect:false}]){
                    if(seg.suspect){const span=el('span',seg.text,'suspect');span.title='글자 오인식이 의심되는 문장입니다. 아래 교정 전 추출문이나 원문 이미지와 대조하세요.';p.append(span);}
                    else p.append(document.createTextNode(seg.text));
                    p.append(document.createTextNode(' '));
                }
                target.append(p);
            }
            else if(block.kind==='table')target.append(renderTable(block,'표 · 띄어쓰기 자동 정리'));
        }
        if(source.corrections)target.append(el('p',`오인식이 확인된 낱말 ${source.corrections}곳을 화면에서만 바로잡았습니다. 추출문과 인용은 원래 글자를 유지합니다.`,'small muted'));
        const notes=blocks.filter(b=>b.kind==='note');
        if(notes.length){const aside=el('div',undefined,'source-notes');aside.append(el('p','여백 주석','source-table-caption'));for(const note of notes)aside.append(el('p',note.text));target.append(aside);}
        const exercises=blocks.filter(b=>b.kind==='exercise');
        if(exercises.length){const box=el('details',undefined,'source-exercises');box.append(el('summary','이 쪽의 학습활동 · 설명이 아니므로 검색에서 제외'));for(const item of exercises)box.append(el('p',item.text));target.append(box);}
        if(source.quality==='review')target.append(el('p','이 페이지는 OCR을 다시 수행한 뒤에도 오인식이 많습니다. 인용 전 원문 이미지를 확인하세요.','notice'));
        const details=el('details');details.open=!blocks.length;details.append(el('summary','교정 전 추출문 확인'),el('pre',source.original_text||source.text,'source-raw-text'));target.append(details);
        $('#verify-status').textContent=qualityLabel(source)+(source.method&&source.method!=='embedded'?' · 한국어 OCR 재수행 결과':'');if(!$('#source-dialog').open)$('#source-dialog').showModal();target.scrollTop=0;
    }catch(error){notice(error.message,true);}
}
// 용어 카드: every term of the books' back-of-book indexes as a tile. A tile opens the same
// cards a question naming the term gets — the written concept entry, then the index card.
const AREAS=[[1,'문식성','literacy'],[2,'문법','grammar'],[4,'문학','literature']];
// 7 = any of 정의(1), 개념 정리(2), 풀이(4): a card that says what the term is.
const SCOPES={7:'설명 있는 카드',0:'모든 용어'};
const INITIALS=['ㄱ','ㄴ','ㄷ','ㄹ','ㅁ','ㅂ','ㅅ','ㅇ','ㅈ','ㅊ','ㅋ','ㅌ','ㅍ','ㅎ','A–Z','기타'];
const CHO='ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ',PLAIN_CHO='ㄱㄱㄴㄷㄷㄹㅁㅂㅂㅅㅅㅇㅈㅈㅊㅋㅌㅍㅎ';
const PAGE=240;
const termsState={items:null,loading:null,scope:7,area:0,initial:'',query:'',shown:PAGE};
// Same spelling rule as term_index.key_of, so 재귀 대명사 and 재귀대명사 find each other.
const termKey=text=>text.replace(/[\s\-‘’'"·]/g,'').toLowerCase();
function initialOf(label){
    const ch=label.replace(/^[^가-힣ㄱ-ㅎA-Za-z0-9]+/,'')[0]||'',code=ch.charCodeAt(0);
    if(code>=0xAC00&&code<=0xD7A3)return PLAIN_CHO[Math.floor((code-0xAC00)/588)];
    const jamo=CHO.indexOf(ch);if(jamo>=0)return PLAIN_CHO[jamo];
    return /[A-Za-z]/.test(ch)?'A–Z':'기타';
}
// The list and every card written ahead of time (scripts/build_term_cards.py) and served by
// Hosting, so opening them never waits for the server to wake. The local app does not serve
// them — a concept just edited must show at once — and then the server is asked, as before.
async function prebuilt(path){try{const r=await fetch(path);return r.ok?await r.json():null;}catch{return null;}}
// Same name as build_term_cards.file_name: the first 16 hex digits of SHA-1 over the label.
async function termFile(label){const hash=await crypto.subtle.digest('SHA-1',new TextEncoder().encode(label));return [...new Uint8Array(hash,0,8)].map(b=>b.toString(16).padStart(2,'0')).join('');}
const termCards=new Map();
function fetchTermCard(label){
    // The files carry no sentence of a book, so a let-in account asks the server for the card with
    // its quotes, and falls back to the file if the server does not answer. Signing in or out
    // changes which one is wanted, so each is kept apart.
    const full=readsQuotes(),key=(full?'full:':'')+label,ask=()=>api('/api/terms/card?q='+encodeURIComponent(label));
    const file=()=>termFile(label).then(name=>prebuilt(`/terms/c/${name}.json`),()=>null);
    if(!termCards.has(key))termCards.set(key,(full?ask().catch(()=>file()).then(data=>data||ask()):file().then(data=>data||ask()))
        .catch(error=>{termCards.delete(key);throw error;}));
    return termCards.get(key);
}
function loadTerms(){
    if(termsState.items)return Promise.resolve(termsState.items);
    termsState.loading??=prebuilt('/terms/index.json').then(data=>data||api('/api/terms')).then(data=>{
        termsState.items=data.items.map(([label,areas,books,flags])=>({label,areas,books,flags,compact:termKey(label),initial:initialOf(label)}));
        return termsState.items;
    }).finally(()=>{termsState.loading=null;});
    return termsState.loading;
}
function termTile(t){
    const tile=el('button',undefined,'term-tile');tile.type='button';
    tile.append(el('span',t.label,'term-tile-label'));
    const meta=el('span',undefined,'term-tile-meta'),areas=AREAS.filter(a=>t.areas&a[0]);
    for(const [,,cls] of areas)meta.append(el('span',undefined,'category-dot '+cls));
    meta.append(el('span',`${areas.map(a=>a[1]).join('·')} · 책 ${t.books}권`));tile.append(meta);
    const tags=el('span',undefined,'term-tile-tags');
    if(t.flags&4)tags.append(el('span','풀이','term-tag note'));
    if(t.flags&1)tags.append(el('span','정의','term-tag'));
    if(t.flags&2)tags.append(el('span','개념 정리','term-tag concept'));
    if(tags.childNodes.length)tile.append(tags);
    // Asked for as the pointer rests or presses on a tile, the card is usually in by the click.
    const prefetch=()=>fetchTermCard(t.label).catch(()=>{});let resting;
    tile.onpointerenter=()=>{resting=setTimeout(prefetch,120);};tile.onpointerleave=()=>clearTimeout(resting);tile.onpointerdown=prefetch;
    tile.onclick=()=>openTermCard(t);return tile;
}
function renderTermsView(){
    const {items,scope,area}=termsState;if(!items)return;
    const q=termKey(termsState.query);
    const base=items.filter(t=>(!area||t.areas&area)&&(!q||t.compact.includes(q)));
    for(const b of document.querySelectorAll('#terms-scope button')){const s=Number(b.dataset.scope);b.querySelector('b').textContent=number(base.filter(t=>!s||t.flags&s).length);b.setAttribute('aria-pressed',String(s===scope));}
    for(const b of document.querySelectorAll('#terms-area button'))b.setAttribute('aria-pressed',String(Number(b.dataset.area)===area));
    const scoped=base.filter(t=>!scope||t.flags&scope);
    const counts=new Map();for(const t of scoped)counts.set(t.initial,(counts.get(t.initial)||0)+1);
    if(termsState.initial&&!counts.get(termsState.initial))termsState.initial='';
    const bar=$('#terms-initials');bar.replaceChildren();
    for(const label of ['전체',...INITIALS]){
        const value=label==='전체'?'':label,n=value?counts.get(value)||0:scoped.length;
        const b=el('button',label);b.type='button';b.title=`${number(n)}개`;b.disabled=!n;b.setAttribute('aria-pressed',String(value===termsState.initial));
        b.onclick=()=>{termsState.initial=value;termsState.shown=PAGE;renderTermsView();};bar.append(b);
    }
    const list=termsState.initial?scoped.filter(t=>t.initial===termsState.initial):scoped;
    const where=[AREAS.find(a=>a[0]===area)?.[1]||'전체 영역',SCOPES[scope]+(termsState.initial?` · ${termsState.initial}`:'')];
    if(termsState.query.trim())where.push(`'${termsState.query.trim()}' 포함`);
    $('#terms-count').textContent=`${where.join(' · ')} ${number(list.length)}개`;
    const grid=$('#terms-grid'),frag=document.createDocumentFragment();
    for(const t of list.slice(0,termsState.shown))frag.append(termTile(t));
    grid.replaceChildren(frag);
    if(!list.length)grid.append(el('p',scope&&q?'이 조건에는 없습니다. 보기를 ‘모든 용어’로 넓혀 보세요.':'조건에 맞는 용어가 없습니다. 검색어를 줄이거나 영역을 넓혀 보세요.','notice'));
    const more=$('#terms-more'),left=list.length-termsState.shown;
    more.hidden=left<=0;more.textContent=`더 보기 (남은 ${number(left)}개)`;
}
let termCardSeq=0;
async function openTermCard(t){
    const dialog=$('#term-dialog'),body=$('#term-dialog-body'),seq=++termCardSeq;
    $('#term-dialog-title').textContent=t.label;
    // Each section below says for itself whether AI wrote it (the 풀이) or not (the books' own sentences).
    $('#term-dialog-meta').textContent=`${AREAS.filter(a=>t.areas&a[0]).map(a=>a[1]).join(' · ')} · 개론서 ${t.books}권`;
    body.replaceChildren(el('p','카드를 불러오는 중입니다.','small muted'));
    if(!dialog.open)dialog.showModal();
    try{
        const data=await fetchTermCard(t.label);
        if(seq!==termCardSeq)return;
        const concepts=el('div'),terms=el('div');
        renderConcepts(data.concepts,concepts,'이 용어만 다룬 정리는 아직 없습니다. 관련 개념 정리 보기: ');renderTerms(data.terms,terms);
        // Where the books' own sentences would stand, the notice says why they are not shown.
        const hidden=data.quotes_hidden&&(data.note?.citations?.length||data.terms?.some(term=>term.sources.some(s=>s.defines)));
        const closed=hidden?[closedNotice('풀이와 개념 정리, 근거가 실린 책과 쪽은 그대로 보실 수 있습니다.',()=>{if(seq===termCardSeq)openTermCard(t);})]:[];
        body.replaceChildren(...(data.note?[renderNote(data.note)]:[]),concepts,...closed,terms);
    }catch(error){if(seq===termCardSeq)body.replaceChildren(el('p',error.message,'notice error'));}
}
function renderNote(note){
    // Written ahead of time from the books' paragraphs (scripts/write_term_notes.py); every quote was checked against them.
    const card=el('article',undefined,'concept-card note-card');
    const head=el('div',undefined,'concept-head');head.append(el('span','풀이','badge'),el('h3',note.label),el('span','AI가 미리 씀 · 검수 전','badge concept-status'));card.append(head);
    const body=el('div',undefined,'concept-body');
    body.append(el('p',note.definition,'note-definition'));
    if(note.explanation?.length){const ul=el('ul',undefined,'note-explanation');for(const s of note.explanation)ul.append(el('li',s));body.append(ul);}
    if(note.examples?.length){const p=el('p',undefined,'note-examples');p.append(el('strong','예'),document.createTextNode(' '+note.examples.join(' · ')));body.append(p);}
    const quoted=note.citations.some(c=>c.quote);
    const foot=el('div',undefined,'concept-sources');foot.append(el('p',quoted?'근거 · 누르면 그 쪽을 열고 근거 구절을 표시합니다.':'근거 · 풀이를 쓸 때 읽은 책과 쪽입니다.','small muted'));
    const pages=new Map();for(const c of note.citations){if(!pages.has(c.id))pages.set(c.id,{source:c,quotes:[]});if(c.quote)pages.get(c.id).quotes.push(c.quote);}
    const row=el('div',undefined,'inline-citations');for(const {source,quotes} of pages.values())row.append(referenceButton(source,quotes));foot.append(row);
    foot.append(el('p',`개론서 문단만 근거로 AI(${note.model||'언어 모델'})가 미리 쓴 풀이입니다. 보는 동안에는 AI를 쓰지 않습니다. 인용하기 전에 원문 쪽을 확인하세요.`,'small muted'));
    body.append(foot);card.append(body);return card;
}
const viewOfHash=()=>location.hash==='#terms'?'terms':location.hash==='#admin'?'admin':'search';
function showView(name,push=true){
    for(const view of ['search','terms','admin']){const on=view===name;$(`#${view}-view`).hidden=!on;const b=$('#nav-'+view);b.classList.toggle('active',on);if(on)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');}
    // The back button returns from the cards (or the admin page) to the question page.
    const hash=name==='search'?'':'#'+name;
    if(push&&location.hash!==hash)history.pushState(null,'',hash||location.pathname+location.search);
    if(name==='search')return;
    window.scrollTo(0,0);
    if(name==='admin')return loadReaders();
    loadTerms().then(renderTermsView).catch(error=>{$('#terms-count').textContent=error.message;});
}
window.addEventListener('popstate',()=>showView(viewOfHash(),false));
let termsTyping=null;
$('#terms-filter').addEventListener('input',event=>{clearTimeout(termsTyping);termsTyping=setTimeout(()=>{termsState.query=event.target.value;termsState.initial='';termsState.shown=PAGE;renderTermsView();},120);});
document.querySelectorAll('#terms-scope button').forEach(b=>b.onclick=()=>{termsState.scope=Number(b.dataset.scope);termsState.shown=PAGE;renderTermsView();});
document.querySelectorAll('#terms-area button').forEach(b=>b.onclick=()=>{termsState.area=Number(b.dataset.area);termsState.shown=PAGE;renderTermsView();});
$('#terms-more').onclick=()=>{termsState.shown+=PAGE;renderTermsView();};
window.addEventListener('beforeinstallprompt',event=>{event.preventDefault();installPrompt=event;$('#install').hidden=false;});$('#install').onclick=async()=>{if(installPrompt){await installPrompt.prompt();installPrompt=null;$('#install').hidden=true;}};
if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});
window.addEventListener('offline',()=>notice('오프라인입니다. AI 해설은 서버에 다시 연결된 뒤 사용할 수 있습니다.'));
// The brand link means "back to the start", so it drops the saved answer instead of reopening it.
$('.brand').addEventListener('click',()=>saveAsk(null));
const restored=savedAsk();
if(restored?.question){
    $('#question').value=restored.question;if(restored.category)$('#category').value=restored.category;
    // Drawn before the page finishes loading, so the browser can put the reader back at the same scroll position.
    if(restored.data?.ai_used)renderResults(restored.data,true);
    else if(restored.job)ask(restored.question,restored.category,restored.mode,restored);
}
if(location.hash==='#terms')showView('terms',false);
loadStatus().then(()=>{if(location.hash==='#admin'&&statusData?.admin)showView('admin',false);});
setInterval(()=>{if(!document.hidden)loadStatus();},15000);

