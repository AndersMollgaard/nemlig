---
name: nemlig-recipes
description: Turn the planned nemlig.com dinners into a recipe page to cook from, a private claude.ai page with a card per night, ingredients split into bought and at home, and the steps. Use when the user asks for recipes, a recipe page, or how to cook the planned dinners. Does not plan dinners or change the basket.
allowed-tools: Bash(nemlig:*), Bash(uv run nemlig:*)
---

# Recipe page for the planned dinners

Claude writes the recipes. The page design is fixed in `template.html`, and `render.py` fills it
from a JSON file, so a run only writes content. `example.json` in this skill's directory is a
real week and shows the shape. Read it once before writing. Don't edit the template for one run.

## Subagent: started by `nemlig-fill-basket`

The brief in the prompt is the whole input. Don't run `nemlig`, don't change the basket, and
don't ask anything, because nobody is waiting on you. Write the page as in *Writing* and
*Render and publish*, then hand back one line: `Recipes: <url>`, or `Recipes failed: <reason>`.

The brief looks like this:
```
Recipe brief
household: 2 adults, 2 children aged 6 and 4
diet: none
delivery: ons. 07/10 kl. 16-21
dishes:
- Laks i citron-flødesauce med spaghetti og spinat | 25 min | 144.45 kr | Italian, pan
  bought: Laksefilet m. skind 600 g x1; Babyspinat øko 100 g x1; Citron lille øko x1 (of 2, the other is for the chicken); Madlavningsfløde 15% 0,25 l x2
  at home: spaghetti, Grana Padano, garlic, butter
- Ovnstegt kylling med citron, kartofler og gulerødder | 75 min | 114.75 kr | Danish, oven
  ...
```

## Alone: the user asked for recipes

1. **Dishes.** Take them from the `nemlig-dinners` picks in this conversation. Without them,
   ask the user which dishes. Never guess dishes from basket lines.
2. **What was bought.** Use the latest basket output in the conversation from after the dinner
   add. If there isn't one, run `nemlig --text basket` once. It also gives the delivery slot.
3. Write, render and publish as below. Reply with the link and the order of the nights in one
   line each.

## Writing

- **Language.** The page is in English, like the template's labels. Dish and product names stay
  in Danish, as on nemlig.
- **Days.** Use the days in the brief or the conversation. Otherwise the first night is the
  delivery day if the slot ends by 17:00, and the day after if not, and the nights follow on
  from there. Cook what keeps the shortest first: fish, then minced meat, then other fresh meat
  and poultry, then vegetarian and frozen. A leftover dish comes right after the night it uses.
- **Portions.** Cook for the household: a full portion per adult and half per child, as
  `nemlig-dinners` counts them. `serves` is the number of people, plus "a lunch" when there is
  clearly more.
- **Ingredients.** `basket` lists what came from nemlig, with the product name and a pack note
  ("the whole pack", "of 2 kg", "1 of 2"). Name the kind and the pack, not the brand, so a
  cheaper swap of the same kind keeps the page right. `home` lists the rest, with amounts. A
  basket product that wasn't bought for the dish, such as butter, still goes under `basket`.
- **Steps.** 4–8 numbered steps, one action each, in the imperative. Give the heat, the time
  and a sign that it's done. Oven: "200 °C (180 °C fan)". Use a core temperature where it
  matters (poultry 75 °C). Use metric units: g, kg, dl, l, tsp, tbsp.
- **Notes.** At most two per night:
  - `Kids`: how to make it work for the household's children. Only include it when there are
    children.
  - `Left over`: what's left and how long it keeps.
  - `Save`: something another night uses. Name it on both nights.
  - `Make ahead`: a step that can be done earlier.
- **Kind** sets the card's colour: `fish`, `poultry`, `beef`, `pork`, `lamb` or `veg`. `tag`
  overrides the label ("Chicken"). `short` is the nav label, usually the anchor ("Laks").
- **Header.** The title is `Week NN Dinners`, where NN is the ISO week of the first night
  (`date -d YYYY-MM-DD +%V`). The eyebrow gives the week and the delivery slot. The lede is
  one or two sentences on the plan and the cooking order. The facts are the number of
  dinners, the portions and the total cost from the brief.

## Render and publish

1. Write the JSON to the scratchpad as `week-NN-dinners.json`.
2. Render it into the same directory:
   ```sh
   uv run python SKILL_DIR/render.py week-NN-dinners.json week-NN-dinners.html
   ```
   `SKILL_DIR` is this skill's base directory. On `error:`, fix the JSON and render again.
3. Publish `week-NN-dinners.html` with the Artifact tool, with icon `recipe` and a one-sentence
   description ("Recipes for the three dinners in Wednesday 7 October's nemlig order"). Each
   week gets a new page. Publishing the same path again in the same session updates that page.
   The page is private until the user shares it.
