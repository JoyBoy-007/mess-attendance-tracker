import base64
import hashlib
import json
import mimetypes
import os
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.core.cache import cache

from .models import NutritionFood


class NutritionLookupError(Exception):
    pass


def _normalize(value):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).split())


def _find_local_food(query):
    normalized_query = _normalize(query)
    if not normalized_query:
        raise NutritionLookupError("Enter a food name first.")
    for food in NutritionFood.objects.all():
        candidates = [food.name, *(food.aliases.split(",") if food.aliases else [])]
        if any(_normalize(candidate) == normalized_query for candidate in candidates):
            return food
    return None


def _portion_grams(raw_portion, food):
    serving_grams = Decimal(str(food.serving_grams))
    portion = (raw_portion or "").strip().casefold()
    if not portion:
        return serving_grams, f"1 {food.serving_unit} ({serving_grams:g} g)"

    match = re.fullmatch(r"(\d+(?:\.\d+)?)?\s*([a-zA-Z]+)?", portion)
    if not match:
        raise NutritionLookupError("Enter a portion such as 150 g, 1 bowl, or 2 roti.")
    try:
        amount = Decimal(match.group(1) or "1")
    except InvalidOperation as error:
        raise NutritionLookupError("Enter a valid portion amount.") from error
    unit = (match.group(2) or "").casefold()
    if amount <= 0 or amount > 10000:
        raise NutritionLookupError("Portion amount must be greater than zero and at most 10,000.")

    units_in_grams = {
        "g": Decimal("1"), "gram": Decimal("1"), "grams": Decimal("1"),
        "kg": Decimal("1000"), "ml": Decimal("1"),
        "bowl": Decimal("200"), "bowls": Decimal("200"),
        "cup": Decimal("240"), "cups": Decimal("240"),
        "plate": Decimal("300"), "plates": Decimal("300"),
        "tbsp": Decimal("15"), "tablespoon": Decimal("15"),
        "tsp": Decimal("5"), "teaspoon": Decimal("5"),
        "piece": Decimal("50"), "pieces": Decimal("50"),
        "slice": Decimal("25"), "slices": Decimal("25"),
    }
    if not unit or unit in {"serving", "servings", "portion", "portions"}:
        grams = amount * serving_grams
        label = f"{amount:g} {food.serving_unit}"
    elif unit in {food.serving_unit.casefold(), f"{food.serving_unit.casefold()}s"}:
        grams = amount * serving_grams
        label = f"{amount:g} {food.serving_unit}"
    elif unit in units_in_grams:
        grams = amount * units_in_grams[unit]
        label = f"{amount:g} {unit}"
    else:
        raise NutritionLookupError(f"I don’t know the unit ‘{unit}’. Use grams, bowls, cups, plates, or {food.serving_unit}.")

    return grams, f"{label} ({grams:g} g)"


def _request_gemini(api_key, model, payload):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "MessMate/1.0 (Gemini nutrition lookup)",
        },
        method="POST",
    )
    return urlopen(req, timeout=15)


def _lookup_gemini_food(food_name, portion):
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise NutritionLookupError(
            "That food isn’t in the local list. Add your Google Gemini API key as GEMINI_API_KEY in .env to enable AI nutrition lookup."
        )

    normalized_sig = f"{_normalize(food_name)}:{_normalize(portion or 'default')}"
    cache_key = f"gemini_nutrition_{hashlib.sha256(normalized_sig.encode('utf-8')).hexdigest()}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    prompt = f"""You are a certified clinical nutritionist and food database engine.
Accurately estimate the nutritional content (calories in kcal, protein in grams, carbohydrates in grams, total fat in grams) for the following food item and portion.
Provide realistic values for typical preparations (especially Indian mess/canteen/hostel, home-style, or restaurant foods when relevant).

Food item: {food_name.strip()}
Portion / Serving: {portion.strip() if portion and portion.strip() else "1 standard serving"}

