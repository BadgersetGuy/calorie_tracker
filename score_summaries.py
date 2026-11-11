"""Explicit score coverage and calorie-weighted aggregates; never mix rubrics."""
import math


def score_averages(meals):
    def finite(value, maximum):
        return isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= maximum

    def aggregate(entries, scale):
        positive = [(meal, value) for meal, value in entries if finite(meal.get("calories"), 20000) and meal["calories"] > 0]
        energy = sum(meal["calories"] for meal, _ in positive)
        total_energy = sum(meal["calories"] for meal in meals if finite(meal.get("calories"), 20000))
        return dict(value=round(sum(meal["calories"] * value for meal, value in positive) / energy, 2) if energy else None,
            scale=scale, scored_meals=len(entries), weighted_meals=len(positive), unscored_meals=len(meals) - len(entries),
            scored_calories=round(energy, 2), calorie_coverage_percent=round(100 * energy / total_energy, 1) if total_energy else None,
            method="Calorie-weighted average: sum(score × meal calories) / scored meal calories. Missing scores are excluded; zero-calorie meals carry no weight.")

    versions = {}
    legacy = []
    for meal in meals:
        score = (meal.get("analysis") or {}).get("score") or {}
        if finite(score.get("value"), 100) and score.get("version"):
            versions.setdefault(score["version"], []).append((meal, score["value"]))
        old = meal.get("legacy_psoriasis_score")
        if finite(old, 10) and old >= 1: legacy.append((meal, old))
    pattern = aggregate([entry for group in versions.values() for entry in group], "0–100")
    pattern["by_version"] = [dict(version=version, meal_count=len(group), **aggregate(group, "0–100")) for version, group in sorted(versions.items())]
    if len(versions) != 1: pattern["value"] = None
    pattern["mixed_versions"] = len(versions) > 1
    psoriasis = aggregate(legacy, "1–10")
    psoriasis["label"] = "Historical psoriasis score"
    psoriasis["note"] = "Original historical estimates only; new analyses use the dietary-pattern rubric. Neither is a clinical measurement."
    return dict(dietary_pattern=pattern, legacy_psoriasis=psoriasis)
