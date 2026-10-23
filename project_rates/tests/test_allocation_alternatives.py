from collections import Counter
from itertools import product

from django.test import SimpleTestCase

from project_rates.allocation_alternatives import alternative_pairs


class AllocationAlternativeTests(SimpleTestCase):
    def test_matches_exhaustive_small_case_feasibility_and_balance(self):
        # Enumerate all three-project case restrictions and their valid plans.
        options = [{e for e in range(3) if mask & (1 << e)} for mask in range(1, 8)]
        for allowed in product(options, repeat=3):
            candidates = dict(enumerate(allowed))
            plans = [set(enumerate(ids)) for ids in product(*allowed)]
            for fixed in [Counter(), Counter({0: 2, 1: 1})]:
                for pairs in plans:
                    load = fixed + Counter(e for _, e in pairs)
                    cost = sum(load[e] ** 2 for e in range(3))
                    expected = any(
                        other != pairs
                        and sum(
                            (fixed + Counter(e for _, e in other))[e] ** 2
                            for e in range(3)
                        )
                        <= cost
                        for other in plans
                    )
                    different = alternative_pairs(pairs, candidates, load)
                    self.assertEqual(different is not None, expected)
                    if different is not None:
                        self.assertNotEqual(different, pairs)
                        self.assertEqual(
                            Counter(p for p, _ in different), Counter(p for p, _ in pairs)
                        )
                        self.assertTrue(all(e in candidates[p] for p, e in different))
                        self.assertLessEqual(
                            sum(
                                (fixed + Counter(e for _, e in different))[e] ** 2
                                for e in range(3)
                            ),
                            cost,
                        )

    def test_cycle_preserves_load_when_no_single_exchange_is_balanced(self):
        pairs = {(10, 1), (20, 2), (30, 3)}
        result = alternative_pairs(
            pairs, {10: {1, 2}, 20: {2, 3}, 30: {3, 1}}, Counter({1: 1, 2: 1, 3: 1})
        )
        self.assertEqual(result, {(10, 2), (20, 3), (30, 1)})

    def test_multiple_slots_stay_unique_and_fixed_members_are_never_candidates(self):
        pairs = {(10, 1), (10, 2), (20, 3), (20, 4)}
        candidates = {10: {1, 2, 3, 4}, 20: {1, 2, 3, 4}}
        result = alternative_pairs(pairs, candidates, Counter({1: 1, 2: 1, 3: 1, 4: 1}))
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 4)
        self.assertEqual(Counter(p for p, _ in result), Counter({10: 2, 20: 2}))
