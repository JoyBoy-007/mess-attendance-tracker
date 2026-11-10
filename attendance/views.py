from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods

from .forms import MealFoodForm
from .models import MealAttendance, MealFood


MACRO_FIELDS = ("calories", "protein_g", "carbs_g", "fat_g")


def _macro_totals(queryset):
    totals = queryset.aggregate(**{field: Sum(field) for field in MACRO_FIELDS})
    return {field: totals[field] or Decimal("0") for field in MACRO_FIELDS}


def dashboard(request):
    selected_date = timezone.localdate()
    raw_date = request.GET.get("date")
    if raw_date:
        try:
            selected_date = date.fromisoformat(raw_date)
        except ValueError:
            messages.error(request, "Choose a valid date.")

    records = {
        record.meal: record
        for record in MealAttendance.objects.filter(date=selected_date).prefetch_related("foods")
    }
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
        })

    eaten_count = sum(item["status"] == MealAttendance.Status.EATEN for item in meals)
    skipped_count = sum(item["status"] == MealAttendance.Status.SKIPPED for item in meals)
    marked_count = eaten_count + skipped_count
    tracked_foods = MealFood.objects.filter(
        attendance__date=selected_date,
        attendance__status__in=MealAttendance.Status.values,
    )
    return render(request, "attendance/dashboard.html", {
        "selected_date": selected_date,
        "meals": meals,
        "eaten_count": eaten_count,
        "skipped_count": skipped_count,
        "unmarked_count": len(meals) - marked_count,
        "progress_width": eaten_count * 25,
        "attendance_percent": round(eaten_count / marked_count * 100) if marked_count else None,
        "macro_totals": _macro_totals(tracked_foods),
        "food_count": tracked_foods.count(),
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
        MealAttendance.objects.filter(date=selected_date, meal=meal).delete()
        messages.success(request, "Meal set to Not Marked.")
    elif status in MealAttendance.Status.values:
        MealAttendance.objects.update_or_create(
            date=selected_date, meal=meal, defaults={"status": status}
        )
        messages.success(request, "Attendance saved.")
    else:
        messages.error(request, "Choose Eaten, Skipped, or Not Marked.")
    return redirect(f"/?date={selected_date.isoformat()}")


@require_http_methods(["GET", "POST"])
def meal_foods(request, attendance_id):
    attendance = get_object_or_404(
        MealAttendance.objects.prefetch_related("foods"), pk=attendance_id
    )
    if request.method == "POST":
        if attendance.status not in MealAttendance.Status.values:
            messages.error(request, "Food details can only be added after marking the meal.")
            return redirect("attendance:dashboard")
        form = MealFoodForm(request.POST)
        if form.is_valid():
            food = form.save(commit=False)
            food.attendance = attendance
            food.save()
            messages.success(request, f"{food.name} added to {attendance.get_meal_display()}.")
            return redirect("attendance:meal_foods", attendance_id=attendance.pk)
    else:
        form = MealFoodForm()

    food_items = list(attendance.foods.all())
    can_add_food = attendance.status in MealAttendance.Status.values
    empty_totals = {field: Decimal("0") for field in MACRO_FIELDS}
    return render(request, "attendance/food_details.html", {
        "attendance": attendance,
        "food_items": food_items,
        "food_totals": _macro_totals(attendance.foods.all()) if can_add_food else empty_totals,
        "form": form,
        "can_add_food": can_add_food,
        "return_date": attendance.date.isoformat(),
    })


@require_POST
def delete_food(request, food_id):
    food = get_object_or_404(MealFood.objects.select_related("attendance"), pk=food_id)
    attendance_id = food.attendance_id
    food.delete()
    messages.success(request, "Food detail removed.")
    return redirect("attendance:meal_foods", attendance_id=attendance_id)
