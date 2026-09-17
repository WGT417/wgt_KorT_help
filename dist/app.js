'use strict';
const $=s=>document.querySelector(s);
let statusData=null,csrf='',installPrompt=null;
const number=n=>Number(n||0).toLocaleString('ko-KR');
function el(tag,text,cls){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;}
function notice(text,isError=false){const target=$('#feedback');target.replaceChildren();if(text)target.append(el('p',text,'notice'+(isError?' error':'')));}
let adminToken='';try{adminToken=localStorage.getItem('adminToken')||'';}catch{}
function authHeaders(extra={}){return adminToken?{...extra,'X-Admin-Token':adminToken}:extra;}
async function api(path,body,retried=false){const response=await fetch(path,body===undefined?{headers:authHeaders()}:{method:'POST',headers:authHeaders({'Content-Type':'application/json','X-CSRF-Token':csrf}),body:JSON.stringify(body)});const result=await response.json();if(!response.ok){if(response.status===403&&result.csrf_expired&&!retried&&body!==undefined){await loadStatus();return api(path,body,true);}throw new Error(result.error||'요청을 처리하지 못했습니다.');}if(path==='/api/status'){$('#settings-open').hidden=result.public?false:Boolean(result.key_configured);$('#settings-label').textContent=result.public?'관리자':'연결 설정';}return result;}
function quotaText(q){if(!q)return '';if(q.admin)return '관리자 · AI 해설 제한 없음';if(q.unavailable)return 'AI 해설 일시 중단';if(q.unlimited)return '';return `오늘 남은 AI 해설 ${q.remaining}회 / ${q.limit}회`;}
function showQuota(q){if(!q||q.unlimited)return;const text=quotaText(q);if(text)$('#side-connection').textContent=text;$('#connection-dot').classList.toggle('off',Boolean(q.unavailable||q.remaining===0));}
async function loadStatus(){try{statusData=await api('/api/status');csrf=statusData.csrf;const books=statusData.books;for(const cat of ['문식성','문법','문학']){const count=books.filter(b=>b.category===cat).length;$('#count-'+cat).textContent=count;$('#card-count-'+cat).textContent=count+'권';}const done=books.reduce((a,b)=>a+b.processed,0),total=books.reduce((a,b)=>a+b.pages,0);$('#index-title').textContent=`${books.length}권의 개론서를 함께 살펴봅니다`;$('#index-detail').textContent=`${number(statusData.reading_pages)} / ${number(total)}페이지 문단 정리 · 띄어쓰기 자동 처리${statusData.semantic_search?' · 뜻으로도 찾기':''}`;$('#index-badge').textContent=statusData.ocr?.status==='running'?`OCR 보완 ${statusData.ocr.done}/${statusData.ocr.total}`:statusData.reading_pages===total&&total?'문단 정리 완료':'문단 정리 중';$('#side-connection').textContent=statusData.key_configured?(statusData.public?'AI 해설 사용 가능':'OpenAI 키 연결됨'):'원문 검색 사용 가능';$('#mode-label').textContent=statusData.public?(statusData.admin?'공개 서재 · 관리자':'공개 서재 · AI 해설 하루 '+(statusData.quota?.limit??3)+'회'):'개인 로컬 서재';$('#key-section').hidden=Boolean(statusData.public);$('#admin-section').hidden=!statusData.public;$('#settings-title').textContent=statusData.public?'관리자 설정':'OpenAI 자동 연결';if(statusData.key_configured)showQuota(statusData.quota);if(!$('#settings-dialog').open)$('#key-status').textContent=statusData.key_configured?'키가 연결되어 있습니다. 첫 해설 요청에서 API 사용 가능 여부를 확인합니다.':'현재 연결된 키가 없습니다.';$('#admin-status').textContent=statusData.admin?'관리자 토큰이 확인되었습니다.':adminToken?'저장된 토큰이 서버와 일치하지 않습니다.':'현재 관리자 토큰이 없습니다.';}catch(error){notice(statusData?.public?'서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.':'로컬 서버에 연결할 수 없습니다. 앱 실행 파일로 서버를 시작해 주세요.',true);$('#side-connection').textContent='서버 연결 안 됨';}}
function chooseCategory(category){$('#category').value=category;$('#question').focus();}
function pageLabel(s){return s.printed_page?`책 ${s.printed_page}쪽 · 자료 ${s.pdf_page}페이지`:`자료 ${s.pdf_page}페이지 · 책 쪽수 미확인`;}
function qualityLabel(s){return s.number_status==='manual'?'책 쪽수 원문 대조 완료':s.number_status==='sequence'?'책 쪽수 연속 번호로 자동 확인':'책 쪽수 확인 전 · 자료 페이지 기준';}
function referenceButton(source,quote=''){
    const quotes=Array.isArray(quote)?quote:quote?[quote]:[];
    const button=el('button',`${source.title} · ${source.printed_page?'책 '+source.printed_page+'쪽':'자료 '+source.pdf_page+'페이지'}${quotes.length>1?' · 근거 '+quotes.length+'곳':''}`,'reference-button citation-chip');
    button.type='button';button.title=pageLabel(source)+(quotes.length?'\n'+quotes.join('\n\n'):'');
    button.onclick=()=>openSource(source.id,quote);return button;
}
function appendCitations(target,citations,sources){
    const span=el('span',undefined,'inline-citations');
    const grouped=new Map();
    for(const citation of citations||[]){if(!grouped.has(citation.source_id))grouped.set(citation.source_id,[]);const quotes=grouped.get(citation.source_id);if(!quotes.includes(citation.quote))quotes.push(citation.quote);}
    for(const [id,quotes] of grouped){const source=sources.find(s=>s.source_id===id);if(source)span.append(referenceButton(source,quotes));}
    target.append(span);
}
function renderPoints(target,points,sources){
    for(const point of points||[]){
        const block=el('div',undefined,'explanation-point');const p=el('p');
        if(point.label)p.append(el('strong',point.label+' '));
        p.append(document.createTextNode(point.text));block.append(p);
        if(point.examples?.length){const examples=el('ul',undefined,'example-list');for(const example of point.examples)examples.append(el('li',example));block.append(examples);}
        appendCitations(block,point.citations,sources);target.append(block);
    }
}
function renderExplanation(answer,sources){
    const article=el('article',undefined,'explanation');article.append(el('h3',answer.title,'explanation-title'));
    for(const section of answer.sections||[]){
        const part=el('section',undefined,'explanation-section');part.append(el('h4',section.title));renderPoints(part,section.points,sources);
        for(const sub of section.subsections||[]){const child=el('section',undefined,'explanation-subsection');child.append(el('h5',sub.title));renderPoints(child,sub.points,sources);part.append(child);}
        article.append(part);
    }
    if(answer.summary?.rows?.length){
        const section=el('section',undefined,'summary-section');section.append(el('h4','종합 일람표'));
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
    const label=`${source.title||source.book} · ${source.printed_page?'책 '+source.printed_page+'쪽':'자료 '+source.pdf_page+'페이지'}`;
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
function renderConcepts(concepts){
    const target=$('#concepts');target.replaceChildren();
    if(!concepts?.length)return;
    for(const c of concepts)conceptLabels.set(c.id,c.label);
    const exact=concepts.filter(c=>c.match!=='related'),related=concepts.filter(c=>c.match==='related');
    if(exact.length){
        const heading=el('div',undefined,'section-heading concept-heading');heading.append(el('h3','개념 정리'),el('span','미리 작성한 정리 · AI 미사용','small muted'));target.append(heading);
        for(const entry of exact)target.append(renderConcept(entry));
    }
    if(related.length){
        // A broader entry that only contains the asked word is offered, not shown as the answer.
        const row=el('p',undefined,'concept-related');row.append(document.createTextNode('질문한 개념의 정리는 아직 없습니다. 상위 개념 정리 보기: '));
        for(const entry of related){const b=el('button',`${entry.label} (${entry.parent||entry.area})`,'citation-chip');b.type='button';b.onclick=()=>{row.after(renderConcept(entry));b.disabled=true;};row.append(b);}
        target.append(row);
    }
}
function renderTerms(terms){
    // Straight from the books' back-of-book indexes: the sentences that define or explain the term (definitions first), then the other pages that list it.
    const target=$('#concepts');
    for(const term of terms||[]){
        const card=el('article',undefined,'concept-card term-card');
        const head=el('div',undefined,'concept-head');head.append(el('span','찾아보기','badge'),el('h3',term.label));
        const books=new Set(term.sources.map(s=>s.book)).size,defined=term.sources.filter(s=>s.quote).length;head.append(el('span',`개론서 ${books}권 · 정의 ${defined}곳 · AI 미사용`,'concept-parent'));card.append(head);
        if(term.variants.length>1)card.append(el('p','표기: '+term.variants.join(' · '),'small muted'));
        const quoted=term.sources.filter(s=>s.quote),others=term.sources.filter(s=>!s.quote);
        if(quoted.length){
            const list=el('div',undefined,'term-sources');
            for(const s of quoted){
                const row=el('div',undefined,'term-source');row.append(conceptSourceButton(s));
                if(!s.indexed)row.append(el('span','찾아보기 밖','term-tag'));
                if(s.ocr)row.append(el('span','오인식 있음','term-tag warn'));
                row.append(el('p',s.quote,'term-quote'));list.append(row);
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
function renderResults(data){
    $('#welcome').hidden=true;$('#results').hidden=false;
    renderConcepts(data.concepts);renderTerms(data.terms);
    $('#result-title').textContent=data.question;$('#route-badge').textContent=data.ai_used?'개론서 근거 기반 해설':'원문 검색';
    $('#route-reason').textContent=data.ai_used?'각 설명의 출처를 누르면 인용한 원문을 확인할 수 있습니다.':data.route_reason;notice(data.notice);
    if(data.quota)showQuota(data.quota);
    const quotaLeft=data.quota&&!data.quota.admin&&!data.quota.unlimited?data.quota.remaining:null;
    const escalate=$('#escalate');escalate.replaceChildren();
    if(!data.ai_used&&data.sources.length&&statusData?.key_configured&&quotaLeft!==0&&!data.quota?.unavailable){const go=el('button','이 개념 해설 보기 →','primary');go.type='button';go.onclick=()=>ask(data.question,$('#category').value,'reason');escalate.append(go,el('span','찾은 원문을 바탕으로 여러 개론서의 관점을 정리한 해설을 작성합니다. OpenAI API를 사용합니다.'+(quotaLeft!==null&&quotaLeft!==undefined?` 오늘 남은 해설 ${quotaLeft}회.`:''),'small muted'));}
    const answer=$('#answer');answer.replaceChildren();
    if(data.answer)answer.append(renderExplanation(data.answer,data.sources));
    const bookCount=new Set(data.sources.map(s=>s.book_id)).size;
    $('#source-count').textContent=`${bookCount}권 · ${data.sources.length}개 페이지`;
    $('#source-details').open=!data.ai_used;$('#source-details').querySelector('summary').firstChild.textContent=data.ai_used?'참고 원문 ':'질문과 관련된 본문 ';
    const target=$('#sources');target.replaceChildren();
    for(const s of data.sources){
        const card=el('article',undefined,'source-card');const meta=el('div',undefined,'source-meta');meta.append(el('span',s.category,'badge'),el('strong',s.title));if(s.match==='semantic')meta.append(el('span','뜻이 가까운 문단','badge meaning-badge'));meta.append(el('span',pageLabel(s),'page-label'));
        const bottom=el('div',undefined,'source-bottom');bottom.append(el('p',(s.match==='semantic'?'질문의 낱말이 그대로 나오지 않지만 의미가 가까워 찾은 문단 · ':'')+(s.quality==='review'?'글자 오인식이 많은 페이지 · 원문 이미지와 대조 필요':'띄어쓰기 자동 정리 · 원문 대조 가능')+(s.corrections?` · 오인식 낱말 ${s.corrections}곳 화면 교정`:'')),referenceButton(s,s.excerpt));card.append(meta,el('p',s.display_excerpt||s.excerpt.replace(/\s+/g,' ').trim(),'reading-passage'));
        for(const block of s.structured||[])card.append(renderTable(block,'같은 쪽의 표'));
        if(s.quality==='review')card.append(el('p','이 페이지는 OCR을 다시 수행한 뒤에도 오인식이 많습니다. 인용 전 원문 이미지를 확인하세요.','notice'));
        card.append(bottom);target.append(card);
    }
    $('#results').focus({preventScroll:true});$('#results').scrollIntoView({behavior:'auto',block:'start'});
}
async function ask(question,category,mode){const button=$('#ask-button');$('#answer').replaceChildren();$('#concepts').replaceChildren();$('#sources').replaceChildren();$('#escalate').replaceChildren();$('#results').hidden=true;button.disabled=true;button.textContent='근거 찾는 중…';$('#results').setAttribute('aria-busy','true');notice(mode==='reason'?'여러 개론서의 근거를 모아 해설을 작성하고 있습니다. 1분 남짓 걸릴 수 있습니다.':'여러 개론서에서 관련 내용을 찾고 있습니다. AI 해설은 시간이 조금 더 걸릴 수 있습니다.');try{const data=await api('/api/ask',{question,category,mode});if(data.question!==question)throw new Error('질문과 응답이 일치하지 않아 표시하지 않았습니다. 다시 질문해 주세요.');renderResults(data);}catch(error){notice(error.message,true);}finally{button.disabled=false;button.textContent='근거 찾기 →';$('#results').removeAttribute('aria-busy');}}
$('#question-form').addEventListener('submit',async event=>{event.preventDefault();if(!csrf){await loadStatus();if(!csrf)return;}await ask($('#question').value.trim(),$('#category').value,document.querySelector('input[name=mode]:checked').value);});
document.querySelectorAll('[data-category]').forEach(button=>button.onclick=()=>chooseCategory(button.dataset.category));
document.querySelectorAll('[data-question]').forEach(button=>button.onclick=()=>{$('#question').value=button.dataset.question;$('#category').value=button.dataset.question.includes('피동')?'문법':'전체';$('#question').focus();});
$('#nav-search').onclick=()=>$('#question').focus();
$('#settings-open').onclick=()=>{$('#api-key').value='';$('#key-status').textContent=statusData?.key_configured?'키 연결됨 · 첫 해설 요청에서 API를 확인합니다.':'현재 연결된 키가 없습니다.';$('#settings-dialog').showModal();};
document.querySelectorAll('[data-close]').forEach(button=>button.onclick=()=>document.getElementById(button.dataset.close).close());
$('#settings-dialog').addEventListener('close',()=>{$('#api-key').value='';});
$('#key-form').onsubmit=async event=>{event.preventDefault();const field=$('#api-key');const key=field.value.trim();field.value='';try{const data=await api('/api/key',{key});await loadStatus();$('#key-status').textContent=data.message;}catch(error){$('#key-status').textContent=error.message;}};
$('#disconnect').onclick=async()=>{try{const data=await api('/api/key',{key:''});await loadStatus();$('#key-status').textContent=data.message;}catch(error){$('#key-status').textContent=error.message;}};
function setAdminToken(value){adminToken=value;try{if(value)localStorage.setItem('adminToken',value);else localStorage.removeItem('adminToken');}catch{}}
$('#admin-form').onsubmit=async event=>{event.preventDefault();const field=$('#admin-token');const value=field.value.trim();field.value='';if(!value)return;setAdminToken(value);await loadStatus();if(!statusData?.admin){setAdminToken('');$('#admin-status').textContent='토큰이 일치하지 않아 저장하지 않았습니다.';}};
$('#admin-clear').onclick=async()=>{setAdminToken('');await loadStatus();$('#admin-status').textContent='관리자 토큰을 해제했습니다.';};
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
        const blocks=source.reading_blocks||[];
        for(const block of blocks){
            if(block.kind==='body'){
                // Whole paragraph, in order. Sentences with visible OCR damage stay in place but are flagged.
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
window.addEventListener('beforeinstallprompt',event=>{event.preventDefault();installPrompt=event;$('#install').hidden=false;});$('#install').onclick=async()=>{if(installPrompt){await installPrompt.prompt();installPrompt=null;$('#install').hidden=true;}};
if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});
window.addEventListener('offline',()=>notice('오프라인입니다. 새 원문 검색과 AI 해설은 로컬 서버 연결 후 사용할 수 있습니다.'));
const modeDescriptions={
    auto:'질문의 표현에 따라 원문 검색과 근거 기반 해설 중 하나를 선택합니다.',
    search:'관련 원문과 출처만 보여 줍니다. AI를 사용하지 않습니다.',
    reason:'찾은 원문을 바탕으로 AI가 개념을 설명하거나 여러 책의 내용을 비교합니다.'
};
function updateModeDescription(){const selected=document.querySelector('input[name="mode"]:checked');$('#question-help').textContent=modeDescriptions[selected.value];}
document.querySelectorAll('input[name="mode"]').forEach(input=>input.addEventListener('change',updateModeDescription));
updateModeDescription();
loadStatus();setInterval(()=>{if(!document.hidden)loadStatus();},15000);

