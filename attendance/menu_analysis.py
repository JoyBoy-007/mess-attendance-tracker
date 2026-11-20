import base64
import json
import mimetypes
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class MenuAnalysisError(Exception):
    pass


def analyze_menu_photo(upload):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise MenuAnalysisError("Add OPENAI_API_KEY to the app environment to analyze menu photos.")

    content = upload.read()
    upload.seek(0)
    mime_type = mimetypes.guess_type(upload.name)[0] or "image/jpeg"
    image_data = base64.b64encode(content).decode("ascii")

    meals = ["BREAKFAST", "LUNCH", "SNACKS", "DINNER"]
    day_schema = {
        "type": "object",
        "properties": {"day": {"type": "string", "enum": [
            "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
        ]}, "meals": {"type": "object", "properties": {
            meal: {"type": "string"} for meal in meals
        }, "required": meals, "additionalProperties": False}},
        "required": ["day", "meals"],
        "additionalProperties": False,
    }
    payload = {
        "model": os.environ.get("OPENAI_MENU_MODEL", "gpt-4.1-mini"),
        "store": False,
        "max_output_tokens": 2500,
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": (
                "Read this mess menu photo. Extract only dishes that are legible. "
                "Return all seven weekdays and the four meal slots BREAKFAST, LUNCH, "
                "SNACKS, DINNER. Put each slot's dishes in one concise string, separated "
                "by commas. Leave a slot empty when it is absent or unreadable. Do not "
                "guess ingredients or nutrition values. Preserve the menu's wording."
            )},
            {"type": "input_image", "image_url": f"data:{mime_type};base64,{image_data}"},
        ]}],
        "text": {"format": {
            "type": "json_schema",
            "name": "weekly_mess_menu",
            "strict": True,
            "schema": {"type": "object", "properties": {
                "days": {"type": "array", "items": day_schema,
                         "minItems": 7, "maxItems": 7}
            }, "required": ["days"], "additionalProperties": False},
        }},
    }
    request = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=90) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code in (401, 403):
            raise MenuAnalysisError("The OpenAI API key was rejected. Check OPENAI_API_KEY.") from error
        if error.code == 429:
            raise MenuAnalysisError("OpenAI is rate limited or out of API credit. Try again later.") from error
        raise MenuAnalysisError("The menu could not be analyzed. Check the API settings and try again.") from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise MenuAnalysisError("Could not reach the menu analysis service. Try again.") from error

    output_text = "".join(
        content.get("text", "")
        for item in result.get("output", [])
        if item.get("type") == "message"
        for content in item.get("content", [])
        if content.get("type") == "output_text"
    )
    try:
        parsed = json.loads(output_text)
        weekdays = {day: index for index, day in enumerate(
            ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
        )}
        return {
            (weekdays[day["day"]], meal): day["meals"][meal].strip()[:600]
            for day in parsed["days"]
            for meal in meals
        }
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise MenuAnalysisError("The analysis returned an unreadable menu. Try another photo.") from error
