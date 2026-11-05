"""LCX catalogue copy, truthful fallbacks, signatures and rollout compatibility."""
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
NOW = dt.datetime(2026, 11, 5, tzinfo=dt.timezone.utc)


class CatalogueTemplate(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((ROOT / "config/segment.lcx-clipping.json").read_text(encoding="utf-8"))["outreach"]
        self.meta = {"podcast_feed": {"episode_count": 525, "latest_title": "A conversation on science",
                                      "latest_at": "2026-11-04T00:00:00Z"}}

    def render(self, meta=None, company="Example Show", seed="example", cfg=None):
        cfg = cfg or self.cfg
        ctx = dr.build_context(cfg, company, self.meta if meta is None else meta,
                               "Anna Rao", "anna@example.com", seed=seed, now=NOW, generator=None)
        tpl = dr.pick_template(cfg, self.meta if meta is None else meta, ctx)
        return tpl, ctx, dr.render_message(tpl, ctx)

    def test_one_opener_follows_owner_catalogue_distribution_and_sample_offer(self):
        for seed in range(12):
            tpl, ctx, (subject, body) = self.render(seed=str(seed))
            self.assertEqual(tpl['key'], 'lcx_catalogue_distribution_v1')
            self.assertTrue(body.startswith('Hello Anna,'))
            for text in ('I trust you are doing well.', 'Example Show', 'at least 525 episodes',
                         'We are LCX', 'distribution workflows across social platforms',
                         'passive viewers into loyal fans', 'a few sample clips',
                         'particular episode', 'Thank you for your time.', 'Regards,'):
                self.assertIn(text, body)
            for text in ('Lex Fridman', '10,000', '500+', '48 hours', 'ReelForge', ct.URL, '{{', '[Name]', '[X]'):
                self.assertNotIn(text, body)
            self.assertFalse(has_forbidden_copy(subject + body))
            self.assertIsNone(llm.make_generator(self.cfg))

    def test_unknown_or_channel_upload_counts_do_not_become_episode_counts(self):
        for meta in ({}, {'youtube_channel': {'video_count': 525}},
                     {'podcast_feed': {'episode_count': 'unknown'}}, {'podcast_feed': {'episode_count': True}}):
            _, _, (_, body) = self.render(meta=meta)
            self.assertNotIn('525', body)
            self.assertNotIn('episodes,', body)
            self.assertIn('Looking at your long-form catalogue', body)
            self.assertNotIn('10,000', body)

    def test_real_episode_count_is_used_without_guessing_clip_totals(self):
        for count in (1, 42, 525, 1000):
            _, _, (_, body) = self.render(meta={'podcast_feed': {'episode_count': count}})
            self.assertIn('at least %s episodes' % format(count, ','), body)
            self.assertNotIn('potential reels', body)
        for value in (-1, 0, 1.5, 'NaN', 'Infinity'):
            self.assertIsNone(ct.episode_count({'podcast_feed': {'episode_count': value}}))

    def test_company_is_personalized_without_claiming_to_have_followed_it(self):
        _, _, (_, body) = self.render(company='Another Podcast')
        self.assertIn('conversations on Another Podcast',body)
        self.assertNotIn('following',body.lower())
        self.assertNotIn('Lex Fridman',body)
        _, _, (_, body) = self.render(meta={'youtube_channel':{}},company='A Video Studio')
        self.assertIn("long-form work in A Video Studio's catalogue",body)

    def test_long_names_and_em_dashes_are_safe(self):
        _, _, (subject, body) = self.render(company='A Very Long Show '*20+'Name\u2014Studio')
        self.assertLessEqual(dr.subject_words(subject),self.cfg['subject_max_words'])
        self.assertEqual(subject,'Turning your viewers into fans')
        self.assertFalse(has_forbidden_copy(subject + body))

    def test_signature_tracks_actual_sender_and_round_trips(self):
        _, _, (_, body) = self.render()
        for name in ('Kartikeya','Suhas C','Vedansh Gupta'):
            person={'email':'person@tvf.example','name':name,'title':'Business Development'}
            shown=dr.personalize(body,self.cfg,person)
            self.assertTrue(shown.endswith('Regards,\n'+name))
            self.assertEqual(dr.canonicalize(shown,self.cfg,person),body)
        self.assertNotIn('Kartikeya',body)

    def test_existing_followup_keeps_thread_subject_and_uses_matching_copy(self):
        followups=[t for t in self.cfg['templates'] if t.get('kind')=='follow_up']
        self.assertEqual(len(followups),1)
        ctx=self.render()[1];ctx['opener_subject']='The original approved subject'
        subject,body=dr.render_message(followups[0],ctx)
        self.assertEqual(subject,'Re: The original approved subject')
        self.assertIn('a few sample clips',body)
        self.assertIn('particular episode',body)
        self.assertNotIn('500+',body)
        self.assertNotIn('ReelForge',body)
        self.assertFalse(has_forbidden_copy(body))

    def test_copy_update_preserves_mailboxes_cap_window_and_followup_schedule(self):
        cfg={'sender':{'name':'Existing'},'daily_send_cap':99,'send_window':{'start':'10:00'},
             'mailboxes':[{'key':'mailbox'}],'sign_as':'approver','send_from':'approver',
             'follow_ups':{'enabled':True,'steps':[{'step':1,'after_days':4}]}}
        original=copy.deepcopy(cfg);ct.apply_config(cfg)
        for key,value in original.items(): self.assertEqual(cfg[key],value)
        self.assertEqual(ct.apply_config(copy.deepcopy(self.cfg)),self.cfg)

    def test_previous_copy_can_still_render_during_code_first_rollout(self):
        cfg=copy.deepcopy(self.cfg)
        cfg['reelforge_templates']='reelforge-20261021'
        cfg['templates']=[{'key':'previous','subject':'An archive idea','body':'{{archive_angle}}\n\n{{footer}}'}]
        _,_,(_,body)=self.render(cfg=cfg)
        self.assertIn('15,750+ potential shorts',body)
        self.assertNotIn('{{',body)

    def test_non_clipping_template_selection_is_unchanged(self):
        cfg={'templates':[{'key':'base'},{'key':'studio','when':{'metadata.kind':'production_house'}}]}
        self.assertEqual(dr.pick_template(cfg,{'kind':'production_house'},{})['key'],'studio')
        self.assertEqual(dr.pick_template(cfg,{}, {})['key'],'base')


if __name__=='__main__': unittest.main()
