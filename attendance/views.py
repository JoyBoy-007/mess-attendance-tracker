from datetime import date
from datetime import timedelta
from decimal import Decimal
import json
import os

from django.contrib import messages
from django.contrib.auth import get_user_model, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .forms import LoginForm, MealFoodForm, SignUpForm, WeeklyMenuPhotoForm
from .menu_analysis import MenuAnalysisError, analyze_menu_photo
from .local_nutrition import NutritionLookupError, calculate_macros, analyze_food_photo
from .models import MealAttendance, MealFood, WeeklyMenu, WeeklyMenuEntry

User = get_user_model()


MACRO_FIELDS = ("calories", "protein_g", "carbs_g", "fat_g")


def _macro_totals(queryset):
    totals = queryset.aggregate(**{field: Sum(field) for field in MACRO_FIELDS})
    return {field: totals[field] or Decimal("0") for field in MACRO_FIELDS}


def _get_owner_filter(request):
    """
    Returns query filter dict for scoping queries to the current authenticated user or guest session.
    Also links legacy unassigned records to the first session so dev data is immediately visible.
    """
    if request.user.is_authenticated:
        return {"user": request.user}

    if not request.session.session_key:
        request.session.create()
    session_key = request.session.session_key

    # Claim unassigned legacy records for this first guest session
    legacy_qs = MealAttendance.objects.filter(user__isnull=True, session_key__isnull=True)
    if legacy_qs.exists() and not MealAttendance.objects.filter(session_key=session_key).exists():
        legacy_qs.update(session_key=session_key)

    return {"user__isnull": True, "session_key": session_key}


def _get_owner_defaults(request):
    """
    Returns model field defaults to assign ownership when creating new attendance records.
    """
    if request.user.is_authenticated:
        return {"user": request.user, "session_key": None}

    if not request.session.session_key:
        request.session.create()
    return {"user": None, "session_key": request.session.session_key}


def _claim_guest_records(request, user):
    """
    Transfers any guest attendance records tracked in this browser session
    to the authenticated user account so their data is permanently saved.
    """
    session_key = request.session.session_key
    migrated_count = 0
    if session_key:
        guest_records = list(
            MealAttendance.objects.filter(user__isnull=True, session_key=session_key)
            .prefetch_related("foods")
        )
        for record in guest_records:
            existing = MealAttendance.objects.filter(user=user, date=record.date, meal=record.meal).first()
            if existing:
                record.foods.all().update(attendance=existing)
                record.delete()
            else:
                record.user = user
                record.session_key = None
                record.save()
            migrated_count += 1

    # Also claim unassigned legacy records if this is the only registered user
    if User.objects.count() == 1:
        unassigned_legacy = list(
            MealAttendance.objects.filter(user__isnull=True, session_key__isnull=True)
            .prefetch_related("foods")
        )
        for record in unassigned_legacy:
            existing = MealAttendance.objects.filter(user=user, date=record.date, meal=record.meal).first()
            if existing:
                record.foods.all().update(attendance=existing)
                record.delete()
            else:
                record.user = user
                record.save()
            migrated_count += 1

    return migrated_count


def _auto_skip_past_unmarked_meals(today, selected_date, owner_filter, owner_defaults):
    yesterday = today - timedelta(days=1)
    first_tracked_date = (
        MealAttendance.objects.filter(**owner_filter, date__lte=yesterday)
        .order_by("date")
        .values_list("date", flat=True)
        .first()
    )
    if not first_tracked_date and selected_date >= today:
        return

    start_date = first_tracked_date or yesterday
    dates_to_fill = set()
    if start_date <= yesterday:
        dates_to_fill.update(
            start_date + timedelta(days=offset)
            for offset in range((yesterday - start_date).days + 1)
        )
    if selected_date < today:
        dates_to_fill.add(selected_date)

    if not dates_to_fill:
        return

    existing = set(
        MealAttendance.objects.filter(**owner_filter, date__in=dates_to_fill)
        .values_list("date", "meal")
    )
    MealAttendance.objects.bulk_create(
        [
            MealAttendance(**owner_defaults, date=day, meal=meal, status=MealAttendance.Status.SKIPPED)
            for day in dates_to_fill
            for meal in MealAttendance.Meal.values
            if (day, meal) not in existing
        ],
        ignore_conflicts=True,
    )


