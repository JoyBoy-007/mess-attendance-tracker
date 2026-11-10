from django.contrib import admin

from .models import MealAttendance, MealFood


class MealFoodInline(admin.TabularInline):
    model = MealFood
    extra = 0


@admin.register(MealAttendance)
class MealAttendanceAdmin(admin.ModelAdmin):
    list_display = ("date", "meal", "status", "updated_at")
    list_filter = ("date", "meal", "status")
    date_hierarchy = "date"
    ordering = ("-date", "meal")
    inlines = (MealFoodInline,)


@admin.register(MealFood)
class MealFoodAdmin(admin.ModelAdmin):
    list_display = ("name", "attendance", "serving", "calories", "protein_g", "carbs_g", "fat_g")
    list_filter = ("attendance__date", "attendance__meal")
    search_fields = ("name",)
