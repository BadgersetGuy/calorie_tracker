# Dietary-pattern rubric 1.0

Evidence checked 9 November 2026. Formula ID: `diet-pattern-1.0`.
Prompt ID: `meal-2.0`.

## What the number means

This is an **app-designed dietary-pattern alignment score**. It is not PASI, a Dietary
Inflammatory Index, a biomarker, an estimate of inflammation in the body, or a validated
predictor of a psoriasis flare. No research cited below validates the numerical weights
or per-meal formula. The numeric rubric is a product choice and is labelled as such.

```
score = round(50 + 50 * (supportive grams - limiting grams) / total edible grams)
```

- Supportive: vegetables, fruit, legumes, whole grains, nuts/seeds, olive oil, fish.
- Limiting: processed meat, red meat, sweets/sugary drinks, refined grains, alcohol.
- Neutral: all other foods, including plain dairy, eggs, poultry, coffee and water.
- 100: entirely supportive by edible mass; 0: entirely limiting; 50: neutral or balanced.
- The full ingredient list, group assignment, assumptions, supportive/limiting percentage,
  version, and explanation are visible in the app.
- Portion size changes nutrient amounts, not this composition score. Do not multiply
  the score by 0.7 when copying a 70% portion.

The weighting is deliberately simple and transparent. Mass weighting has limitations:
water-rich foods can dominate, a teaspoon of oil has little mass, and a beverage can
change a combined-meal score. Do not interpret differences of a few points as medically
meaningful. Ingredient grouping and estimated quantities can still be wrong.

## Research basis and boundaries

1. **MEDIPSO randomized clinical trial (2025).** 38 adults with mild-to-moderate psoriasis;
   16-week Mediterranean dietary intervention alongside stable topical therapy. The trial
   supports further use/study of Mediterranean-style patterns as an adjunct, but its
   small, single-centre design does not identify a flare risk for every individual food.
   [JAMA Dermatology, DOI 10.1001/jamadermatol.2025.3410](https://jamanetwork.com/journals/jamadermatology/fullarticle/2839013)
2. **National Psoriasis Foundation systematic review (2018).** Strongest recommendation
   concerns weight reduction in people with overweight/obesity. Gluten-free eating is
   weakly recommended only for people with positive markers of gluten sensitivity.
   [PubMed 29926091](https://pubmed.ncbi.nlm.nih.gov/29926091/)
3. **NIAMS psoriasis guidance**, current page checked in November 2026. Highlights a
   healthy weight, healthy eating including Mediterranean dietary patterns, and moderating
   alcohol. [NIAMS guidance](https://www.niams.nih.gov/health-topics/psoriasis/diagnosis-treatment-and-steps-to-take)

Individual ingredients are not universally "bad for psoriasis". This version applies
no universal penalties to gluten, dairy, eggs or nightshades. Their presence can be
shown as ingredient flags. A personal trigger/symptom correlation system would require
separate longitudinal observations and is not implemented in this version.

## Consistency and change control

The model does not invent the score. It returns food classification and quantities in
a constrained schema; server code calculates the score and nutrition. Per-ingredient
nutrition values are estimates, so scores are reproducible for confirmed ingredients,
not guaranteed identical for differently phrased descriptions of the same real meal.

Analysis drafts retain the model, prompt version, response, assumptions and clarification
context. Saved analyses retain the computed score version. Old meals without ingredients
show no new score until explicitly reanalysed. Never silently recompute history under a
new formula. If the rubric changes, bump its ID, preserve old results, document changes,
and offer explicit reanalysis.

## Model evaluation before release

Compare the default model with a stronger candidate using the same set of weighed meals
and package labels. Include mixed dishes, hidden oil, sauces, milk-based drinks, small
portions, raw/cooked weights, text-only entries and ambiguous photos. Record ingredient
accuracy, calorie/macronutrient error, portion error, useful vs unnecessary questions,
response time and actual cost. Use repeated trials to measure variation. Version both
the evaluation set and prompt. No real-meal benchmark has been completed here.

[OpenAI model catalog](https://developers.openai.com/api/docs/models)