@require_http_methods(["GET", "POST"])
def signup_view(request):
    if request.user.is_authenticated:
        return redirect("attendance:dashboard")
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            saved_count = _claim_guest_records(request, user)
            auth_login(request, user)
            if saved_count > 0:
                messages.success(request, f"Welcome to MessMate, {user.username}! Your account has been created and your {saved_count} meal records have been saved.")
            else:
                messages.success(request, f"Welcome to MessMate, {user.username}! Your account has been created.")
            return redirect("attendance:dashboard")
    else:
        form = SignUpForm()
    return render(request, "attendance/signup.html", {"form": form})


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("attendance:dashboard")
    if request.method == "POST":
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            saved_count = _claim_guest_records(request, user)
            auth_login(request, user)
            if saved_count > 0:
                messages.success(request, f"Welcome back, {user.username}! Your {saved_count} guest meal records have been saved to your account.")
            else:
                messages.success(request, f"Welcome back, {user.username}!")
            next_url = request.POST.get("next") or request.GET.get("next") or "/"
            return redirect(next_url)
    else:
        form = LoginForm(request)
    return render(request, "attendance/login.html", {
        "form": form,
        "next": request.GET.get("next", ""),
    })


@require_POST
def logout_view(request):
    auth_logout(request)
    messages.success(request, "You have been logged out. You can continue using MessMate in guest mode.")
    return redirect("attendance:dashboard")


def dashboard(request):
    selected_date = timezone.localdate()
    raw_date = request.GET.get("date")
    if raw_date:
        try:
            selected_date = date.fromisoformat(raw_date)
        except ValueError:
            messages.error(request, "Choose a valid date.")

    owner_filter = _get_owner_filter(request)
    owner_defaults = _get_owner_defaults(request)
    _auto_skip_past_unmarked_meals(timezone.localdate(), selected_date, owner_filter, owner_defaults)

    records = {
        record.meal: record
        for record in MealAttendance.objects.filter(**owner_filter, date=selected_date).prefetch_related("foods")
    }
    week_start = selected_date - timedelta(days=selected_date.weekday())
    today = timezone.localdate()
    week_dates = [week_start + timedelta(days=i) for i in range(7)]
    week_attendance = MealAttendance.objects.filter(**owner_filter, date__in=week_dates)
    attendance_by_day = {}
    for att in week_attendance:
        attendance_by_day.setdefault(att.date, {})[att.meal] = att.status

    week_days = []
    for day_date in week_dates:
        day_meals = attendance_by_day.get(day_date, {})
        dots = []
        for meal_choice in MealAttendance.Meal.values:
            status = day_meals.get(meal_choice)
            if status == MealAttendance.Status.EATEN:
                dots.append("eaten")
            elif status == MealAttendance.Status.SKIPPED:
                dots.append("skipped")
            else:
                dots.append("unmarked")

        week_days.append({
            "date": day_date,
            "iso": day_date.isoformat(),
            "day_number": day_date.day,
            "weekday_short": day_date.strftime("%a")[:3].upper(),
            "weekday_initial": day_date.strftime("%a")[0],
            "is_today": day_date == today,
            "is_selected": day_date == selected_date,
            "dots": dots,
            "eaten_count": sum(1 for d in dots if d == "eaten"),
        })

    menu = WeeklyMenu.objects.filter(week_start=week_start).first()
    menu_entries = {
        (entry.day_of_week, entry.meal): entry.dishes
        for entry in menu.entries.all()
    } if menu else {}
    meals = []
    for meal in MealAttendance.Meal:
        record = records.get(meal.value)
        food_items = list(record.foods.all()) if record else []
        food_totals = {
            field: sum((getattr(food, field) for food in food_items), Decimal("0"))
            for field in MACRO_FIELDS
        }
        meals.append({
            "key": meal.value,
            "label": meal.label,
            "status": record.status if record else None,
            "attendance_id": record.pk if record else None,
            "food_count": len(food_items) if record else 0,
            "saved_food_count": len(food_items),
            "food_totals": food_totals,
            "planned_dishes": menu_entries.get((selected_date.weekday(), meal.value), ""),
        })

    eaten_count = sum(item["status"] == MealAttendance.Status.EATEN for item in meals)
    skipped_count = sum(item["status"] == MealAttendance.Status.SKIPPED for item in meals)
    marked_count = eaten_count + skipped_count
    attendance_pks = MealAttendance.objects.filter(**owner_filter, date=selected_date).values_list("pk", flat=True)
    tracked_foods = MealFood.objects.filter(
        attendance_id__in=attendance_pks,
        attendance__status__in=MealAttendance.Status.values,
    )
    return render(request, "attendance/dashboard.html", {
        "today": today,
        "is_today_selected": selected_date == today,
        "selected_date": selected_date,
        "previous_date": selected_date - timedelta(days=1),
        "next_date": selected_date + timedelta(days=1),
        "previous_week_date": selected_date - timedelta(days=7),
        "next_week_date": selected_date + timedelta(days=7),
        "week_days": week_days,
        "meals": meals,
        "eaten_count": eaten_count,
        "skipped_count": skipped_count,
        "unmarked_count": len(meals) - marked_count,
        "progress_width": eaten_count * 25,
        "attendance_percent": round(eaten_count / marked_count * 100) if marked_count else None,
        "macro_totals": _macro_totals(tracked_foods),
        "food_count": tracked_foods.count(),
        "menu_week_start": week_start,
        "has_weekly_menu": bool(menu and (menu.photo or menu.entries.exists())),
        "is_guest": not request.user.is_authenticated,
    })


