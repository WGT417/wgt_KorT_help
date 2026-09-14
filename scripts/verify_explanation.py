"""Opt-in live API check: uses the configured key; saves no credentials."""
import sys,json,time,argparse,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core,server
from explanation import collect_evidence
parser=argparse.ArgumentParser()
parser.add_argument('--live',action='store_true')
parser.add_argument('--query',default='어미의 종류에 대해 설명해줘')
parser.add_argument('--category',default='문법',choices=['문법','문식성','문학'])
args=parser.parse_args();query=args.query
if not args.live:raise SystemExit('Use --live to run the configured API.')
if not server.API_KEY:raise SystemExit('API key is not configured.')
start=time.perf_counter()
sources=core.search_pages(query,args.category)
print('Initial:',[(r['title'],r['pdf_page']) for r in sources],flush=True)
sources=collect_evidence(query,args.category,sources,server.openai_call,server.API_KEY)
print('Expanded:',len(sources),[(r['title'],r['pdf_page']) for r in sources],flush=True)
answer=server.reason(query,sources)
for r in sources:
    r.pop('text',None);r.pop('evidence_text',None)
result={'question':query,'route':'reason','route_reason':'','sources':sources,'answer':answer,'ai_used':True,'notice':''}
path=core.DATA/('explanation-verification-'+hashlib.sha256(query.encode()).hexdigest()[:10]+'.json')
path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print('Seconds:',round(time.perf_counter()-start,1),'Sections:',[s['title'] for s in answer['sections']],'Table rows:',len(answer['summary']['rows']),'Rejected:',answer['rejected_count'],flush=True)
