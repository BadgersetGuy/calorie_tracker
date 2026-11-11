import unittest
from score_summaries import score_averages


def meal(calories, score=None, legacy=None, version="v1"):
    return dict(calories=calories, legacy_psoriasis_score=legacy,
        analysis=dict(score=dict(value=score, version=version)) if score is not None else None)


class ScoreSummaryTests(unittest.TestCase):
    def test_weighted_averages_coverage_and_separate_scales(self):
        report = score_averages([meal(100, 10, 1), meal(900, 90, 9), meal(1000), meal(0, 100, 10)])
        self.assertEqual(report["dietary_pattern"]["value"], 82)
        self.assertEqual(report["legacy_psoriasis"]["value"], 8.2)
        for score in report.values():
            self.assertEqual(score["scored_meals"], 3)
            self.assertEqual(score["weighted_meals"], 2)
            self.assertEqual(score["unscored_meals"], 1)
            self.assertEqual(score["calorie_coverage_percent"], 50)

    def test_absent_invalid_or_zero_energy_scores_are_not_zero_averages(self):
        for meals in ([], [meal(100)], [meal(0, 80, 8)], [meal(100, float("nan"), 11)]):
            for score in score_averages(meals).values(): self.assertIsNone(score["value"])

    def test_rubric_versions_remain_separate(self):
        score = score_averages([meal(100, 20), meal(900, 80, version="v2")])["dietary_pattern"]
        self.assertIsNone(score["value"])
        self.assertTrue(score["mixed_versions"])
        self.assertEqual([part["value"] for part in score["by_version"]], [20, 80])