@require_POST
def update_attendance(request):
    raw_date = request.POST.get("date", "")
    meal = request.POST.get("meal", "")
    status = request.POST.get("status", "")
    try:
        selected_date = date.fromisoformat(raw_date)
    except ValueError:
        messages.error(request, "Choose a valid date.")
        return redirect("attendance:dashboard")

    if meal not in MealAttendance.Meal.values:
        messages.error(request, "Choose a valid meal.")
    elif status == "UNMARKED":
        owner_filter = _get_owner_filter(request)
        MealAttendance.objects.filter(**owner_filter, date=selected_date, meal=meal).delete()
        messages.success(request, "Meal set to Not Marked.")
    elif status in MealAttendance.Status.values:
        owner_filter = _get_owner_filter(request)
        owner_defaults = _get_owner_defaults(request)
        record = MealAttendance.objects.filter(**owner_filter, date=selected_date, meal=meal).first()
        if record:
            record.status = status
            record.save()
        else:
            MealAttendance.objects.create(
                **owner_defaults,
                date=selected_date,
                meal=meal,
                status=status,
            )
        messages.success(request, "Attendance saved.")
    else:
        messages.error(request, "Choose Eaten, Skipped, or Not Marked.")
    return redirect(f"/?date={selected_date.isoformat()}")


