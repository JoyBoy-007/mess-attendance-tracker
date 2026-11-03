from django.contrib import admin
from .models import MealAttendance


@admin.register(MealAttendance)
class MealAttendanceAdmin(admin.ModelAdmin):
    list_display = ("date", "meal", "status", "updated_at")
    list_filter = ("date", "meal", "status")
    date_hierarchy = "date"
    ordering = ("-date", "meal")
