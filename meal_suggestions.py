"""Auditable food ideas using household history, feedback, novelty and rotation."""
from collections import Counter
import re
import unicodedata

VERSION = "meal-ideas-1.0"

def normalized(value):
    return " ".join(re.findall(r"\w+", "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))))

ALIASES = {
    "salmon": ["salmon", "somon"], "lentils": ["lentil", "lentils", "linte"],
    "chickpeas": ["chickpea", "chickpeas", "naut"], "oats": ["oat", "oats", "ovaz"],
    "beans": ["bean", "beans", "fasole"], "mushrooms": ["mushroom", "mushrooms", "ciuperci"],
    "spinach": ["spinach", "spanac"], "tomatoes": ["tomato", "tomatoes", "rosii", "rosie"],
    "walnuts": ["walnut", "walnuts", "nuci"], "sardines": ["sardine", "sardines", "sardinele"],
    "brown rice": ["brown rice", "orez brun"], "buckwheat": ["buckwheat", "hrisca"],
    "yogurt": ["yogurt", "yoghurt", "iaurt"], "eggs": ["egg", "eggs", "ou", "oua"],
}

def recipe(key, title, group, ingredients, steps, tags=()):
    return dict(id=key, title=title, group=group, ingredients=ingredients,
                steps=steps, tags=list(tags), basis="Vegetables, legumes, whole grains and/or fish; Mediterranean-style dietary pattern.")

RECIPES = [
    recipe("lentil-bowl", "Lentil & roasted vegetable bowl", "legumes", ["lentils", "carrots", "spinach", "olive oil", "lemon"], "Cook lentils; roast carrots. Toss with spinach, lemon and a little olive oil."),
    recipe("salmon-barley", "Salmon, barley & broccoli", "fish", ["salmon", "barley", "broccoli", "olive oil", "lemon"], "Bake salmon and broccoli; serve with cooked barley and lemon.", ["fish", "gluten"]),
    recipe("chickpea-tray", "Chickpea & cauliflower tray bake", "legumes", ["chickpeas", "cauliflower", "spinach", "olive oil", "cumin"], "Roast drained chickpeas and cauliflower with cumin; finish with spinach."),
    recipe("oat-berries", "Berry oats with walnuts", "breakfast", ["oats", "berries", "walnuts", "chia seeds"], "Cook oats in water; top with berries, chopped walnuts and chia.", ["nuts", "gluten"]),
    recipe("bean-soup", "White bean & vegetable soup", "legumes", ["beans", "carrots", "celery", "tomatoes", "olive oil"], "Simmer vegetables and cooked beans; finish with olive oil and herbs.", ["celery", "nightshades"]),
    recipe("sardine-toast", "Sardines on wholegrain toast", "fish", ["sardines", "wholegrain bread", "tomatoes", "parsley", "lemon"], "Top wholegrain toast with sardines, sliced tomatoes, parsley and lemon.", ["fish", "gluten", "nightshades"]),
    recipe("buckwheat-mushrooms", "Buckwheat, mushrooms & greens", "whole_grains", ["buckwheat", "mushrooms", "spinach", "olive oil", "garlic"], "Cook buckwheat; sauté mushrooms and garlic, then fold in spinach."),
    recipe("quinoa-peas", "Quinoa & green pea salad", "whole_grains", ["quinoa", "peas", "cucumber", "mint", "lemon"], "Cook and cool quinoa; combine with peas, cucumber, mint and lemon."),
    recipe("trout-potatoes", "Trout with potatoes & green beans", "fish", ["trout", "potatoes", "green beans", "olive oil", "dill"], "Bake trout; boil potatoes and green beans. Finish with dill and olive oil.", ["fish", "nightshades"]),
    recipe("hummus-plate", "Hummus & crunchy vegetable plate", "legumes", ["chickpeas", "tahini", "carrots", "cucumber", "lemon"], "Blend chickpeas, tahini and lemon into hummus; serve with vegetable sticks.", ["sesame"]),
    recipe("yogurt-pear", "Plain yogurt, pear & pumpkin seeds", "breakfast", ["yogurt", "pear", "pumpkin seeds", "oats"], "Combine plain unsweetened yogurt with sliced pear, oats and seeds.", ["dairy", "gluten"]),
    recipe("egg-spinach", "Spinach omelette & rye toast", "eggs", ["eggs", "spinach", "mushrooms", "rye bread", "olive oil"], "Cook spinach and mushrooms, add eggs, and serve with rye toast.", ["eggs", "gluten"]),
    recipe("lentil-stuffed", "Lentil-stuffed courgettes", "legumes", ["lentils", "courgette", "tomatoes", "brown rice", "parsley"], "Fill halved courgettes with cooked lentils, rice and tomato; bake until tender.", ["nightshades"]),
    recipe("mackerel-beet", "Mackerel & beetroot salad", "fish", ["mackerel", "beetroot", "cucumber", "beans", "lemon"], "Serve cooked mackerel with beetroot, cucumber and beans; dress with lemon.", ["fish"]),
    recipe("tofu-brown-rice", "Tofu, brown rice & broccoli", "soy", ["tofu", "brown rice", "broccoli", "ginger", "olive oil"], "Pan-sear tofu, steam broccoli and serve with brown rice and grated ginger.", ["soy"]),
    recipe("overnight-apple", "Apple & cinnamon overnight oats", "breakfast", ["oats", "apple", "chia seeds", "cinnamon", "yogurt"], "Soak oats and chia with plain yogurt and water overnight; add apple and cinnamon.", ["dairy", "gluten"]),
    recipe("bean-cabbage", "White beans with cabbage & dill", "legumes", ["beans", "cabbage", "carrots", "dill", "olive oil"], "Soften cabbage and carrots in a little oil; add cooked beans and dill."),
    recipe("roasted-beet-quinoa", "Beetroot, quinoa & walnut bowl", "whole_grains", ["beetroot", "quinoa", "walnuts", "spinach", "lemon"], "Roast beetroot, cook quinoa and toss with spinach, walnuts and lemon.", ["nuts"]),
]
BY_ID = {r["id"]: r for r in RECIPES}
CANONICAL = sorted({i for r in RECIPES for i in r["ingredients"]})

def matches(haystack, phrase):
    return bool(re.search(r"(?<!\w)" + re.escape(normalized(phrase)) + r"(?!\w)", normalized(haystack)))

def recognize(description):
    return {ingredient for ingredient in CANONICAL if any(matches(description, alias) for alias in ALIASES.get(ingredient, [ingredient]))}

def suggest(history, excluded, feedback, avoid, seed=0):
    category_aliases = {"milk": "dairy", "lapte": "dairy", "nut": "nuts", "peste": "fish", "soia": "soy"}
    avoid = sorted({term for word in avoid for term in [normalized(word), category_aliases.get(normalized(word), normalized(word)), *recognize(word)]})
    counts = Counter()
    recent = Counter()
    for position, meal in enumerate(history):
        ingredients = recognize(meal["description"] + " " + " ".join(meal.get("ingredients", [])))
        counts.update(ingredients)
        if position < 7:
            recent.update(ingredients)
    candidates = []
    for index, item in enumerate(RECIPES):
        if item["id"] in excluded or feedback.get(item["id"]) == "skip":
            continue
        if any(any(matches(name, word) or matches(word, name) for name in item["ingredients"] + item["tags"]) for word in avoid):
            continue
        familiar = [i for i in item["ingredients"] if counts[i] >= 2]
        novel = [i for i in item["ingredients"] if counts[i] == 0]
        rank = sum(min(counts[i], 5) * .5 for i in familiar) + min(len(novel), 2) * 1.2
        rank -= sum(recent[i] * .45 for i in item["ingredients"])
        rank += 3 if feedback.get(item["id"]) == "like" else 0
        # Stable tie rotation, no random/LLM choices; prior batches change the seed.
        rank += ((index + seed * 7) % len(RECIPES)) * .02
        candidates.append((rank, item, familiar, novel))
    chosen = []
    groups = set()
    while candidates and len(chosen) < 3:
        best = max(candidates, key=lambda c: c[0] - (4 if c[1]["group"] in groups else 0))
        candidates.remove(best)
        _, item, familiar, novel = best
        idea = dict(item)
        idea["familiar_ingredients"] = familiar
        idea["new_ingredients"] = novel
        idea["feedback"] = feedback.get(item["id"])
        reasons = []
        if feedback.get(item["id"]) == "like": reasons.append("You liked this idea.")
        if familiar: reasons.append("Often logged: " + ", ".join(f"{i} ({counts[i]} meals)" for i in familiar) + ".")
        if novel: reasons.append("A change to try: " + ", ".join(novel[:2]) + ".")
        idea["why"] = " ".join(reasons) or "A different Mediterranean-style option for variety."
        chosen.append(idea)
        groups.add(item["group"])
    return dict(version=VERSION, ideas=chosen,
        context_meal_count=len(history),
        preferences=[dict(ingredient=i, meals=count) for i, count in counts.most_common(8) if count >= 2],
        note="Repeated logging suggests familiarity, not proven enjoyment. Recent foods and the last two idea batches are down-ranked or excluded. "
             "These are Mediterranean-style ideas, not a guarantee against inflammation or a psoriasis flare.",
        empty_reason="No more matching ideas in this rotation. Adjust exclusions or use a previous idea." if not chosen else None)
