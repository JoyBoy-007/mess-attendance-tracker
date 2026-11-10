from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class MealAttendance(models.Model):
    class Meal(models.TextChoices):
        BREAKFAST = "BREAKFAST", "Breakfast"
        LUNCH = "LUNCH", "Lunch"
        SNACKS = "SNACKS", "Snacks"
        DINNER = "DINNER", "Dinner"

    class Status(models.TextChoices):
        EATEN = "EATEN", "Eaten"
        SKIPPED = "SKIPPED", "Skipped"

    date = models.DateField()
    meal = models.CharField(max_length=12, choices=Meal.choices)
    status = models.CharField(max_length=8, choices=Status.choices)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "meal"]
        constraints = [
            models.UniqueConstraint(
                fields=["date", "meal"], name="unique_meal_attendance_per_day"
            )
        ]

    def __str__(self):
        return f"{self.get_meal_display()} — {self.date}: {self.get_status_display()}"


class MealFood(models.Model):
    attendance = models.ForeignKey(
        MealAttendance, related_name="foods", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=100)
    serving = models.CharField(
        max_length=60, blank=True, help_text="For example: 1 cup or 150 g"
    )
    calories = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0"), blank=True,
        validators=[MinValueValidator(0)],
    )
    protein_g = models.DecimalField(
        "protein (g)", max_digits=8, decimal_places=2, default=Decimal("0"), blank=True,
        validators=[MinValueValidator(0)],
    )
    carbs_g = models.DecimalField(
        "carbohydrates (g)", max_digits=8, decimal_places=2, default=Decimal("0"), blank=True,
        validators=[MinValueValidator(0)],
    )
    fat_g = models.DecimalField(
        "fat (g)", max_digits=8, decimal_places=2, default=Decimal("0"), blank=True,
        validators=[MinValueValidator(0)],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name = "food detail"
        verbose_name_plural = "food details"

    def __str__(self):
        return f"{self.name} — {self.attendance.get_meal_display()} on {self.attendance.date}"
