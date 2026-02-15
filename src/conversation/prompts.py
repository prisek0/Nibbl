"""Claude prompt templates for all Nibbl tasks."""

SYSTEM_CONVERSATION = """You are Nibbl, a friendly family dinner planning assistant \
communicating via iMessage. Keep messages short and conversational — this is texting, not email.

Guidelines:
- Keep messages under 300 characters when possible (iMessage readability)
- Use line breaks for lists
- Be encouraging about kids' food preferences
- If someone says something unrelated to food, acknowledge briefly and redirect
- Respond in {language_name}
- If the family member writes in a different language, match their language
- Use a warm, casual tone like a helpful family friend"""

PREFERENCE_EXTRACTION = """\
A family member just sent a message about dinner preferences.

Family member: {member_name} ({member_role})
Message: "{message_text}"

Known preferences for this person:
{existing_preferences}

Extract any food preferences, dislikes, dietary needs, or specific dinner wishes.
Return valid JSON only (no markdown fencing):

{{
  "preferences": [
    {{
      "category": "likes|dislikes|allergy|dietary|cuisine_preference|general",
      "detail": "description of the preference",
      "confidence": 0.0-1.0,
      "is_update": false
    }}
  ],
  "specific_wishes": ["concrete dinner requests for this week"],
  "has_food_content": true
}}

Set "has_food_content" to false if the message has nothing to do with food preferences.
If the message confirms an existing preference, set "is_update" to true with higher confidence.
Return empty arrays if nothing food-related was expressed."""

MEAL_PLAN_GENERATION = """\
Generate a {num_days}-day dinner plan starting from {start_date}.

## Family members
{family_profiles}

## This week's specific requests
{specific_wishes}

## Known preferences per member
{all_preferences}

## Recent meals (last 3 weeks, avoid repeats)
{recent_history}

## Season & context
Current month: {month}, season: {season}. Prefer seasonal ingredients available in the Netherlands.

## Rules
- Vary cuisines across the week (no same cuisine on consecutive days)
- Vary main proteins (no same protein two days in a row)
- Include at least one vegetarian meal
- At least 2 meals should be kid-friendly (simple flavors, familiar formats)
- Mix quick meals (< 30 min) with more elaborate ones
- Ingredients must be commonly available at a Dutch supermarket (Picnic)
- Use metric units and Dutch ingredient names (for Picnic supermarket search)
- Write recipe names, descriptions, and instructions in {language}
- Honor specific family requests

Return valid JSON only (no markdown fencing):

{{
  "plan": [
    {{
      "date": "YYYY-MM-DD",
      "recipe": {{
        "name": "Recipe name",
        "description": "1-2 sentence description",
        "servings": {family_size},
        "prep_time_minutes": 15,
        "cook_time_minutes": 25,
        "cuisine": "Italian",
        "tags": ["quick", "kid-friendly"],
        "ingredients": [
          {{"name": "kipfilet", "quantity": 400, "unit": "g", "category": "meat"}},
          {{"name": "spaghetti", "quantity": 500, "unit": "g", "category": "pantry"}}
        ],
        "instructions": "1. Step one\\n2. Step two\\n3. Step three"
      }}
    }}
  ],
  "reasoning": "Brief explanation of why these meals were chosen"
}}"""

MEAL_PLAN_REVISION = """\
The parent reviewed the meal plan and wants changes.

Current plan (JSON):
{current_plan}

Parent's feedback: "{feedback}"

## Instructions
- Only change the meals the parent is unhappy with
- Keep meals that weren't mentioned in the feedback exactly as they are (same date, recipe, ingredients)
- For replaced meals, provide complete recipes with all ingredients and instructions
- Use Dutch ingredient names (for Picnic supermarket search)
- Use metric units

Return the COMPLETE revised plan as valid JSON only (no markdown fencing):

{{
  "plan": [
    {{
      "date": "YYYY-MM-DD",
      "recipe": {{
        "name": "Recipe name",
        "description": "1-2 sentence description",
        "servings": 4,
        "prep_time_minutes": 15,
        "cook_time_minutes": 25,
        "cuisine": "Italian",
        "tags": ["quick", "kid-friendly"],
        "ingredients": [
          {{"name": "kipfilet", "quantity": 400, "unit": "g", "category": "meat"}}
        ],
        "instructions": "1. Step one\\n2. Step two"
      }}
    }}
  ],
  "reasoning": "Brief explanation of what was changed and why"
}}"""

CLASSIFY_MESSAGE = """\
Classify this incoming message from a family member in the context of dinner planning.

Message: "{message_text}"
Current planning phase: {current_state}
Sender role: {sender_role}

Return valid JSON only:

{{
  "intent": "trigger|preference|approval|rejection|change_request|pantry_response|cancel|greeting|other",
  "confidence": 0.0-1.0,
  "summary": "brief description of what the person is saying"
}}

Intent definitions:
- trigger: wants to start meal planning ("plan dinner", "wat eten we", "boodschappen")
- preference: expressing food wishes or preferences
- approval: approving/accepting the meal plan ("looks good", "akkoord", "ja")
- rejection: rejecting the plan entirely ("nee", "helemaal opnieuw")
- change_request: wants specific changes ("swap X for Y", "geen vis op dinsdag")
- pantry_response: listing items they already have at home
- cancel: wants to stop the current planning session
- greeting: just saying hi
- other: unrelated to dinner planning"""

GENERATE_SEARCH_TERMS = """\
Generate Dutch supermarket search terms for finding this ingredient at Picnic (Dutch online supermarket).

Ingredient: {ingredient_name}, {quantity} {unit}
Category: {category}

Return valid JSON only — an array of 2-3 search terms in Dutch, most likely term first:
["term1", "term2"]

Focus on how the product would be named on a supermarket shelf."""

SELECT_BEST_PRODUCT = """\
Select the best supermarket product match for this recipe ingredient.

Recipe needs: {quantity} {unit} of {ingredient_name}

Available Picnic products:
{products_list}

Consider:
1. Does the product match the ingredient?
2. Is the quantity sufficient? (if recipe needs 400g and pack is 300g, set count to 2)
3. Prefer basic/unflavored versions unless recipe specifies otherwise
4. Prefer the most common/cheapest option

Return valid JSON only:

{{
  "product_id": "the_id",
  "product_name": "product name",
  "count": 1,
  "confidence": 0.0-1.0,
  "note": "optional note about the match"
}}

If no good match exists, return {{"product_id": null, "confidence": 0, "note": "reason"}}"""

MATCH_PANTRY_ITEMS = """\
The parent said which ingredients they already have at home.

Parent's message: "{message}"

Ingredient list (these are the ingredients needed for the meal plan):
{ingredients}

Match the parent's message against the ingredient list. The parent may use:
- English names for Dutch ingredients (e.g., "olive oil" = "olijfolie")
- Abbreviations or informal names (e.g., "rice" = "rijst", "pasta" = "spaghetti")
- Plural or singular forms
- General terms that cover specific items (e.g., "oil" covers "olijfolie" and "zonnebloemolie")
- If the parent says "nothing" or "none" or similar, return an empty array

Return valid JSON only — an array of ingredient names exactly as they appear in the ingredient list:
["olijfolie", "rijst"]

Only include ingredients that the parent clearly indicates they have at home."""

