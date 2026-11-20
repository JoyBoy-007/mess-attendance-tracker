from django.contrib import admin

from .models import MealAttendance, MealFood, NutritionFood, WeeklyMenu, WeeklyMenuEntry


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


class WeeklyMenuEntryInline(admin.TabularInline):
    model = WeeklyMenuEntry
    extra = 0


@admin.register(WeeklyMenu)
class WeeklyMenuAdmin(admin.ModelAdmin):
    list_display = ("week_start", "updated_at")
    ordering = ("-week_start",)
    inlines = (WeeklyMenuEntryInline,)


@admin.register(NutritionFood)
class NutritionFoodAdmin(admin.ModelAdmin):
    list_display = ("name", "calories", "protein_g", "carbs_g", "fat_g", "serving_unit", "serving_grams")
    search_fields = ("name", "aliases")
    ordering = ("name",)
