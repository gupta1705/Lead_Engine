import unittest
import apollo
from apollo_pilot import Pilot, SLUGS, cost, permitted


class GuardTests(unittest.TestCase):
    def test_endpoint_allowlist(self):
        self.assertEqual(cost('/mixed_people/api_search'), 0)
        self.assertEqual(cost('/mixed_companies/search'), 1)
        self.assertEqual(cost('/people/bulk_match', {'details': [{'id': 'x'}] * 10}), 10)
        with self.assertRaises(ValueError):
            cost('/people/match')

    def test_segment_caps_cannot_borrow(self):
        state = {'status': 'running', 'reserved': dict(zip(SLUGS, [50, 3]))}
        self.assertFalse(permitted(state, SLUGS[0], 1))
        self.assertTrue(permitted(state, SLUGS[1], 47))
        self.assertFalse(permitted(state, SLUGS[1], 48))
        state['status'] = 'complete'
        self.assertFalse(permitted(state, SLUGS[1], 1))

    def guard(self, balance, fail=False):
        calls, reserves = [], []
        pilot = Pilot(None)
        pilot.reserve = reserves.append
        def original(method, path, query=None, body=None, timeout=30):
            calls.append(path)
            if path == '/usage_stats/credit_usage_stats':
                return {'credit_usage_stats': {'lead_credit': {'left_over': balance}}}
            if fail:
                raise apollo.ApolloError('uncertain request')
            return {'ok': True}
        return pilot.guarded(original), calls, reserves

    def test_balance_checked_before_reservation_and_paid_call(self):
        call, calls, reserves = self.guard(701)
        call('POST', '/mixed_companies/search')
        self.assertEqual(calls, ['/usage_stats/credit_usage_stats', '/mixed_companies/search'])
        self.assertEqual(reserves, [1])

    def test_low_unknown_balance_cannot_spend(self):
        for balance in (None, 700):
            call, calls, reserves = self.guard(balance)
            with self.assertRaises(apollo.ApolloError):
                call('POST', '/mixed_companies/search')
            self.assertEqual(reserves, [])
            self.assertEqual(calls, ['/usage_stats/credit_usage_stats'])

    def test_uncertain_paid_request_keeps_reservation(self):
        call, calls, reserves = self.guard(900, True)
        with self.assertRaises(apollo.ApolloError):
            call('POST', '/mixed_companies/search')
        self.assertEqual(reserves, [1])
        self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
