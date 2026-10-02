import unittest

from adaptive_companion.delivery import DeliveryPart, DeliveryPlan, DeliveryPlanner, DeliverySettings


class BubblePacingTests(unittest.TestCase):
    casual = {'context': 'casual_chat'}

    def test_short_bubble_gap_is_about_one_second(self):
        planner = DeliveryPlanner()
        for seed in range(100):
            parts = planner.plan('好呀。明天见。', str(seed), self.casual).parts
            self.assertEqual(['好呀', '明天见'], [p.text for p in parts])
            self.assertTrue(840 <= parts[1].delay_ms <= 990)

    def test_longer_bubble_gap_is_about_two_seconds(self):
        text = '明' * 40
        planner = DeliveryPlanner()
        for seed in range(100):
            parts = planner.plan('好呀。' + text + '。', str(seed), self.casual).parts
            self.assertEqual(text, parts[1].text)
            self.assertTrue(1950 <= parts[1].delay_ms <= 2100)

    def test_very_long_bubble_gap_is_bounded_without_dropping_text(self):
        text = '明' * 150
        parts = DeliveryPlanner().plan('好呀。' + text + '。', policy=self.casual).parts
        self.assertEqual(text, parts[1].text)
        self.assertEqual(2500, parts[1].delay_ms)

    def test_model_latency_only_reduces_first_bubble_wait(self):
        planner = DeliveryPlanner()
        text = '好呀。明天见。记得带伞。'
        fast = planner.plan(text, 'fixed', self.casual)
        slow = planner.plan(text, 'fixed', self.casual, generation_latency_ms=30_000)
        self.assertTrue(0 < fast.parts[0].delay_ms <= 900)
        self.assertEqual(0, slow.parts[0].delay_ms)
        self.assertEqual(fast.parts[1:], slow.parts[1:])
        self.assertTrue(all(p.delay_ms >= 800 for p in slow.parts[1:]))

    def test_disabled_timing_stays_disabled_after_validation(self):
        planner = DeliveryPlanner(DeliverySettings(enabled=False))
        plan = planner.plan('好呀。明天见。', policy=self.casual)
        self.assertEqual([0, 0], [p.delay_ms for p in planner.validate(plan).parts])
        self.assertEqual([0, 0], [p.delay_ms for p in planner.validate(
            DeliveryPlan('split', [DeliveryPart('好呀', 800), DeliveryPart('明天见', 2000)])).parts])

    def test_custom_fast_settings_are_not_overridden(self):
        planner = DeliveryPlanner(DeliverySettings(base_delay_ms=0, delay_per_character_ms=0,
            random_jitter_ms=0, minimum_delay_ms=0, maximum_delay_ms=0))
        self.assertEqual([0, 0], [p.delay_ms for p in planner.plan('好呀。明天见。', policy=self.casual).parts])

    def test_empty_metadata_part_does_not_make_first_real_bubble_wait_a_second(self):
        planner = DeliveryPlanner()
        plan = planner.validate(DeliveryPlan('split', [DeliveryPart(' ', 500), DeliveryPart('好呀', 0), DeliveryPart('明天见', 1)]))
        self.assertEqual(['好呀', '明天见'], [p.text for p in plan.parts])
        self.assertEqual([0, 800], [p.delay_ms for p in plan.parts])


if __name__ == '__main__':
    unittest.main()
