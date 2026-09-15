"""Daily AI-explanation quota for the public deployment.

Three buckets are counted per Korean calendar day: the visitor cookie, the
client IP, and the whole server. A request is allowed only when every bucket
is under its limit. The admin (X-Admin-Token) bypasses all of this in
server.py, so nothing here ever sees admin traffic.

Backends:
  none      - no counting (local desktop use)
  memory    - in-process dict, resets on restart (tests, local rehearsal)
  firestore - Google Cloud Firestore via Application Default Credentials
              (Cloud Run). Fails closed: if Firestore is unreachable the
              caller refuses to generate an explanation.
"""
import os, threading, datetime

KST = datetime.timezone(datetime.timedelta(hours=9))
LIMITS = (int(os.environ.get('DAILY_PER_VISITOR', '3')),
          int(os.environ.get('DAILY_PER_IP', '15')),
          int(os.environ.get('DAILY_TOTAL', '300')))
LABELS = ('visitor', 'ip', 'daily')


def today():
    return datetime.datetime.now(KST).strftime('%Y-%m-%d')


def _remaining(counts):
    return max(0, min(limit - count for limit, count in zip(LIMITS, counts)))


class NoQuota:
    name = 'none'
    def peek(self, day, visitor, ip): return None
    def consume(self, day, visitor, ip): return True, None
    def refund(self, day, visitor, ip): pass


class MemoryQuota:
    name = 'memory'
    def __init__(self):
        self.counts = {}
        self.lock = threading.Lock()
    def _keys(self, day, visitor, ip):
        return [(day, 'visitor', visitor), (day, 'ip', ip), (day, 'daily', '')]
    def peek(self, day, visitor, ip):
        with self.lock:
            return _remaining([self.counts.get(k, 0) for k in self._keys(day, visitor, ip)])
    def consume(self, day, visitor, ip):
        keys = self._keys(day, visitor, ip)
        with self.lock:
            counts = [self.counts.get(k, 0) for k in keys]
            if any(c >= l for c, l in zip(counts, LIMITS)):
                return False, _remaining(counts)
            for k in keys: self.counts[k] = self.counts.get(k, 0) + 1
            return True, _remaining([c + 1 for c in counts])
    def refund(self, day, visitor, ip):
        with self.lock:
            for k in self._keys(day, visitor, ip):
                if self.counts.get(k, 0) > 0: self.counts[k] -= 1


class FirestoreQuota:
    name = 'firestore'
    def __init__(self):
        from google.cloud import firestore  # imported lazily: not installed for local use
        self.firestore = firestore
        self.db = firestore.Client()
    def _refs(self, day, visitor, ip):
        return [self.db.document('quota_visitor', f'{day}_{visitor}'),
                self.db.document('quota_ip', f'{day}_{ip}'),
                self.db.document('quota_daily', day)]
    @staticmethod
    def _count(snapshot):
        return (snapshot.to_dict() or {}).get('count', 0) if snapshot.exists else 0
    def peek(self, day, visitor, ip):
        return _remaining([self._count(ref.get()) for ref in self._refs(day, visitor, ip)])
    def consume(self, day, visitor, ip):
        refs = self._refs(day, visitor, ip)
        firestore = self.firestore
        # Documents carry an `expires` timestamp so a Firestore TTL policy on
        # that field can sweep old days automatically; nothing reads it.
        expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3)
        @firestore.transactional
        def run(tx):
            counts = [self._count(ref.get(transaction=tx)) for ref in refs]
            if any(c >= l for c, l in zip(counts, LIMITS)):
                return False, _remaining(counts)
            for ref, count in zip(refs, counts):
                tx.set(ref, {'count': count + 1, 'updated': firestore.SERVER_TIMESTAMP, 'expires': expires}, merge=True)
            return True, _remaining([c + 1 for c in counts])
        return run(self.db.transaction())
    def refund(self, day, visitor, ip):
        refs = self._refs(day, visitor, ip)
        firestore = self.firestore
        @firestore.transactional
        def run(tx):
            counts = [self._count(ref.get(transaction=tx)) for ref in refs]
            for ref, count in zip(refs, counts):
                if count > 0: tx.set(ref, {'count': count - 1}, merge=True)
        run(self.db.transaction())


def make(backend):
    if backend == 'firestore': return FirestoreQuota()
    if backend == 'memory': return MemoryQuota()
    return NoQuota()