Return ONLY a valid JSON object matching this exact schema:
{{
  "food": "{food_name.strip()}",
  "portion": "normalized portion description with approximate weight in grams, e.g. 1 bowl (approx 180 g) or 2 pieces (70 g)",
  "serving_grams": 180,
  "calories": 160.0,
  "protein_g": 6.5,
  "carbs_g": 24.0,
  "fat_g": 4.0
}}
Do not wrap in markdown code blocks if possible. Return only JSON."""

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
        },
    }

    primary_model = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest").strip()
    models_to_try = [primary_model]
    for fallback in ["gemini-flash-latest", "gemini-3.8-flash", "gemini-3.5-flash"]:
        if fallback not in models_to_try:
            models_to_try.append(fallback)

    res_payload = None
    last_error = None

    for model in models_to_try:
        try:
            with _request_gemini(api_key, model, payload) as response:
                res_payload = json.loads(response.read().decode("utf-8"))
                break
        except HTTPError as error:
            last_error = error
            if error.code in (404, 503) and model != models_to_try[-1]:
                continue
            if error.code == 429:
                if model != models_to_try[-1]:
                    continue
                raise NutritionLookupError("Google Gemini API is temporarily busy or rate-limited. Try again shortly.") from error
            if error.code in (400, 401, 403):
                raise NutritionLookupError("Google Gemini API key was rejected or invalid. Check GEMINI_API_KEY in .env.") from error
            if model != models_to_try[-1]:
                continue
            raise NutritionLookupError(f"Gemini API returned HTTP {error.code}. Try again later.") from error
        except (URLError, TimeoutError, UnicodeDecodeError) as error:
            raise NutritionLookupError("Google Gemini API is unreachable right now. Check your internet connection and try again.") from error
        except json.JSONDecodeError as error:
            raise NutritionLookupError("Could not decode response from Gemini API.") from error

    if res_payload is None and last_error:
        raise NutritionLookupError("Google Gemini service is currently unavailable.")

    try:
        candidate = res_payload.get("candidates", [])[0]
        text_content = candidate.get("content", {}).get("parts", [])[0].get("text", "")
    except (IndexError, KeyError, AttributeError):
        raise NutritionLookupError("Gemini could not analyze this food. Please check the food name or enter macros manually.")

    raw_text = text_content.strip()
    if raw_text.startswith("```"):
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)

    try:
        data = json.loads(raw_text)
        cal = Decimal(str(data["calories"])).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        prot = Decimal(str(data.get("protein_g", 0))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        carb = Decimal(str(data.get("carbs_g", 0))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        fat = Decimal(str(data.get("fat_g", 0))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        serving_desc = str(data.get("portion") or (portion.strip() if portion else "1 serving"))[:60]
        grams = str(data.get("serving_grams", "100"))
        cleaned_food = str(data.get("food") or food_name.strip())[:100]
    except (KeyError, ValueError, InvalidOperation, json.JSONDecodeError) as error:
        raise NutritionLookupError("Gemini returned an unreadable nutrition format. Try a clearer food name or enter macros manually.") from error

    result = {
        "food": cleaned_food,
        "serving": serving_desc,
        "portion": serving_desc,
        "default_serving": (portion.strip() if portion and portion.strip() else serving_desc),
        "grams": grams,
        "source": "Gemini AI",
        "macros": {
            "calories": str(cal),
            "protein_g": str(prot),
            "carbs_g": str(carb),
            "fat_g": str(fat),
        },
    }
    cache.set(cache_key, result, 60 * 60 * 24)
    return result


def calculate_macros(food_name, portion):
    if not food_name or not food_name.strip():
        raise NutritionLookupError("Enter a food name first.")

    food = _find_local_food(food_name)
    if food is not None:
        try:
            grams, portion_label = _portion_grams(portion, food)
            scale = grams / Decimal("100")
            result = {}
            for field in ("calories", "protein_g", "carbs_g", "fat_g"):
                value_per_100g = Decimal(str(getattr(food, field)))
                result[field] = str((value_per_100g * scale).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
            return {
                "food": food.name,
                "serving": portion_label,
                "portion": portion_label,
                "default_serving": (portion.strip() or f"1 {food.serving_unit}"),
                "grams": str(grams),
                "source": "local food list",
                "macros": result,
            }
        except NutritionLookupError:
            # If portion parsing failed for local food, fall through to Gemini to understand the portion
            pass

    return _lookup_gemini_food(food_name, portion)


def analyze_food_photo(upload):
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise NutritionLookupError(
            "Add your Google Gemini API key as GEMINI_API_KEY in .env to enable food photo analysis."
        )

    content = upload.read()
    upload.seek(0)
    if not content:
        raise NutritionLookupError("The uploaded file is empty.")
    if len(content) > 10 * 1024 * 1024:
        raise NutritionLookupError("Please choose a photo smaller than 10 MB.")

    mime_type = mimetypes.guess_type(getattr(upload, "name", "photo.jpg"))[0] or "image/jpeg"
    if mime_type not in ("image/jpeg", "image/png", "image/webp"):
        mime_type = "image/jpeg"

    image_b64 = base64.b64encode(content).decode("ascii")

    prompt = """You are an expert clinical dietitian and computer vision nutritionist.
