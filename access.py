"""Who may read whole pages on the public server.

The books are sold, so the public site shows only the quoted part of a page.
A whole page goes to the admin and to the few people the admin has let in by
their Google account; the admin page adds and removes them without a deploy.

Sign-in is Firebase Authentication (Google). The page sends the Firebase ID
token in X-Id-Token — not Authorization, which Cloud Run may try to read as
its own IAM token — and verify_token checks it against Google's keys.

Readers backends:
  memory    - in-process set (tests, local rehearsal)
  firestore - collection `readers`, one document per email (Cloud Run).
              Fails closed: if Firestore is unreachable, nobody but the
              admins (ADMIN_EMAILS) reads whole pages.
"""
import os, re, time, threading, hashlib, datetime

PROJECT = os.environ.get('FIREBASE_PROJECT', 'kor-teacher-help')
ISSUER = 'https://securetoken.google.com/'
EMAIL = re.compile(r'[^@\s]{1,64}@[A-Za-z0-9.-]{1,189}\.[A-Za-z]{2,}')
CACHE_SECONDS = 30


def normal(email):
    """The form an email is stored and compared in, or '' when it is not one."""
    email = (email or '').strip().lower() if isinstance(email, str) else ''
    return email if EMAIL.fullmatch(email) else ''


def check_claims(claims, project=PROJECT, now=None):
    """The email a verified Firebase ID token speaks for, or ''.

    google-auth checks the signature, expiry and audience; the rest of what
    Firebase asks a server to check is here: the issuer, a subject, and that
    the account is a Google account whose address Google has confirmed."""
    now = time.time() if now is None else now
    if claims.get('iss') != ISSUER + project or claims.get('aud') != project:
        return ''
    signed_in = claims.get('auth_time')
    if not claims.get('sub') or not isinstance(signed_in, (int, float)) or signed_in > now + 60:
        return ''
    if (claims.get('firebase') or {}).get('sign_in_provider') != 'google.com':
        return ''
    if claims.get('email_verified') is not True:
        return ''
    return normal(claims.get('email'))


_verified = {}
_verified_lock = threading.Lock()
_transport = None


def verify_token(token):
    """The Google account's email behind a Firebase ID token, or '' for anything else.

    A token stays valid for an hour and the page sends the same one on every
    request, so a checked token is remembered until it expires instead of
    fetching Google's keys again."""
    if not isinstance(token, str) or not 20 <= len(token) <= 4096:
        return ''
    key = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    with _verified_lock:
        hit = _verified.get(key)
        if hit and hit[1] > now:
            return hit[0]
    global _transport
    try:
        # Both come with google-cloud-firestore; neither is installed for local use.
        from google.oauth2 import id_token
        from google.auth.transport import requests as transport
        if _transport is None:
            _transport = transport.Request()
        claims = id_token.verify_firebase_token(token, _transport, audience=PROJECT)
    except Exception:
        return ''
    email = check_claims(claims or {}, now=now)
    if email:
        with _verified_lock:
            if len(_verified) > 1000:
                for k in [k for k, (_, exp) in _verified.items() if exp <= now]:
                    del _verified[k]
            _verified[key] = (email, float(claims.get('exp', now)))
    return email


def admin_emails():
    return {e for e in map(normal, os.environ.get('ADMIN_EMAILS', '').split(',')) if e}


class MemoryReaders:
    name = 'memory'
    def __init__(self):
        self.rows = {}
        self.lock = threading.Lock()
    def list(self):
        with self.lock:
            return sorted(self.rows.values(), key=lambda r: r['added'], reverse=True)
    def allowed(self, email):
        with self.lock:
            return email in self.rows
    def add(self, email, note, by):
        with self.lock:
            self.rows[email] = {'email': email, 'note': note, 'added': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), 'added_by': by}
    def remove(self, email):
        with self.lock:
            return self.rows.pop(email, None) is not None


class FirestoreReaders:
    name = 'firestore'
    def __init__(self):
        from google.cloud import firestore  # imported lazily: not installed for local use
        self.firestore = firestore
        self.db = firestore.Client()
        self.cache = (0.0, frozenset())
        self.lock = threading.Lock()
    def _col(self):
        return self.db.collection('readers')
    def _emails(self):
        # Every whole-page request asks; one read of the list per CACHE_SECONDS answers them.
        at, emails = self.cache
        if time.monotonic() - at < CACHE_SECONDS:
            return emails
        with self.lock:
            at, emails = self.cache
            if time.monotonic() - at < CACHE_SECONDS:
                return emails
            emails = frozenset(doc.id for doc in self._col().stream())
            self.cache = (time.monotonic(), emails)
            return emails
    def _forget(self):
        self.cache = (0.0, frozenset())
    def list(self):
        rows = []
        for doc in self._col().stream():
            data = doc.to_dict() or {}
            added = data.get('added')
            rows.append({'email': doc.id, 'note': data.get('note', ''), 'added': added.isoformat(timespec='seconds') if hasattr(added, 'isoformat') else '', 'added_by': data.get('added_by', '')})
        return sorted(rows, key=lambda r: r['added'], reverse=True)
    def allowed(self, email):
        return email in self._emails()
    def add(self, email, note, by):
        self._col().document(email).set({'note': note, 'added': self.firestore.SERVER_TIMESTAMP, 'added_by': by})
        self._forget()
    def remove(self, email):
        ref = self._col().document(email)
        existed = ref.get().exists
        ref.delete()
        self._forget()
        return existed


def make(backend):
    if backend == 'firestore': return FirestoreReaders()
    if backend == 'memory': return MemoryReaders()
    return None
