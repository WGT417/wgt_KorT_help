"""Merge rewritten entries (scratchpad/entries/*.json, each with a "_file" key) into concepts/<file>.json,
replacing the entry with the same id in place and dropping legacy fields; then run the checker."""
import sys,json,glob,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
LEGACY={'explanation','steps','examples','counter_examples','common_errors'}
KEEP_ORDER=['id','label','parent','era','aliases','summary','sections','confused_with','standards','sources','review']
files={}
only=set(sys.argv[1:])
for path in sorted((HERE/'entries').glob('*.json')):
    if only and path.stem not in only:continue
    new=json.loads(path.read_text(encoding='utf-8'));target=new.pop('_file')
    d=files.get(target) or json.loads((ROOT/'concepts'/target).read_text(encoding='utf-8'));files[target]=d
    old=next((c for c in d['concepts'] if c['id']==new['id']),None)
    merged={}
    for k in KEEP_ORDER:
        if k in new:merged[k]=new[k]
        elif old and k in old and k not in LEGACY:merged[k]=old[k]
    for k in new:
        if k not in merged:merged[k]=new[k]
    if old:d['concepts'][d['concepts'].index(old)]=merged
    else:d['concepts'].append(merged)
    d['schema']=2
    print('merged',target,new['id'],'sections',len(merged.get('sections',[])),'sources',len(merged.get('sources',[])))
for target,d in files.items():
    (ROOT/'concepts'/target).write_text(json.dumps(d,ensure_ascii=False,indent=1),encoding='utf-8')
r=subprocess.run([sys.executable,str(ROOT/'scripts'/'check_concepts.py')],capture_output=True,text=True,encoding='utf-8')
print(r.stdout[-1500:],r.stderr[-800:]);sys.exit(r.returncode)
