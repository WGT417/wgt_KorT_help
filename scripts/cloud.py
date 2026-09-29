"""One tool for the Google Cloud side: data sync and deployment.

    python scripts/cloud.py setup                 # once per project: APIs, bucket, image repository
    python scripts/cloud.py push-data             # upload data/ (this computer -> bucket)
    python scripts/cloud.py pull-data             # download data/ (bucket -> this computer)
    python scripts/cloud.py deploy [--openai-key K] [--admin-token T] [--admin-email E] [--no-hosting]
                                                  # build in Cloud Build (data fetched from the bucket) and deploy to Cloud Run,
                                                  # then `hosting` so the term cards match what was deployed
    python scripts/cloud.py hosting               # write the term cards (build_term_cards.py) and deploy dist/ to Firebase Hosting
    python scripts/cloud.py url                   # print the Cloud Run URL

Settings live in deploy.json (project, region, service, bucket). Requires the
gcloud CLI, logged in with `gcloud init`. Secrets are never written to disk here:
pass --openai-key / --admin-token only on the first deploy (or to rotate them);
later deploys keep the environment variables of the previous revision.
--admin-email is the Google account (comma-separated for several) that signs in
as admin and manages who may read whole pages. It stays out of this public
repository for the same reason: it lives only on the Cloud Run service.
"""
import argparse, json, os, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'deploy.json'
# Never synced: SQLite side files, temporary extraction folders, audit screenshots,
# unfinished downloads, and all of models/ — search models are downloaded, not made
# here, so each computer fetches its own with scripts/download_bge_m3.py and
# scripts/download_local_search_model.py. Carrying 570MB+ between computers made the
# transfer stall repeatedly, and a killed transfer discards the partial file.
# The bucket keeps its own copy for the Cloud Build step; a dry-run on 2026-09-24
# confirmed an excluded path is never listed for deletion at the destination.
# gcloud applies re.match to the relative path (backslashes on Windows), so every
# alternative may follow any leading folders. No leading ^: gcloud reads ^X^ at the
# start of a list argument as a custom delimiter and splits the pattern.
SYNC_EXCLUDE = r'(.*[/\\])?(tmp[^/\\]*([/\\].*)?|.*\.sqlite3-(wal|shm)|.*\.png|.*\.download|models([/\\].*)?)$'


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


def deploy(config, openai_key, admin_token, admin_email=''):
    image = image_name(config)
    project = ['--project', config['project']]
    run('builds', 'submit', '--config', 'cloudbuild.yaml', '--region', config['region'],
        '--substitutions', f"_BUCKET={config['bucket']},_IMAGE={image}", *project)
    args = ['run', 'deploy', config['service'], '--image', image, '--region', config['region'], '--platform', 'managed',
            '--allow-unauthenticated', '--memory', config['memory'], '--cpu', str(config['cpu']),
            '--max-instances', str(config['max_instances']), '--min-instances', str(config['min_instances']),
            '--timeout', str(config['timeout']), '--concurrency', '8', *project]
    env = {k: v for k, v in (('OPENAI_API_KEY', openai_key), ('ADMIN_TOKEN', admin_token), ('ADMIN_EMAILS', admin_email)) if v}
    if env:
        # ^|^ makes | the separator so a key containing a comma cannot break the list.
        args += ['--update-env-vars', '^|^' + '|'.join(f'{k}={v}' for k, v in env.items())]
    run(*args)
    print('\n배포 주소:', url(config))


def firebase():
    exe = shutil.which('firebase') or shutil.which('firebase.cmd')
    npm = Path(os.environ.get('APPDATA', '')) / 'npm' / 'firebase.cmd'
    if not exe and npm.exists():
        exe = str(npm)
    if not exe:
        sys.exit('firebase CLI를 찾을 수 없습니다. `npm install -g firebase-tools` 후 `firebase login`을 실행하세요.')
    return exe


def hosting(config):
    """The term list and cards are static files on Hosting (scripts/build_term_cards.py),
    so they are written from this computer's data/ and concepts/ just before upload.
    Without data/ they cannot be written, and uploading dist/ without them would
    drop the cards Hosting has, so stop instead."""
    if not (ROOT / 'data' / 'library.sqlite3').exists():
        sys.exit('data/library.sqlite3가 없어 용어 카드를 만들 수 없습니다. `python scripts/cloud.py pull-data` 후 `python scripts/cloud.py hosting`을 실행하세요.')
    print('$ python scripts/build_term_cards.py', flush=True)
    if subprocess.run([sys.executable, str(ROOT / 'scripts' / 'build_term_cards.py')], cwd=ROOT,
                      env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}).returncode:
        sys.exit('용어 카드를 만들지 못해 Hosting 배포를 멈췄습니다.')
    print('$ firebase deploy --only hosting', flush=True)
    if subprocess.run([firebase(), 'deploy', '--only', 'hosting', '--project', config['project']], cwd=ROOT).returncode:
        sys.exit('Hosting 배포에 실패했습니다.')


def url(config):
    return run('run', 'services', 'describe', config['service'], '--region', config['region'],
               '--project', config['project'], '--format', 'value(status.url)', capture=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('setup', 'push-data', 'pull-data', 'hosting', 'url'):
        sub.add_parser(name)
    d = sub.add_parser('deploy')
    d.add_argument('--openai-key', default='')
    d.add_argument('--admin-token', default='')
    d.add_argument('--admin-email', default='', help='관리자로 로그인할 구글 계정(여럿이면 쉼표로). 한 번 넣으면 다음 배포에도 남는다')
    d.add_argument('--no-hosting', action='store_true', help='Cloud Run만 배포하고 용어 카드·화면(Hosting)은 두기')
    args = parser.parse_args()
    config = load_config()
    if args.command == 'setup': setup(config)
    elif args.command == 'push-data': sync(config, 'push')
    elif args.command == 'pull-data': sync(config, 'pull')
    elif args.command == 'deploy':
        deploy(config, args.openai_key, args.admin_token, args.admin_email)
        if not args.no_hosting: hosting(config)
    elif args.command == 'hosting': hosting(config)
    elif args.command == 'url': print(url(config))


if __name__ == '__main__':
    main()
