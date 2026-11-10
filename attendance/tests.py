from datetime import date
from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from .models import MealAttendance, MealFood


class AttendanceDashboardTests(TestCase):
    def test_unmarked_meals_are_shown_by_default(self):
        response = self.client.get(reverse("attendance:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["unmarked_count"], 4)
        self.assertContains(response, "Not Marked")
        self.assertContains(response, "Daily macros")

    def test_mark_and_change_status_keeps_one_record_per_date_and_meal(self):
        url = reverse("attendance:update")
        data = {"date": "2026-11-03", "meal": "BREAKFAST", "status": "EATEN"}
        self.client.post(url, data)
        self.client.post(url, {**data, "status": "SKIPPED"})
        self.assertEqual(MealAttendance.objects.count(), 1)
        self.assertEqual(MealAttendance.objects.get().status, "SKIPPED")

    def test_database_rejects_duplicate_date_and_meal(self):
        MealAttendance.objects.create(
            date=date(2026, 11, 3), meal="BREAKFAST", status="EATEN"
        )
        with self.assertRaises(IntegrityError):
            MealAttendance.objects.create(
                date=date(2026, 11, 3), meal="BREAKFAST", status="SKIPPED"
            )

    def test_can_clear_a_meal_to_unmarked(self):
        MealAttendance.objects.create(date="2026-11-03", meal="LUNCH", status="EATEN")
        self.client.post(reverse("attendance:update"), {
            "date": "2026-11-03", "meal": "LUNCH", "status": "UNMARKED"
        })
        self.assertFalse(MealAttendance.objects.exists())


class MealFoodTests(TestCase):
    def setUp(self):
        self.attendance = MealAttendance.objects.create(
            date=date(2026, 11, 10), meal="LUNCH", status="EATEN"
        )
        self.url = reverse("attendance:meal_foods", args=[self.attendance.pk])

    def food_data(self, **overrides):
        return {
            "name": "Dal",
            "serving": "1 bowl",
            "calories": "180",
            "protein_g": "10",
            "carbs_g": "24",
            "fat_g": "4",
            **overrides,
        }

    def test_food_can_be_added_and_dashboard_totals_macros(self):
        response = self.client.post(self.url, self.food_data())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(MealFood.objects.count(), 1)
        dashboard = self.client.get(reverse("attendance:dashboard"), {"date": "2026-11-10"})
        self.assertEqual(dashboard.context["food_count"], 1)
        self.assertEqual(dashboard.context["macro_totals"]["calories"], Decimal("180"))
        self.assertEqual(dashboard.context["macro_totals"]["protein_g"], Decimal("10"))
        self.assertContains(dashboard, "Manage")

    def test_skipped_meal_can_record_food_and_count_its_macros(self):
        MealFood.objects.create(
            attendance=self.attendance, name="Dal", calories=180,
            protein_g=10, carbs_g=24, fat_g=4,
        )
        self.attendance.status = MealAttendance.Status.SKIPPED
        self.attendance.save()
        response = self.client.post(self.url, self.food_data(name="Rice", calories="220"))
        self.assertEqual(response.status_code, 302)
        dashboard = self.client.get(reverse("attendance:dashboard"), {"date": "2026-11-10"})
        self.assertEqual(dashboard.context["food_count"], 2)
        self.assertEqual(dashboard.context["macro_totals"]["calories"], Decimal("400"))
        self.assertEqual(MealFood.objects.count(), 2)
        detail = self.client.get(self.url)
        self.assertEqual(detail.context["food_totals"]["calories"], Decimal("400"))
        self.assertContains(detail, "This meal was skipped at the mess")
        self.assertContains(detail, "Dal")

    def test_food_can_be_removed(self):
        food = MealFood.objects.create(attendance=self.attendance, name="Dal")
        response = self.client.post(reverse("attendance:delete_food", args=[food.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(MealFood.objects.exists())

    def test_clearing_attendance_removes_its_food_details(self):
        MealFood.objects.create(attendance=self.attendance, name="Dal")
        self.client.post(reverse("attendance:update"), {
            "date": "2026-11-10", "meal": "LUNCH", "status": "UNMARKED"
        })
        self.assertFalse(MealAttendance.objects.exists())
        self.assertFalse(MealFood.objects.exists())
