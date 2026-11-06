"""Owned-offer evidence, unrestricted audience size and quota-bounded creator searches."""
import copy
import datetime as dt
import json
from pathlib import Path
import unittest

import creator_offers as offers
import clipping_targeting as targeting
import yt_api
from discover_youtube_channels import search_pairs

ROOT = Path(__file__).resolve().parent.parent
NOW = dt.datetime(2026, 11, 6, tzinfo=dt.timezone.utc)


class CreatorTargeting(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((ROOT / 'config/segment.lcx-clipping.json').read_text(encoding='utf-8'))

    def channel(self, text='Weekly filmmaking lessons.', subscribers=2000000, topics=None):
        item = {'id': 'UCfixture', 'snippet': {'title': 'Fixture Teacher', 'description': text, 'country': 'US', 'defaultLanguage': 'en'},
                'statistics': {'subscriberCount': str(subscribers), 'videoCount': '200'},
                'topicDetails': {'topicCategories': ['https://en.wikipedia.org/wiki/'+t for t in topics or ['Education']]}}
        uploads = [{'id': 'video-'+str(i), 'title': 'Lesson '+str(i), 'published_at': '2026-11-01T00:00:00Z',
                    'description': text, 'duration_s': 1200} for i in range(12)]
        return yt_api.profile(item, uploads, self.cfg)

    def test_owned_offers_are_evidence_backed(self):
        result = offers.detect([('Explore my filmmaking course: https://creator.example/course\nJoin my newsletter: https://creator.example/newsletter\nSupport me: https://patreon.com/fixture', 'https://youtube.com/@fixture', 'youtube_channel')])
        self.assertTrue(result['priority'])
        self.assertEqual(result['kinds'], ['course', 'membership', 'newsletter'])
        self.assertTrue(all(o['url'].startswith('https://') and o['evidence'] for o in result['offers']))
        self.assertNotIn('paid', result, 'a self-published offer does not establish its price')

    def test_sponsors_and_affiliates_are_not_owned_offers(self):
        for text in ['Sponsored by a course provider: https://partner.teachable.com',
                     'Affiliate link: https://gumroad.com/l/a-course',
                     "Our guest's newsletter: https://guest.substack.com",
                     'My favorite course is from Udemy.', 'I review courses on my channel.']:
            with self.subTest(text=text):
                self.assertFalse(offers.detect([(text, 'https://youtube.com/@fixture', 'youtube_channel')])['priority'])

    def test_services_and_creator_products_are_included(self):
        result = offers.detect([('Work with me on consulting.\nBuy my editing presets: https://creator.example/shop', None, 'youtube_channel')])
        self.assertEqual(result['kinds'], ['product', 'service'])

    def test_no_podcast_is_required(self):
        yc = self.channel('Join my cinematography course: https://creator.example/course')
        meta = targeting.refreshed_metadata({'youtube_channel': yc}, self.cfg, yc['title'])
        self.assertTrue(meta['creator_offers']['priority'])
        self.assertNotIn('podcast_feed', meta)
        self.assertFalse(self.cfg['creator_targeting']['offer_required'])
        self.assertFalse(any('offer' in g['key'] for g in self.cfg['gates']))

    def test_strong_creator_without_an_offer_remains_eligible(self):
        yc = self.channel()
        si = yt_api.inputs_from_channel(yc, self.cfg, NOW)
        self.assertFalse(yc['creator_offers']['priority'])
        self.assertFalse(si['excluded_category_signal'])
        self.assertEqual(si['audience_band'], 1)

    def test_every_large_audience_has_the_same_band_and_no_size_exclusion(self):
        for subscribers in (10000, 1000000, 2000000, 6000000, 50000000):
            with self.subTest(subscribers=subscribers):
                si = yt_api.inputs_from_channel(self.channel(subscribers=subscribers), self.cfg, NOW)
                self.assertEqual((si['audience_band'], si['oversized_signal'], si['oversized_audience']), (1, False, 0))
        self.assertFalse(any(g['key'] == 'not_oversized' for g in self.cfg['gates']))
        self.assertFalse(any(m['key'] == 'oversized_audience' for m in self.cfg['score_modifiers']))

    def test_legacy_other_project_size_policy_is_unchanged(self):
        legacy = copy.deepcopy(self.cfg); legacy.pop('creator_targeting')
        si = yt_api.inputs_from_channel(self.channel(subscribers=50000000), legacy, NOW)
        self.assertTrue(si['oversized_signal'])

    def test_music_education_is_allowed_but_performance_and_kids_are_excluded(self):
        for description, expected in [('Learn music production in my course.', False),
                                      ('Original music performances and official music videos.', True)]:
            si = yt_api.inputs_from_channel(self.channel(description, topics=['Music']), self.cfg, NOW)
            self.assertEqual(si['excluded_category_signal'], expected)
        self.assertTrue(offers.excluded_content('Kids guitar', 'Learn guitar', ['Kids & Family', 'Music'], self.cfg))

    def test_music_podcast_discussion_is_not_a_music_performance(self):
        self.assertFalse(offers.excluded_content('Music History', 'Original conversations', ['Music History'], self.cfg))
        self.assertFalse(any('music' in g.lower() for g in self.cfg['podcast_discovery']['excluded_genres']))

    def test_priority_searches_do_not_increase_the_budget(self):
        pairs = search_pairs(self.cfg['youtube_channel_discovery'], {'US'}, 'fixture', 15)
        self.assertEqual(len(pairs), 15)
        self.assertGreaterEqual(sum(bool(q.get('offer_priority')) for q, _ in pairs), 9)
        self.assertLess(sum(bool(q.get('offer_priority')) for q, _ in pairs), 15)
        self.assertEqual(sum(r['code'] == 'US' for _, r in pairs), 9)
        self.assertEqual(pairs, search_pairs(self.cfg['youtube_channel_discovery'], {'US'}, 'fixture', 15))

    def test_config_update_is_idempotent_and_preserves_mail_settings(self):
        updated = targeting.configure(self.cfg)
        self.assertEqual(updated, targeting.configure(updated))
        self.assertEqual(updated['outreach'], self.cfg['outreach'])
        self.assertEqual(updated['lead_retention'], self.cfg['lead_retention'])

    def test_backfill_clears_old_size_flags_without_claiming_offer_absence_is_a_gate(self):
        original = {'youtube_channel': self.channel(subscribers=10000000),
                    'scoring_inputs': {'audience_band': 0, 'oversized_signal': True, 'oversized_audience': 1, 'country_signal': 'allowed'}}
        meta = targeting.refreshed_metadata(original, self.cfg, 'Fixture')
        self.assertEqual(meta['scoring_inputs']['audience_band'], 1)
        self.assertFalse(meta['scoring_inputs']['oversized_signal'])
        self.assertEqual(meta['scoring_inputs']['country_signal'], 'allowed')
        self.assertFalse(meta['creator_offers']['priority'])
        self.assertTrue(original['scoring_inputs']['oversized_signal'], 'backfill does not mutate its input')

    def test_an_offer_never_overrides_the_remaining_qualification_gates(self):
        for key, value in [('country_signal','disallowed'), ('activity_signal','confirmed_dormant'),
                           ('excluded_category_signal',True), ('major_network_signal',True)]:
            self.assertFalse(targeting.passes_gates({'creator_offers':{'priority':True}, 'scoring_inputs':{key:value}}, self.cfg))
        self.assertTrue(targeting.passes_gates({'creator_offers':{'priority':False}}, self.cfg))

    def test_sql_priority_is_soft_and_prefers_an_offer_at_equal_quality(self):
        import psycopg2, uuid
        from run_sql import load_db_url
        from lead_lifecycle import priority_order
        conn = psycopg2.connect(load_db_url())
        try:
            cur = conn.cursor(); slug = 'zz-offer-'+uuid.uuid4().hex[:8]
            cur.execute("insert into segments(slug,name,entity_type,config) values (%s,'Fixture','company','{}') returning id", (slug,))
            seg = cur.fetchone()[0]; ids = []
            for label, score, offer in [('plain',70,False), ('offer',70,True), ('strong',95,False), ('weak',20,True)]:
                cur.execute("insert into entities(segment_id,name,source,status,fit_score,metadata,created_at) values (%s,%s,'test','ready_for_review',%s,%s::jsonb,now()) returning id",
                            (seg,label,score,json.dumps({'creator_offers':{'priority':offer}})))
                ids.append(str(cur.fetchone()[0]))
            cur.execute('select name from entities e where id=any(%s::uuid[]) order by '+priority_order(), (ids,))
            self.assertEqual([r[0] for r in cur.fetchall()], ['strong','offer','plain','weak'])
        finally:
            conn.rollback(); conn.close()


if __name__ == '__main__':
    unittest.main()
