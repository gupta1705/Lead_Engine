"""One explicitly queued, bounded Apollo batch on the server holding the owner's key.

No key export or login is needed. A durable claim prevents deployment/restart retries;
every paid attempt reserves from the 50/50 grant before HTTP and is never refunded.
"""
import contextlib
import importlib
import json
import os
import sys
from datetime import datetime, timezone

import apollo
import apollo_budget
from dbconn import Db

SLUGS = ('lcx-clipping', 'startup-acquisitions')
FIELD = 'apollo_pilot'
RESERVE = 700


def cost(path, body=None):
    if path == '/mixed_companies/search':
        return 1
    if path == '/people/bulk_match':
        details = (body or {}).get('details') or []
        if not details or len(details) > 10:
            raise ValueError('Invalid pilot reveal batch')
        return len(details)
    if path in ('/usage_stats/credit_usage_stats', '/users/api_profile', '/mixed_people/api_search'):
        return 0
    raise ValueError('Endpoint not allowed in the capped pilot')


def permitted(state, segment, amount):
    return (state.get('status') == 'running' and segment in SLUGS and
            amount > 0 and state.get('reserved', {}).get(segment, 0) + amount <= 50 and
            sum(state.get('reserved', {}).values()) + amount <= 100)


class Pilot:
    def __init__(self, db):
        self.db, self.segment, self.run_id = db, None, None

    def state(self, cur, lock=False):
        cur.execute("select config from segments where slug='lcx-clipping'" + (' for update' if lock else ''))
        return cur.fetchone()[0].get(FIELD) or {}

    def write(self, cur, state):
        cur.execute("update segments set config=jsonb_set(config,'{apollo_pilot}',%s::jsonb),updated_at=now() where slug='lcx-clipping'", (json.dumps(state),))

    def claim(self):
        def tx(cur):
            state = self.state(cur, True)
            if state.get('status') != 'queued' or state.get('limits') != dict.fromkeys(SLUGS, 50):
                return None
            state.update(status='running', started_at=datetime.now(timezone.utc).isoformat(), reserved=dict.fromkeys(SLUGS, 0))
            self.write(cur, state)
            return state['id']
        self.run_id = self.db.run(tx)
        return self.run_id

    def record(self, **fields):
        def tx(cur):
            state = self.state(cur, True)
            if state.get('id') != self.run_id:
                raise RuntimeError('Pilot identity changed')
            state.update(fields)
            self.write(cur, state)
        self.db.run(tx)

    def reserve(self, amount):
        def tx(cur):
            state = self.state(cur, True)
            if state.get('id') != self.run_id or not permitted(state, self.segment, amount):
                raise RuntimeError('Pilot credit cap reached')
            state['reserved'][self.segment] += amount
            self.write(cur, state)
        self.db.run(tx)

    def switches(self, enabled):
        def tx(cur):
            cur.execute('select slug,config from segments where slug=any(%s) order by slug for update', (list(SLUGS),))
            for slug, cfg in cur.fetchall():
                block = cfg['clipping_apollo' if slug == SLUGS[0] else 'enrichment']
                block.update(enabled=enabled, credits_per_run=50, keep_in_reserve=RESERVE)
                if enabled:
                    block['credits_per_week'] = apollo_budget.spent(cur, slug) + 50
                cur.execute('update segments set config=%s::jsonb,updated_at=now() where slug=%s', (json.dumps(cfg), slug))
        self.db.run(tx)

    def guarded(self, original):
        def call(method, path, query=None, body=None, timeout=30):
            amount = cost(path, body)
            if amount:
                balance = original('POST', '/usage_stats/credit_usage_stats', timeout=10)
                left = ((balance.get('credit_usage_stats') or {}).get('lead_credit') or {}).get('left_over')
                if not isinstance(left, (int, float)) or left - amount < RESERVE:
                    raise apollo.ApolloError('Pilot reserve or unknown balance prevents spending')
                self.reserve(amount)
            return original(method, path, query, body, timeout)
        return call

    def command(self, module, args):
        previous = sys.argv
        try:
            sys.argv = [module] + args
            result = importlib.import_module(module).main()
            if result not in (None, 0):
                raise RuntimeError(module + ' stopped with error')
        finally:
            sys.argv = previous

    def run(self):
        if not self.claim():
            return {'status': 'not queued; no Apollo calls'}
        original = apollo._call
        try:
            balance = apollo.credits()
            self.record(balance_before=balance)
            left = balance.get('lead_credits_left')
            if not isinstance(left, (int, float)) or left <= RESERVE:
                raise RuntimeError('Unknown balance or fewer credits than the reserve')
            apollo._call = self.guarded(original)
            self.switches(True)
            self.segment = SLUGS[0]
            import clipping_apollo
            result = clipping_apollo.run(clipping_apollo.Repository(self.db), limit=100)
            self.record(clipping=result)
            self.segment = SLUGS[1]
            os.environ['SEGMENT_SLUG'] = self.segment
            self.command('discover_apollo', ['--pages', '4', '--max-minutes', '5'])
            self.command('run_chain', ['--defer-shortlist'])
            self.command('enrich_lcx_services', ['--limit', '500'])
            self.command('enrich_startups', ['--limit', '50'])
            self.command('run_chain', ['--defer-shortlist'])
            self.command('enrich_apollo', ['--limit', '50', '--budget', '46'])
            self.command('run_chain', ['--defer-shortlist'])
            self.record(status='complete', balance_after=apollo.credits())
        except Exception as exc:
            self.record(status='stopped', error=str(exc)[:500])
        finally:
            apollo._call = original
            self.switches(False)
            self.record(finished_at=datetime.now(timezone.utc).isoformat(), spending_enabled=False)
        return self.db.run(lambda cur: self.state(cur))


def main():
    db = Db()
    try:
        print(json.dumps(Pilot(db).run()), flush=True)
    finally:
        db.close()


if __name__ == '__main__':
    main()
