from datetime import date
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from .models import MealAttendance


class AttendanceDashboardTests(TestCase):
    def test_unmarked_meals_are_shown_by_default(self):
        response = self.client.get(reverse("attendance:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["unmarked_count"], 4)
        self.assertContains(response, "Not Marked")

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
