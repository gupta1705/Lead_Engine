#!/usr/bin/env python3
"""dbconn.py -- a database connection that survives the pooler hanging up.

WHY THIS IS A SHARED MODULE AND NOT A LOCAL HELPER. Three long-running passes
died of the same thing on 2026-08-29:

    enrich_sitescrape  at  47 companies   server closed the connection
    enrich_sitescrape  at 183 companies   server closed the connection
    resolve_domains    at ~90 names       SSL SYSCALL error: EOF detected

Supabase's session pooler will not hold one connection open for the hour or
two these passes take. Every tool here opens a connection at the top of main()
and holds it to the end, so every one of them has this bug -- and fixing it
once inside enrich_sitescrape simply moved the next failure to the next tool.

The resolver's version was the expensive one: it accumulated results in a dict
and wrote them all at the end, so a drop at 90% lost 100% of the work. Hence
the second rule below.

TWO RULES FOR ANY LONG PASS
  1. Never hold a connection open across the whole run. Use Db.run(), which
     probes the connection, reconnects if it has gone, and retries once.
  2. Never batch writes to the end. Commit per item, so a failure costs one
     item rather than the whole pass. Resumability is a property of the data
     (a per-row "done" stamp), not of the process staying alive.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


class Db:
    """A psycopg2 connection that reconnects instead of dying."""

    def __init__(self, url=None):
        self._url = url
        self._conn = None

    def _url_or_env(self):
        if self._url:
            return self._url
        from run_sql import load_db_url
        return load_db_url()

    def _fresh(self):
        import psycopg2
        self._conn = psycopg2.connect(self._url_or_env(), connect_timeout=20)
        return self._conn

    def _live(self):
        import psycopg2
        if self._conn is None or self._conn.closed:
            return self._fresh()
        try:
            with self._conn.cursor() as c:
                c.execute("select 1")
            return self._conn
        except psycopg2.Error:
            try:
                self._conn.close()
            except Exception:
                pass
            return self._fresh()

    def run(self, fn, on_reconnect=None):
        """Run fn(cur) in a transaction. Commits on success; retries once on a drop.

        fn must be idempotent -- it may run twice if the connection dies after
        the work but before the commit lands.
        """
        import psycopg2
        for attempt in (1, 2):
            conn = self._live()
            try:
                with conn.cursor() as cur:
                    out = fn(cur)
                conn.commit()
                return out
            except psycopg2.OperationalError:
                try:
                    conn.close()
                except Exception:
                    pass
                self._conn = None
                if attempt == 2:
                    raise
                if on_reconnect:
                    on_reconnect()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise

    def close(self):
        try:
            if self._conn:
                self._conn.close()
        except Exception:
            pass
