"""Daily AI-explanation quota for the public deployment.

One bucket per Korean calendar day: the whole server. Everyone draws from the
same pool, so nothing is counted per visitor and the site sets no cookie for
this. The admin (X-Admin-Token) bypasses all of it in server.py, so nothing
here ever sees admin traffic.

Backends:
  none      - no counting (local desktop use)
  memory    - in-process dict, resets on restart (tests, local rehearsal)
  firestore - Google Cloud Firestore via Application Default Credentials
              (Cloud Run). Fails closed: if Firestore is unreachable the
              caller refuses to generate an explanation.
"""
import os, threading, datetime

KST = datetime.timezone(datetime.timedelta(hours=9))
LIMIT = int(os.environ.get('DAILY_TOTAL', '100'))


def today():
    return datetime.datetime.now(KST).strftime('%Y-%m-%d')


def _remaining(count):
    return max(0, LIMIT - count)


class NoQuota:
    name = 'none'
    def peek(self, day): return None
    def consume(self, day): return True, None
    def refund(self, day): pass


class MemoryQuota:
    name = 'memory'
    def __init__(self):
        self.counts = {}
        self.lock = threading.Lock()
    def peek(self, day):
        with self.lock:
            return _remaining(self.counts.get(day, 0))
    def consume(self, day):
        with self.lock:
            count = self.counts.get(day, 0)
            if count >= LIMIT:
                return False, 0
            self.counts[day] = count + 1
            return True, _remaining(count + 1)
    def refund(self, day):
        with self.lock:
            if self.counts.get(day, 0) > 0: self.counts[day] -= 1


class FirestoreQuota:
    name = 'firestore'
    def __init__(self):
        from google.cloud import firestore  # imported lazily: not installed for local use
        self.firestore = firestore
        self.db = firestore.Client()
    def _ref(self, day):
        return self.db.document('quota_daily', day)
    @staticmethod
    def _count(snapshot):
        return (snapshot.to_dict() or {}).get('count', 0) if snapshot.exists else 0
    def peek(self, day):
        return _remaining(self._count(self._ref(day).get()))
    def consume(self, day):
        ref = self._ref(day)
        firestore = self.firestore
        # The document carries an `expires` timestamp so a Firestore TTL policy on
        # that field can sweep old days automatically; nothing reads it.
        expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3)
        @firestore.transactional
        def run(tx):
            count = self._count(ref.get(transaction=tx))
            if count >= LIMIT:
                return False, 0
            tx.set(ref, {'count': count + 1, 'updated': firestore.SERVER_TIMESTAMP, 'expires': expires}, merge=True)
            return True, _remaining(count + 1)
        return run(self.db.transaction())
    def refund(self, day):
        ref = self._ref(day)
        firestore = self.firestore
        @firestore.transactional
        def run(tx):
            count = self._count(ref.get(transaction=tx))
            if count > 0: tx.set(ref, {'count': count - 1}, merge=True)
        run(self.db.transaction())


def make(backend):
    if backend == 'firestore': return FirestoreQuota()
    if backend == 'memory': return MemoryQuota()
    return NoQuota()
