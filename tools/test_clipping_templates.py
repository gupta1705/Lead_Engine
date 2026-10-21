"""The owner's four ReelForge patterns, evidence fallbacks and existing copy safeguards."""
import copy
import datetime as dt
import json
import unittest
from pathlib import Path

import clipping_templates as ct
import draft_render as dr
import llm
from mail_copy import has_forbidden_copy

ROOT = Path(__file__).resolve().parent.parent
NOW = dt.datetime(2026, 10, 21, tzinfo=dt.timezone.utc)


class ReelForgeTemplates(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((ROOT / "config/segment.lcx-clipping.json").read_text(encoding="utf-8"))["outreach"]
        self.meta = {"podcast_feed": {"episode_count": 525, "latest_title": "A conversation on science",
                                      "latest_at": "2026-10-20T00:00:00Z"}}

    def render(self, meta=None, company="Example Show", seed="example"):
        ctx = dr.build_context(self.cfg, company, self.meta if meta is None else meta,
                               "Anna Rao", "anna@example.com", seed=seed, now=NOW, generator=None)
        tpl = dr.pick_template(self.cfg, meta or {}, ctx)
        return tpl, ctx, dr.render_message(tpl, ctx)

    def test_four_openers_are_used_and_have_owner_offer_and_process(self):
        seen = set()
        for seed in range(100):
            tpl, ctx, (subject, body) = self.render(seed=str(seed))
            seen.add(tpl["key"])
            for phrase in ("500+", "48 hours", "AI and human editors", "third-party networks", ct.URL,
                           "free clip set", "LCX | lightscameraexperiment.com"):
                self.assertIn(phrase, body)
            self.assertNotIn("{{", body)
            self.assertNotIn("Figuring Out", body)
            self.assertNotIn("FO518", body)
            self.assertFalse(has_forbidden_copy(subject))
            self.assertFalse(has_forbidden_copy(body))
            self.assertLessEqual(dr.subject_words(subject), self.cfg["subject_max_words"])
        self.assertEqual(len(seen), 4)

    def test_archive_maths_are_conditional_not_unseen_footage_claims(self):
        _, ctx, _ = self.render()
        self.assertIn("262,500+ potential shorts", ctx["archive_opportunity"])
        self.assertIn("15,750+ potential shorts", ctx["archive_angle"])
        self.assertNotIn("never seen", ctx["archive_opportunity"])

    def test_unknown_counts_do_not_reuse_example_numbers_or_choose_archive_math(self):
        for meta in ({}, {"youtube_channel": {"video_count": 525}},
                     {"podcast_feed": {"episode_count": "unknown"}}):
            for seed in range(12):
                tpl, ctx, (_, body) = self.render(meta=meta, seed=str(seed))
                self.assertNotEqual(tpl["key"], "reelforge_archive_feed_v1")
                self.assertNotIn("525", body)
                self.assertNotIn("15,750", body)
                self.assertNotIn("your recent episode,", body)

    def test_old_or_advertising_titles_are_not_presented_as_recent_work(self):
        for title, date in (("Old title", "2025-01-01"), ("Buy https://spam.example", "2026-10-20")):
            meta = {"podcast_feed": {"latest_title": title, "latest_at": date}}
            _, ctx, (_, body) = self.render(meta=meta)
            self.assertNotIn(title, body)
            self.assertEqual(ctx["sample_target"], "one of your episodes")

    def test_long_names_and_em_dashes_are_safe(self):
        for seed in range(12):
            _, _, (subject, body) = self.render(company="A Very Long Show " * 20 + "Name\u2014Studio", seed=str(seed))
            self.assertLessEqual(dr.subject_words(subject), 16)
            self.assertFalse(has_forbidden_copy(subject))
            self.assertFalse(has_forbidden_copy(body))

    def test_free_clip_question_survives_preview_and_edit_without_reply_yes(self):
        _, _, (_, body) = self.render()
        person = {"email": "anna@tvf.example", "name": "Anna Rao", "title": "Business Development"}
        shown = dr.personalize(body, self.cfg, person)
        self.assertIn("free clip set", shown)
        self.assertIn("Regards,\nAnna Rao\nLCX | lightscameraexperiment.com", shown)
        self.assertEqual(dr.canonicalize(shown, self.cfg, person), body)
        self.assertNotIn("reply yes", shown.lower())

    def test_existing_mailbox_and_qualification_settings_are_not_replaced(self):
        cfg = {"sender": {"name": "Existing"}, "daily_send_cap": 99,
               "send_window": {"start": "10:00"}, "mailboxes": [{"key": "mailbox"}], "sign_as": "approver"}
        original = copy.deepcopy(cfg)
        ct.apply_config(cfg)
        for key, value in original.items():
            self.assertEqual(cfg[key], value)
        self.assertIsNone(llm.make_generator(self.cfg))

    def test_rotation_is_stable_and_followups_are_not_selected_as_openers(self):
        self.assertEqual(self.render()[0], self.render()[0])
        for tpl in self.cfg["templates"]:
            if tpl.get("kind") == "follow_up":
                ctx = self.render()[1]
                ctx["opener_subject"] = "An earlier subject"
                subject, body = dr.render_message(tpl, ctx)
                self.assertEqual(subject, "Re: An earlier subject")
                self.assertIn("500+", body)
                self.assertIn("free clip set", body)

    def test_non_clipping_templates_keep_their_existing_selection_and_cap(self):
        cfg = {"templates": [{"key": "base"}, {"key": "studio", "when": {"metadata.kind": "production_house"}}]}
        self.assertEqual(dr.pick_template(cfg, {"kind": "production_house"}, {})["key"], "studio")
        self.assertEqual(dr.pick_template(cfg, {}, {})["key"], "base")


if __name__ == "__main__":
    unittest.main()
