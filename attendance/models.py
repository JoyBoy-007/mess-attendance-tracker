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