@require_http_methods(["GET", "POST"])
def meal_foods(request, attendance_id):
    owner_filter = _get_owner_filter(request)
    attendance = get_object_or_404(
        MealAttendance.objects.prefetch_related("foods"), pk=attendance_id, **owner_filter
    )
    if request.method == "POST":
        if attendance.status not in MealAttendance.Status.values:
            messages.error(request, "Food details can only be added after marking the meal.")
            return redirect("attendance:dashboard")
        form = MealFoodForm(request.POST)
        if form.is_valid():
            food = form.save(commit=False)
            food.attendance = attendance
            if not food.calories or food.calories == Decimal("0"):
                try:
                    calc = calculate_macros(food.name, food.serving)
                    food.calories = Decimal(calc["macros"]["calories"])
                    food.protein_g = Decimal(calc["macros"]["protein_g"])
                    food.carbs_g = Decimal(calc["macros"]["carbs_g"])
                    food.fat_g = Decimal(calc["macros"]["fat_g"])
                    if not food.serving:
                        food.serving = calc.get("serving", "")
                except Exception:
                    pass
            food.save()
            messages.success(request, f"{food.name} added to {attendance.get_meal_display()}.")
            return redirect("attendance:meal_foods", attendance_id=attendance.pk)
    else:
        form = MealFoodForm(initial={"name": request.GET.get("name", "")})

    food_items = list(attendance.foods.all())
    can_add_food = attendance.status in MealAttendance.Status.values
    empty_totals = {field: Decimal("0") for field in MACRO_FIELDS}
    week_start = attendance.date - timedelta(days=attendance.date.weekday())
    menu_entry = WeeklyMenuEntry.objects.filter(
        menu__week_start=week_start,
        day_of_week=attendance.date.weekday(),
        meal=attendance.meal,
    ).first()
    return render(request, "attendance/food_details.html", {
        "attendance": attendance,
        "food_items": food_items,
        "food_totals": _macro_totals(attendance.foods.all()) if can_add_food else empty_totals,
        "form": form,
        "can_add_food": can_add_food,
        "return_date": attendance.date.isoformat(),
        "planned_foods": [dish.strip() for dish in menu_entry.dishes.split(",") if dish.strip()] if menu_entry else [],
    })


@require_POST
def delete_food(request, food_id):
    owner_filter = _get_owner_filter(request)
    filter_kwargs = {"attendance__" + k: v for k, v in owner_filter.items()}
    food = get_object_or_404(MealFood.objects.select_related("attendance"), pk=food_id, **filter_kwargs)
    attendance_id = food.attendance_id
    food.delete()
    messages.success(request, "Food detail removed.")
    return redirect("attendance:meal_foods", attendance_id=attendance_id)


@require_GET
def nutrition_lookup(request):
    try:
        result = calculate_macros(request.GET.get("food", ""), request.GET.get("portion", ""))
    except NutritionLookupError as error:
        return JsonResponse({"ok": False, "error": str(error)}, status=400)
    return JsonResponse({"ok": True, **result})


@require_POST
def analyze_photo(request):
    upload = request.FILES.get("photo")
    if not upload:
        return JsonResponse({"ok": False, "error": "Please choose or take a food photo first."}, status=400)
    try:
        result = analyze_food_photo(upload)
    except NutritionLookupError as error:
        return JsonResponse({"ok": False, "error": str(error)}, status=400)
    return JsonResponse({"ok": True, **result})


@require_POST
def add_bulk_foods(request, attendance_id):
    owner_filter = _get_owner_filter(request)
    attendance = get_object_or_404(MealAttendance, pk=attendance_id, **owner_filter)
    try:
        payload = json.loads(request.body.decode("utf-8"))
        items = payload.get("foods", [])
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Invalid JSON format."}, status=400)

    if not items:
        return JsonResponse({"ok": False, "error": "No food items provided."}, status=400)

    created_foods = []
    for item in items:
        name = str(item.get("name", "")).strip()[:100]
        if not name:
            continue
        serving = str(item.get("serving", "")).strip()[:60]
        try:
            calories = Decimal(str(item.get("calories", 0)))
            protein_g = Decimal(str(item.get("protein_g", 0)))
            carbs_g = Decimal(str(item.get("carbs_g", 0)))
            fat_g = Decimal(str(item.get("fat_g", 0)))
        except (Exception):
            calories = Decimal("0")
            protein_g = Decimal("0")
            carbs_g = Decimal("0")
            fat_g = Decimal("0")

        food = MealFood(
            attendance=attendance,
            name=name,
            serving=serving,
            calories=max(Decimal("0"), calories),
            protein_g=max(Decimal("0"), protein_g),
            carbs_g=max(Decimal("0"), carbs_g),
            fat_g=max(Decimal("0"), fat_g),
        )
        created_foods.append(food)

    if created_foods:
        MealFood.objects.bulk_create(created_foods)
        messages.success(request, f"Added {len(created_foods)} food items from your meal photo.")

    return JsonResponse({
        "ok": True,
        "added_count": len(created_foods),
        "redirect_url": reverse("attendance:meal_foods", args=[attendance.pk]),
    })


