# MessMate — Mess Attendance Tracker

A small Django app for recording whether you ate each meal in your mess. Built with Django and SQLite, with a responsive dashboard and Django admin.

## Features

- Track Breakfast, Lunch, Snacks, and Dinner for any date.
- Mark each meal Eaten or Skipped; unmarked meals remain Not Marked.
- Add foods and portion details to eaten meals.
- Record calories, protein, carbohydrates, and fat for each portion.
- See daily macro totals and per-meal food details. A skipped mess meal can still record foods eaten elsewhere.
- Change or clear a meal's status later; remove food entries when needed.
- Enforce one attendance record per meal per date in the database.
- Manage attendance and foods through Django admin.

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
