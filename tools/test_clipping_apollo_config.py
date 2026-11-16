"""Configuration acceptance checks; no database or network."""
import copy
import json
import unittest
from pathlib import Path

from configure_clipping_apollo import configure, JOB

ROOT = Path(__file__).resolve().parent.parent


class ClippingApolloConfig(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((ROOT / 'config/segment.lcx-clipping.json').read_text(encoding='utf-8'))

    def test_no_credit_and_original_sourcing_scoring_and_copy_preserved(self):
        before = copy.deepcopy(self.cfg)
        result = configure(before)
        self.assertEqual(before, self.cfg)
        for key in ('enrichment', 'outreach', 'rubric', 'gates', 'modifiers', 'creator_targeting',
                    'discovery', 'geography', 'lead_retention', 'auto_shortlist'):
            self.assertEqual(result.get(key), self.cfg.get(key), key)
        block = result['clipping_apollo']
        self.assertFalse(block['enabled'])
        self.assertEqual((block['credits_per_run'], block['credits_per_week']), (0, 0))

    def test_pipeline_preserves_discovery_and_runs_after_qualification(self):
        base = copy.deepcopy(self.cfg)
        steps = base['pipelines']['weekly_refresh']
        i = steps.index(JOB)
        del steps[i:i+2]
        original = list(steps)
        final = configure(base)['pipelines']['weekly_refresh']
        i = final.index(JOB)
        self.assertEqual(final[:i] + final[i+2:], original)
        self.assertLess(final.index('enrich_clipping'), i)
        self.assertLess(final.index('promote_chain'), i)
        self.assertEqual(final[i+1:i+3], ['promote_chain', 'draft_outreach'])
        self.assertNotIn('discover_apollo', final)

    def test_idempotence(self):
        once = configure(self.cfg)
        self.assertEqual(configure(once), once)
        self.assertEqual(once['pipelines']['weekly_refresh'].count(JOB), 1)


if __name__ == '__main__':
    unittest.main()
