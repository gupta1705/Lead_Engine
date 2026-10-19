"""Narrow copy cleanup: preserve approved wording, remove dashes and free-clip CTAs."""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import draft_render as dr
from mail_copy import clean_text, has_forbidden_copy


class MailCopyTests(unittest.TestCase):
    def test_unaffected_message_is_byte_for_byte_unchanged(self):
        original = (
            "Hi Asha,\n\n"
            "Your people-first series has 12 episodes and 2–20 contributors.\n"
            "We deliver short-form work within 48 hours.\n\n"
            "See https://example.com/case-study?version=2 and write to hi@example.com.\n\n"
            "Vedansh Gupta\nBusiness Development, LCX\n"
        )
        self.assertEqual(clean_text(original), original)
        self.assertFalse(has_forbidden_copy(original))

    def test_em_and_horizontal_dashes_are_removed_without_rewriting(self):
        for dash in ("\u2014", "\u2015", "&mdash;", "&#8212;", "&#x2014;", " -- "):
            with self.subTest(dash=dash):
                text = "Our editors cut" + dash + "your team approves."
                self.assertEqual(clean_text(text), "Our editors cut, your team approves.")
                self.assertTrue(has_forbidden_copy(text))

    def test_adjacent_punctuation_does_not_gain_another_comma(self):
        text = "Our editors cut, \u2014 your team approves.\nA clear note. \u2014 Thanks."
        result = clean_text(text)
        self.assertIn("Our editors cut, your team approves.", result)
        self.assertNotRegex(result, r",\s*,|\.\s*,")
        self.assertNotIn("\u2014", result)

    def test_hyphenated_words_and_urls_survive(self):
        text = "people-first, long-form, behind-the-scenes: https://example.com/a--b/2025-10-19"
        self.assertEqual(clean_text(text), text)

    def test_original_free_clip_paragraph_is_removed_only(self):
        before = "Hi Alex,\n\nYour show has 859 videos and 22 long episodes.\n\nOur editors cut; you approve."
        offer = ('Rather than describe it: reply "yes" and we\'ll cut three shorts out of '
                 'your recent upload, "Episode 2. The next chapter...", free, so you can '
                 'judge the quality before anything else is discussed.')
        footer = "Vedansh Gupta\nBusiness Development, LCX"
        text = before + "\n\n" + offer + "\n\n" + footer
        self.assertEqual(clean_text(text), before + "\n\n" + footer)
        self.assertTrue(has_forbidden_copy(text))

    def test_clipping_film_variant_is_removed_only(self):
        before = "Hi Alex,\n\nOur editors cut; your team approves."
        offer = ('Rather than describe it: reply "yes" and we\'ll cut three shorts out of '
                 'one of your recent uploads, free, so you can judge the quality first.')
        self.assertEqual(clean_text(before + "\n\n" + offer + "\n\n{{footer}}"),
                         before + "\n\n{{footer}}")

    def test_followup_keeps_the_numeric_argument(self):
        before = ("Hi Alex,\n\nFloating this back up in case it got buried. "
                  "To put a number on it: a 43-minute video is 7 to 11 shorts.")
        offer = ('The offer stands -- reply "yes" and we\'ll cut three out of '
                 'your recent upload, "Dr. Jones: What changed?", free, so you can '
                 'judge the quality before anything else is discussed.')
        footer = "Alex Taylor\nPartnerships, LCX"
        self.assertEqual(clean_text(before + " " + offer + "\n\n" + footer),
                         before + "\n\n" + footer)

    def test_final_followup_keeps_opening_and_closing(self):
        before = "Hi Alex,\n\nLast note from me on this."
        offer = ("If short-form from your back catalogue is ever on the list, "
                 "reply here and the three free shorts are yours.")
        after = "Otherwise I'll leave you be.\n\nVedansh Gupta\nPartnerships, LCX"
        self.assertEqual(clean_text(before + " " + offer + " " + after),
                         before + " " + after)

    def test_quoted_titles_do_not_leave_partial_offer_fragments(self):
        for title in ('"Zero to One, live"', '"Ep. 219: Dr. Smith..."',
                      '"What happened? Part 2!"', '"The A.I. Show, Vol. 3"'):
            with self.subTest(title=title):
                offer = ('Rather than describe it: reply "yes" and we\'ll cut three shorts out of '
                         'your recent upload, ' + title + ', free, so you can judge the quality first.')
                self.assertEqual(clean_text("Opening.\n\n" + offer + "\n\nSender"),
                                 "Opening.\n\nSender")

    def test_ordinary_reply_request_and_free_facts_are_preserved(self):
        for text in ("Would you be free for a call next week?",
                     'Reply "yes" if Tuesday works for a conversation.',
                     "Your ad-free long-form series has 48 episodes.",
                     'We watched "Reply Yes", your latest film.'):
            with self.subTest(text=text):
                self.assertEqual(clean_text(text), text)
                self.assertFalse(has_forbidden_copy(text))

    def test_offer_removal_can_be_disabled_for_subjects(self):
        text = ('Rather than describe it: reply "yes" and we\'ll cut three shorts '
                'out of one of your recent uploads, free, so you can judge the quality first.')
        self.assertEqual(clean_text(text, remove_offer=False), text)

    def test_cleanup_is_idempotent(self):
        samples = [
            "Our editors cut \u2014 you approve.\n\nVedansh Gupta",
            'Opening.\n\nRather than describe it: reply "yes" and we\'ll cut three shorts '
            'out of your recent upload, "Vol. 3...", free, so you can judge the quality first.\n\nSender',
            'Last note from me on this. If short-form from your back catalogue is ever on '
            "the list, reply here and the three free shorts are yours. Otherwise I'll leave you be.",
        ]
        for text in samples:
            with self.subTest(text=text):
                once = clean_text(text)
                self.assertEqual(clean_text(once), once)
                self.assertFalse(has_forbidden_copy(once))

    def test_subject_word_limit_counts_cleaned_subject_and_fallback(self):
        ctx = {"subject_max_words": 5}
        tpl = {"subject": "A\u2014B C D E F", "body": "Existing body.",
               "subject_fallback": "Next production steps"}
        subject, body = dr.render_message(tpl, ctx)
        self.assertEqual(subject, "Next production steps")
        self.assertEqual(body, "Existing body.")
        self.assertLessEqual(dr.subject_words(subject), 5)
        tpl["subject_fallback"] = "C\u2014D E F G H"
        with self.assertRaises(ValueError):
            dr.render_message(tpl, ctx)

    def test_placeholder_values_are_cleaned_after_interpolation(self):
        tpl = {"subject": "{{company}} next steps",
               "body": "Hi {{greeting_name}},\n\n{{company}} has 12 episodes.\n\n{{footer}}"}
        cfg = {"sender": {"name": "Alex Taylor", "title": "Partnerships\u2014LCX"},
               "footer": {"text": "{{sender_name}}\n{{sender_title}}"}}
        ctx = {"company": "Example\u2014Studio", "greeting_name": "Asha",
               "footer": "Alex Taylor\nPartnerships\u2014LCX"}
        subject, body = dr.render_message(tpl, ctx)
        self.assertEqual(subject, "Example, Studio next steps")
        self.assertEqual(body, "Hi Asha,\n\nExample, Studio has 12 episodes.\n\nAlex Taylor\nPartnerships, LCX")
        self.assertEqual(dr.footer_for(cfg), "Alex Taylor\nPartnerships, LCX")

    def test_manual_messages_are_cleaned_without_a_person(self):
        body = ('Hi Asha,\n\nYour 12 episodes\u2014all long-form\u2014are useful.\n\n'
                'Rather than describe it: reply "yes" and we\'ll cut three shorts out of '
                'your recent upload, "Ep. 3...", free, so you can judge the quality first.\n\n'
                'Alex Taylor\nPartnerships, LCX')
        expected = ("Hi Asha,\n\nYour 12 episodes, all long-form, are useful.\n\n"
                    "Alex Taylor\nPartnerships, LCX")
        for cfg in ({}, {"sign_as": "approver"}):
            for person in (None, {}):
                with self.subTest(cfg=cfg, person=person):
                    self.assertEqual(dr.personalize(body, cfg, person), expected)
                    self.assertEqual(dr.canonicalize(body, cfg, person), expected)

    def test_every_saved_template_renders_with_cleanup_and_without_other_edits(self):
        count = 0
        for path in sorted((ROOT / "config").glob("segment*.json")):
            cfg = json.loads(path.read_text(encoding="utf-8"))
            for tpl in cfg.get("outreach", {}).get("templates", []):
                with self.subTest(segment=path.name, template=tpl.get("key")):
                    fields = set(re.findall(r"{{(\w+)}}", tpl["subject"] + tpl["body"]))
                    ctx = {field: "Evidence for " + field for field in fields}
                    ctx.update(company="Example Studio", greeting_name="Alex",
                               footer="Vedansh Gupta\nBusiness Development, LCX",
                               latest_work='your recent upload, "Dr. Smith... Part 2"',
                               clip_math="a 43-minute video is 7 to 11 shorts")
                    expected_subject = clean_text(dr.render(tpl["subject"], ctx), remove_offer=False)
                    expected_body = clean_text(dr.render(tpl["body"], ctx))
                    subject, body = dr.render_message(tpl, ctx)
                    self.assertEqual(subject, expected_subject)
                    self.assertEqual(body, expected_body)
                    self.assertFalse(has_forbidden_copy(subject))
                    self.assertFalse(has_forbidden_copy(body))
                    self.assertIn(ctx["footer"], body)
                    count += 1
        self.assertGreaterEqual(count, 12)


if __name__ == "__main__":
    unittest.main()