Carefully examine this meal or plate photo.
Identify each food, dish, or beverage visible (including Indian mess/hostel dishes, thali items, single dishes, snacks, or sides).

For each item identified:
1. "name": Clear, specific dish name (e.g. "Dal Tadka", "Roti / Chapati", "Jeera Rice", "Paneer Butter Masala", "Curd", "Boiled Egg").
2. "serving": Realistic portion description with estimated weight in grams (e.g. "2 pieces (approx 70 g)", "1 bowl (approx 150 g)", "1 cup (approx 150 g)").
3. "calories": Total estimated calories in kcal for that portion (number).
4. "protein_g": Protein in grams (number).
5. "carbs_g": Total carbohydrates in grams (number).
6. "fat_g": Total fat in grams (number).

Return ONLY a valid JSON object matching this schema:
{
  "summary": "Brief 1-sentence description of the meal (e.g. 'Indian thali with 2 rotis, dal tadka, and mixed vegetable sabzi')",
  "total_calories": 520,
  "foods": [
    {
      "name": "Roti",
      "serving": "2 pieces (approx 70 g)",
      "calories": 210.0,
      "protein_g": 6.8,
      "carbs_g": 38.0,
      "fat_g": 3.2
    }
  ]
}
If no food is visible in the photo, return {"summary": "No recognizable food items found", "total_calories": 0, "foods": []}.
Do not include markdown code fences or explanatory text outside the JSON."""

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": image_b64,
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
        },
    }

    primary_model = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest").strip()
    models_to_try = [primary_model]
    for fallback in ["gemini-flash-latest", "gemini-3.8-flash", "gemini-3.5-flash"]:
        if fallback not in models_to_try:
            models_to_try.append(fallback)

    res_payload = None
    last_error = None

    for model in models_to_try:
        try:
            with _request_gemini(api_key, model, payload) as response:
                res_payload = json.loads(response.read().decode("utf-8"))
                break
        except HTTPError as error:
            last_error = error
            if error.code in (404, 503) and model != models_to_try[-1]:
                continue
            if error.code == 429:
                if model != models_to_try[-1]:
                    continue
                raise NutritionLookupError("Google Gemini API is temporarily busy or rate-limited. Try again shortly.") from error
            if error.code in (400, 401, 403):
                raise NutritionLookupError("Google Gemini API key was rejected or invalid. Check GEMINI_API_KEY in .env.") from error
            if model != models_to_try[-1]:
                continue
            raise NutritionLookupError(f"Gemini API returned HTTP {error.code}. Try again later.") from error
        except (URLError, TimeoutError, UnicodeDecodeError) as error:
            raise NutritionLookupError("Google Gemini API is unreachable right now. Check your internet connection and try again.") from error
        except json.JSONDecodeError as error:
            raise NutritionLookupError("Could not decode response from Gemini API.") from error

    if res_payload is None and last_error:
        raise NutritionLookupError("Google Gemini vision service is currently unavailable.")

    try:
        candidate = res_payload.get("candidates", [])[0]
        text_content = candidate.get("content", {}).get("parts", [])[0].get("text", "")
    except (IndexError, KeyError, AttributeError):
        raise NutritionLookupError("Gemini could not analyze this food photo. Please try another image.")

    raw_text = text_content.strip()
    if raw_text.startswith("```"):
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise NutritionLookupError("Gemini returned an invalid format for the photo. Try another photo.") from error

    foods_list = []
    total_cal = Decimal("0")
    for item in data.get("foods", []):
        try:
            cal = Decimal(str(item.get("calories", 0))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            prot = Decimal(str(item.get("protein_g", 0))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            carb = Decimal(str(item.get("carbs_g", 0))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            fat = Decimal(str(item.get("fat_g", 0))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            name = str(item.get("name") or "Dish")[:100].strip()
            serving = str(item.get("serving") or "1 serving")[:60].strip()
            total_cal += cal
            foods_list.append({
                "name": name,
                "serving": serving,
                "calories": str(cal),
                "protein_g": str(prot),
                "carbs_g": str(carb),
                "fat_g": str(fat),
            })
        except (InvalidOperation, ValueError):
            continue

    return {
        "summary": str(data.get("summary") or "Food photo analysis"),
        "total_calories": str(total_cal),
        "foods": foods_list,
        "source": "Gemini AI Vision",
    }

