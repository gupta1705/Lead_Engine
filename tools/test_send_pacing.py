"""Two-per-minute planning acceptance cases; no database or real email."""
import datetime as dt
import json
import random
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/"tools"))
import send_window as sw
import outreach_policy as policy
import send_pacing

class PacingTests(unittest.TestCase):
    def test_saved_projects_keep_windows_and_daily_caps(self):
        for path in (ROOT/"config").glob("segment.*.json"):
            before=json.loads(path.read_text(encoding="utf-8"));after=send_pacing.configure(before)
            self.assertEqual(send_pacing.configure(after),after)
            original=(before.get("outreach") or {}).get("send_window")
            if not original:continue
            w=sw.window_cfg(after)
            self.assertEqual((w["min_gap_seconds"],w["spacing_s"]),(30,30))
            self.assertEqual((w["start"],w["end"]),(original["start"],original["end"]))
            self.assertEqual(after["outreach"].get("daily_send_cap"),before["outreach"].get("daily_send_cap"))
            remaining=dict(after["outreach"]);remaining.pop("send_window")
            old=dict(before["outreach"]);old.pop("send_window")
            self.assertEqual(remaining,old)

    def test_eighty_approvals_fit_the_hour_with_account_cap_unchanged(self):
        class Cur:
            def execute(self,*args):pass
        w=sw.window_cfg({"send_window":{"start":"10:00","end":"11:00","min_gap_seconds":30,"schedule_padding_seconds":0}})
        now=dt.datetime(2026,11,16,8,tzinfo=dt.timezone.utc)
        for seed in range(20):
            placer=policy._Placer(Cur(),w,{"send_from":"approver"},"fixture",now,random.Random(seed))
            placer.keys["approver:fixture@example.test"]={"n":1,"daily_for":lambda day:80,"placed":{},"sent":[]}
            times=sorted(placer.place({"id":str(i),"approver":"fixture@example.test"},"UTC")[0] for i in range(80))
            self.assertTrue(all(t.date()==now.date() and t.hour==10 for t in times),seed)
            self.assertTrue(all((b-a).total_seconds()>=30 for a,b in zip(times,times[1:])))
            self.assertTrue(all((times[i+2]-times[i]).total_seconds()>=60 for i in range(len(times)-2)))
            extra=placer.place({"id":"extra","approver":"fixture@example.test"},"UTC")[0]
            self.assertGreater(extra.date(),now.date())

    def test_thirty_second_slot_is_available_and_twenty_nine_is_blocked(self):
        lo=dt.datetime(2026,11,16,10,tzinfo=dt.timezone.utc)
        self.assertIsNone(sw.pick_moment(lo+dt.timedelta(seconds=29),lo+dt.timedelta(seconds=30),[lo],30))
        self.assertEqual(sw.pick_moment(lo+dt.timedelta(seconds=30),lo+dt.timedelta(seconds=31),[lo],30),lo+dt.timedelta(seconds=30))

    def test_invalid_padding_is_refused(self):
        for value in (-1,True,"0",3601):
            with self.assertRaises(ValueError):sw.window_cfg({"send_window":{"schedule_padding_seconds":value}})

if __name__=="__main__":unittest.main()
