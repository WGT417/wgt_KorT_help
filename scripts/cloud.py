"""One tool for the Google Cloud side: data sync and deployment.

    python scripts/cloud.py setup                 # once per project: APIs, bucket, image repository
    python scripts/cloud.py push-data             # upload data/ (this computer -> bucket)
    python scripts/cloud.py pull-data             # download data/ (bucket -> this computer)
    python scripts/cloud.py deploy [--openai-key K] [--admin-token T]
                                                  # build in Cloud Build (data fetched from the bucket) and deploy to Cloud Run
    python scripts/cloud.py url                   # print the Cloud Run URL

Settings live in deploy.json (project, region, service, bucket). Requires the
gcloud CLI, logged in with `gcloud init`. Secrets are never written to disk here:
pass --openai-key / --admin-token only on the first deploy (or to rotate them);
later deploys keep the environment variables of the previous revision.
"""
import argparse, json, os, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'deploy.json'
# Never synced: SQLite side files, temporary extraction folders, audit screenshots.
SYNC_EXCLUDE = r'(^|/)(tmp[^/]*|.*\.sqlite3-(wal|shm)|.*\.png)$'


def load_config():
    config = json.loads(CONFIG.read_text(encoding='utf-8'))
    if not config.get('project'):
        sys.exit('deploy.json의 "project"에 Firebase 프로젝트 ID를 적어 주세요 (Firebase 콘솔 → 프로젝트 설정 → 일반).')
    config.setdefault('bucket', '') or config.update(bucket=f"{config['project']}-library")
    return config


def gcloud():
    exe = shutil.which('gcloud') or shutil.which('gcloud.cmd')
    if not exe:
        sys.exit('gcloud CLI를 찾을 수 없습니다. https://cloud.google.com/sdk/docs/install 에서 설치한 뒤 새 터미널에서 `gcloud init`을 실행하세요.')
    if exe.lower().endswith(('.cmd', '.bat')):
        # Windows: gcloud.cmd runs through cmd.exe, which treats | ( ) ^ in arguments
        # (e.g. the rsync --exclude regex) as its own operators. Call the SDK's Python
        # entry point directly instead, with the interpreter the SDK itself uses.
        script = Path(exe).resolve().parent.parent / 'lib' / 'gcloud.py'
        if script.exists():
            return [os.environ.get('CLOUDSDK_PYTHON') or sys.executable, str(script)]
    return [exe]


def run(*args, capture=False, check=True):
    command = [*gcloud(), *args]
    shown = ['gcloud', *args]
    if '--update-env-vars' in shown:  # never echo secrets
        shown[shown.index('--update-env-vars') + 1] = '<secrets>'
    print('$', ' '.join(a if ' ' not in a else f'"{a}"' for a in shown), flush=True)
    result = subprocess.run(command, cwd=ROOT, text=True, encoding='utf-8', capture_output=capture)
    if check and result.returncode:
        sys.exit(result.returncode)
    return result.stdout.strip() if capture else result.returncode


def image_name(config):
    return f"{config['region']}-docker.pkg.dev/{config['project']}/{config['repository']}/app"


def setup(config):
    project = ['--project', config['project']]
    run('services', 'enable', 'run.googleapis.com', 'cloudbuild.googleapis.com', 'artifactregistry.googleapis.com',
        'firestore.googleapis.com', 'storage.googleapis.com', *project)
    if run('storage', 'buckets', 'describe', f"gs://{config['bucket']}", *project, capture=True, check=False) == '':
        run('storage', 'buckets', 'create', f"gs://{config['bucket']}", '--location', config['region'],
            '--uniform-bucket-level-access', '--public-access-prevention', *project)
    if run('artifacts', 'repositories', 'describe', config['repository'], '--location', config['region'], *project, capture=True, check=False) == '':
        run('artifacts', 'repositories', 'create', config['repository'], '--repository-format', 'docker',
            '--location', config['region'], *project)
    print(f"\n준비 완료. 버킷 gs://{config['bucket']}, 이미지 저장소 {image_name(config)}")


def sync(config, direction):
    local, remote = str(ROOT / 'data'), f"gs://{config['bucket']}/data"
    source, target = (local, remote) if direction == 'push' else (remote, local)
    if direction == 'push' and not (ROOT / 'data' / 'library.sqlite3').exists():
        sys.exit('data/library.sqlite3가 없습니다. 자료가 있는 컴퓨터에서 push-data를 실행하세요.')
    (ROOT / 'data').mkdir(exist_ok=True)
    # --delete-unmatched-destination-objects keeps both sides identical (a rebuilt
    # library replaces the old one). Nothing outside data/ is ever touched.
    run('storage', 'rsync', '--recursive', '--delete-unmatched-destination-objects',
        '--exclude', SYNC_EXCLUDE, source, target, '--project', config['project'])
    print(f"\n{'올렸습니다' if direction == 'push' else '받았습니다'}: {source} -> {target}")


def deploy(config, openai_key, admin_token):
    image = image_name(config)
    project = ['--project', config['project']]
    run('builds', 'submit', '--config', 'cloudbuild.yaml', '--region', config['region'],
        '--substitutions', f"_BUCKET={config['bucket']},_IMAGE={image}", *project)
    args = ['run', 'deploy', config['service'], '--image', image, '--region', config['region'], '--platform', 'managed',
            '--allow-unauthenticated', '--memory', config['memory'], '--cpu', str(config['cpu']),
            '--max-instances', str(config['max_instances']), '--min-instances', str(config['min_instances']),
            '--timeout', str(config['timeout']), '--concurrency', '8', *project]
    env = {k: v for k, v in (('OPENAI_API_KEY', openai_key), ('ADMIN_TOKEN', admin_token)) if v}
    if env:
        # ^|^ makes | the separator so a key containing a comma cannot break the list.
        args += ['--update-env-vars', '^|^' + '|'.join(f'{k}={v}' for k, v in env.items())]
    run(*args)
    print('\n배포 주소:', url(config))


def url(config):
    return run('run', 'services', 'describe', config['service'], '--region', config['region'],
               '--project', config['project'], '--format', 'value(status.url)', capture=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('setup', 'push-data', 'pull-data', 'url'):
        sub.add_parser(name)
    d = sub.add_parser('deploy')
    d.add_argument('--openai-key', default='')
    d.add_argument('--admin-token', default='')
    args = parser.parse_args()
    config = load_config()
    if args.command == 'setup': setup(config)
    elif args.command == 'push-data': sync(config, 'push')
    elif args.command == 'pull-data': sync(config, 'pull')
    elif args.command == 'deploy': deploy(config, args.openai_key, args.admin_token)
    elif args.command == 'url': print(url(config))


if __name__ == '__main__':
    main()
