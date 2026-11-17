import unittest
import urllib.error
from unittest.mock import patch
import discover_podcasts as podcast


class ThrottleTests(unittest.TestCase):
    def test_repeated_refusal_ends_search_pass(self):
        for status in (403, 429, 503):
            with patch.object(podcast, 'http_get', side_effect=urllib.error.HTTPError('https://example.org', status, '', {}, None)) as get, patch.object(podcast.time, 'sleep'):
                with self.assertRaises(podcast.AppleThrottled):
                    podcast.apple_search('filmmaking', 'US')
                self.assertEqual(get.call_count, 3)

    def test_success_after_throttle_keeps_results(self):
        error = urllib.error.HTTPError('https://example.org', 429, '', {}, None)
        with patch.object(podcast, 'http_get', side_effect=[error, b'{"results":[{"collectionId":123}]}']), patch.object(podcast.time, 'sleep'):
            self.assertEqual(podcast.apple_search('film', 'US'), [{'collectionId': 123}])

    def test_empty_success_is_not_a_throttle(self):
        with patch.object(podcast, 'http_get', return_value=b'{"results":[]}'):
            self.assertEqual(podcast.apple_search('film', 'US'), [])


if __name__ == '__main__':
    unittest.main()
