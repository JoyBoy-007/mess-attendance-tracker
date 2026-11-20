# MessMate — Mess Attendance Tracker

A small Django app for recording whether you ate each meal in your mess. Built with Django and SQLite, with a responsive dashboard and Django admin.

## Features

- **Instant Guest Mode & Optional Accounts**: Anyone visiting the site lands directly on the interactive dashboard and can immediately track meals, calculate macros, and scan food photos without logging in. When ready to save data permanently across devices, users can click **Save Data (Sign Up)** or **Log In**; any meals or food logs tracked during the guest session are automatically migrated to their personal account.
- **Google Calendar-Style Dashboard**: Modern calendar header with a one-click **Today** shortcut, week day strip with real-time meal attendance heatmap dots, and an interactive mini-month calendar picker.
- **Meal Attendance Tracking**: Track Breakfast, Lunch, Snacks, and Dinner for any date. Mark meals as Eaten or Skipped; unmarked meals remain Not Marked.
- **Automatic Macro & Calorie Calculation**: Add foods with portions (e.g. "2 roti", "1 bowl dal tadka") and calories/macros are automatically calculated using Google Gemini AI, with a seeded local offline food list fallback.
- **AI Food Photo Scanning**: Take a photo of your plate or upload an image. Gemini AI Vision analyzes your meal, detects dishes, portions, calories, and macros, and allows one-click bulk addition to your meal log.
- **Weekly Menu Photo Analysis**: Upload a weekly mess menu photo and use vision AI to extract the seven-day, four-meal dish schedule.
- **Planned Dishes Integration**: See mess menu dishes on your daily dashboard and click any dish to prefill your meal log.
- **Django Admin**: Manage users, attendance, food items, and nutrition database through the Django admin panel.

## Quick start

Requires Python 3.10 or newer.

```bash
python -m venv .venv
```

Activate the environment, then install dependencies and initialize the database:

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Open <http://127.0.0.1:8000/>. To use Django admin, create a staff account with `python manage.py createsuperuser`, then visit <http://127.0.0.1:8000/admin/>.

## Tests

```bash
python manage.py test attendance
python manage.py check
```

## Configuration

The local development settings use SQLite and the Asia/Kolkata time zone. For deployment, set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`, and `DJANGO_ALLOWED_HOSTS` in the environment. Do not commit secrets or the local SQLite database.

Menu photo analysis requires an OpenAI API key with Responses API access. Keep the key on the server; do not put it in source code or a browser script. On PowerShell, set it for the current terminal before starting Django:

```powershell
$env:OPENAI_API_KEY = "your-api-key"
python manage.py runserver
```

The optional `OPENAI_MENU_MODEL` environment variable changes the vision model (default: `gpt-4.1-mini`). When you choose **Analyze and fill meals**, the uploaded image is sent to OpenAI for extraction and may incur API charges. The source image is also stored in the app's local `media/menus/` folder, which is excluded from Git.

Macro lookup checks the SQLite nutrition list first. If there is no exact local match, it uses Google Gemini AI to analyze the food name and portion (e.g. "2 butter roti", "1 bowl dal makhani", "1 plate poha") and estimates calories, protein, carbohydrates, and fat. These values are estimates; you can review and edit them before saving. The local list remains available offline if the Gemini API key is not configured or the service is unavailable.

To enable AI nutrition lookup, get a free API key from [Google AI Studio](https://aistudio.google.com/). Keep it on the server and out of source control. You can place it in your local `.env` file (`GEMINI_API_KEY=your-api-key`) or set it in PowerShell:

```powershell
$env:GEMINI_API_KEY = "your-gemini-api-key"
python manage.py runserver
```

The optional `GEMINI_MODEL` environment variable changes the Gemini model (default: `gemini-flash-lite-latest`, with automatic fallback to `gemini-flash-latest` and `gemini-3.8-flash`). Nutrition lookups are cached locally for 24 hours to reduce API requests.
