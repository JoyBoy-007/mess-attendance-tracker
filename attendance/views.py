from datetime import date

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import MealAttendance


def dashboard(request):
    selected_date = timezone.localdate()
    raw_date = request.GET.get("date")
    if raw_date:
        try:
            selected_date = date.fromisoformat(raw_date)
        except ValueError:
            messages.error(request, "Choose a valid date.")

    records = {
        record.meal: record.status
        for record in MealAttendance.objects.filter(date=selected_date)
    }
    meals = [
        {"key": meal.value, "label": meal.label, "status": records.get(meal.value)}
        for meal in MealAttendance.Meal
    ]
    eaten_count = sum(item["status"] == MealAttendance.Status.EATEN for item in meals)
    skipped_count = sum(item["status"] == MealAttendance.Status.SKIPPED for item in meals)
    marked_count = eaten_count + skipped_count
    return render(request, "attendance/dashboard.html", {
        "selected_date": selected_date,
        "meals": meals,
        "eaten_count": eaten_count,
        "skipped_count": skipped_count,
        "unmarked_count": len(meals) - marked_count,
        "progress_width": eaten_count * 25,
        "attendance_percent": round(eaten_count / marked_count * 100) if marked_count else None,
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
