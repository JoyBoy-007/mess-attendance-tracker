from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
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

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="meal_attendances",
    )
    session_key = models.CharField(max_length=40, blank=True, null=True, db_index=True)
    date = models.DateField()
    meal = models.CharField(max_length=12, choices=Meal.choices)
    status = models.CharField(max_length=8, choices=Status.choices)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "meal"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "date", "meal"],
                condition=models.Q(user__isnull=False),
                name="unique_user_meal_attendance_per_day",
            ),
            models.UniqueConstraint(
                fields=["session_key", "date", "meal"],
                condition=models.Q(user__isnull=True, session_key__isnull=False),
                name="unique_guest_meal_attendance_per_day",
            ),
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


def validate_menu_image(upload):
    allowed_types = {
        ".jpg": (b"\xff\xd8\xff",),
        ".jpeg": (b"\xff\xd8\xff",),
        ".png": (b"\x89PNG\r\n\x1a\n",),
        ".webp": (b"RIFF",),
    }
    suffix = Path(upload.name).suffix.lower()
    if suffix not in allowed_types:
        raise ValidationError("Upload a JPG, PNG, or WebP image.")
    if upload.size > 10 * 1024 * 1024:
        raise ValidationError("Choose an image smaller than 10 MB.")
    header = upload.read(12)
    upload.seek(0)
    if not any(header.startswith(signature) for signature in allowed_types[suffix]):
        raise ValidationError("The file contents do not match a supported image type.")
    if suffix == ".webp" and header[8:12] != b"WEBP":
        raise ValidationError("The file contents do not match a supported image type.")


class WeeklyMenu(models.Model):
    week_start = models.DateField(unique=True, help_text="Monday of this menu week")
    photo = models.FileField(upload_to="menus/%Y/%m/", validators=[validate_menu_image], blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-week_start"]

    def __str__(self):
        return f"Menu for week of {self.week_start}"


class WeeklyMenuEntry(models.Model):
    class Day(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    menu = models.ForeignKey(WeeklyMenu, related_name="entries", on_delete=models.CASCADE)
    day_of_week = models.PositiveSmallIntegerField(choices=Day.choices)
    meal = models.CharField(max_length=12, choices=MealAttendance.Meal.choices)
    dishes = models.CharField(max_length=600, blank=True)

    class Meta:
        ordering = ["day_of_week", "meal"]
        constraints = [
            models.UniqueConstraint(
                fields=["menu", "day_of_week", "meal"],
                name="unique_weekly_menu_day_meal",
            )
        ]

    def __str__(self):
        return f"{self.get_day_of_week_display()} {self.get_meal_display()}: {self.dishes}"


class NutritionFood(models.Model):
    """Local nutrition reference values; macros are stored per 100 grams."""

    name = models.CharField(max_length=100, unique=True)
    aliases = models.CharField(max_length=300, blank=True)
    calories = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    protein_g = models.DecimalField("protein (g)", max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    carbs_g = models.DecimalField("carbohydrates (g)", max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    fat_g = models.DecimalField("fat (g)", max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    serving_unit = models.CharField(max_length=24, default="serving")
    serving_grams = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal("100"), validators=[MinValueValidator(Decimal("0.01"))])

    class Meta:
        ordering = ["name"]
        verbose_name = "local nutrition food"
        verbose_name_plural = "local nutrition foods"

    def __str__(self):
        return self.name
