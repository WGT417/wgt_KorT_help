from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / '개론서 파일'
manifest = []
for source in sorted(BASE.rglob('*.pdf')):
    source = source.resolve()
    assert source.is_relative_to(BASE.resolve())
    if '요약본' in source.parts:
        manifest.append({'action': 'delete-summary', 'source': str(source.relative_to(ROOT)), 'bytes': source.stat().st_size})
        continue
    name = source.name
    if name.startswith('2022'):
        category = '참고자료'
    elif any(word in name for word in ['문법', '국어사', '음운론']):
        category = '문법'
    elif any(word in name for word in ['독서', '작문', '화법', '의사소통']):
        category = '문식성'
    else:
        category = '문학'
    target = (BASE / category / name).resolve()
    assert target.is_relative_to(BASE.resolve())
    if source != target:
        assert not target.exists(), f'Duplicate: {target}'
        manifest.append({'action': 'move', 'source': str(source.relative_to(ROOT)), 'target': str(target.relative_to(ROOT)), 'bytes': source.stat().st_size})

(ROOT / 'data').mkdir(exist_ok=True)
record = ROOT / 'data' / 'organization.json'
if manifest:
    record.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
for item in manifest:
    source = ROOT / item['source']
    if item['action'] == 'move':
        target = ROOT / item['target']
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
    else:
        source.unlink()
for directory in sorted(BASE.rglob('*'), key=lambda p: len(p.parts), reverse=True):
    if directory.is_dir() and not any(directory.iterdir()):
        directory.rmdir()
print(json.dumps({'moved': sum(i['action']=='move' for i in manifest), 'deleted_summaries': sum(i['action']=='delete-summary' for i in manifest)}, ensure_ascii=False))