def _requested_week(raw_week):
    try:
        requested = date.fromisoformat(raw_week) if raw_week else timezone.localdate()
    except ValueError:
        requested = timezone.localdate()
    return requested - timedelta(days=requested.weekday())


@require_http_methods(["GET", "POST"])
def weekly_menu(request):
    raw_week = request.POST.get("week_start") or request.GET.get("week")
    week_start = _requested_week(raw_week)
    menu, _ = WeeklyMenu.objects.get_or_create(week_start=week_start)
    weekdays = list(WeeklyMenuEntry.Day.choices)
    meals = list(MealAttendance.Meal.choices)
    entries = {
        (entry.day_of_week, entry.meal): entry.dishes
        for entry in menu.entries.all()
    }
    photo_form = WeeklyMenuPhotoForm(instance=menu)

    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action == "analyze":
            photo_form = WeeklyMenuPhotoForm(request.POST, request.FILES, instance=menu)
            if photo_form.is_valid():
                upload = request.FILES.get("photo")
                if upload:
                    photo_form.save()
                    upload = menu.photo
                elif menu.photo:
                    upload = menu.photo
                if not upload:
                    messages.error(request, "Choose a menu photo to analyze.")
                else:
                    try:
                        extracted = analyze_menu_photo(upload)
                    except MenuAnalysisError as error:
                        messages.error(request, str(error))
                    else:
                        for (day_index, meal), dishes in extracted.items():
                            if dishes:
                                WeeklyMenuEntry.objects.update_or_create(
                                    menu=menu, day_of_week=day_index, meal=meal,
                                    defaults={"dishes": dishes},
                                )
                            else:
                                WeeklyMenuEntry.objects.filter(
                                    menu=menu, day_of_week=day_index, meal=meal
                                ).delete()
                        messages.success(request, "Menu extracted. Review and edit each meal before saving.")
                        return redirect(f"{request.path}?week={week_start.isoformat()}")
            else:
                messages.error(request, "Choose a valid menu image.")
        else:
            menu, _ = WeeklyMenu.objects.get_or_create(week_start=week_start)
            for day_index, _day_label in weekdays:
                for meal, _meal_label in meals:
                    field_name = f"entry-{day_index}-{meal}"
                    dishes = request.POST.get(field_name, "").strip()[:600]
                    entry_filter = {
                        "menu": menu, "day_of_week": day_index, "meal": meal,
                    }
                    if dishes:
                        WeeklyMenuEntry.objects.update_or_create(
                            **entry_filter, defaults={"dishes": dishes}
                        )
                    else:
                        WeeklyMenuEntry.objects.filter(**entry_filter).delete()
            messages.success(request, "Weekly menu saved.")
            return redirect(f"{request.path}?week={week_start.isoformat()}")

    entries = {
        (entry.day_of_week, entry.meal): entry.dishes
        for entry in menu.entries.all()
    }
    menu_days = [
        {"index": day_index, "label": day_label, "meals": [
            {"key": meal, "label": meal_label,
             "dishes": entries.get((day_index, meal), "")}
            for meal, meal_label in meals
        ]}
        for day_index, day_label in weekdays
    ]
    return render(request, "attendance/weekly_menu.html", {
        "menu": menu,
        "week_start": week_start,
        "week_end": week_start + timedelta(days=6),
        "weekdays": weekdays,
        "meals": meals,
        "menu_days": menu_days,
        "photo_form": photo_form,
        "has_openai_key": bool(os.environ.get("OPENAI_API_KEY")),
    })
