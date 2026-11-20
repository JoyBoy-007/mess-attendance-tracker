from datetime import date
from decimal import Decimal
import json
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from .local_nutrition import NutritionLookupError, calculate_macros, analyze_food_photo
from .models import MealAttendance, MealFood, NutritionFood

User = get_user_model()


class AttendanceDashboardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password123")
        self.client.force_login(self.user)

    def test_unmarked_meals_are_shown_by_default(self):
        response = self.client.get(reverse("attendance:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["unmarked_count"], 4)
        self.assertEqual(len(response.context["week_days"]), 7)
        self.assertContains(response, "Not Marked")
        self.assertContains(response, "Daily macros")
        self.assertContains(response, "gcal-widget")
        self.assertContains(response, "Today")

    def test_mark_and_change_status_keeps_one_record_per_date_and_meal(self):
        url = reverse("attendance:update")
        data = {"date": "2026-11-03", "meal": "BREAKFAST", "status": "EATEN"}
        self.client.post(url, data)
        self.client.post(url, {**data, "status": "SKIPPED"})
        self.assertEqual(MealAttendance.objects.filter(user=self.user).count(), 1)
        self.assertEqual(MealAttendance.objects.get(user=self.user).status, "SKIPPED")

    def test_database_rejects_duplicate_date_and_meal(self):
        MealAttendance.objects.create(
            user=self.user, date=date(2026, 11, 3), meal="BREAKFAST", status="EATEN"
        )
        with self.assertRaises(IntegrityError):
            MealAttendance.objects.create(
                user=self.user, date=date(2026, 11, 3), meal="BREAKFAST", status="SKIPPED"
            )

    def test_can_clear_a_meal_to_unmarked(self):
        MealAttendance.objects.create(user=self.user, date="2026-11-03", meal="LUNCH", status="EATEN")
        self.client.post(reverse("attendance:update"), {
            "date": "2026-11-03", "meal": "LUNCH", "status": "UNMARKED"
        })
        self.assertFalse(MealAttendance.objects.filter(user=self.user).exists())


class MealFoodTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password123")
        self.client.force_login(self.user)
        self.attendance = MealAttendance.objects.create(
            user=self.user, date=date(2026, 11, 10), meal="LUNCH", status="EATEN"
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

    def test_food_added_without_macros_auto_calculates(self):
        response = self.client.post(self.url, {
            "name": "Roti",
            "serving": "2 roti",
            "calories": "0",
            "protein_g": "0",
            "carbs_g": "0",
            "fat_g": "0",
        })
        self.assertEqual(response.status_code, 302)
        food = MealFood.objects.get(name="Roti")
        self.assertGreater(food.calories, Decimal("0"))
        self.assertGreater(food.protein_g, Decimal("0"))

    def test_clearing_attendance_removes_its_food_details(self):
        MealFood.objects.create(attendance=self.attendance, name="Dal")
        self.client.post(reverse("attendance:update"), {
            "date": "2026-11-10", "meal": "LUNCH", "status": "UNMARKED"
        })
        self.assertFalse(MealAttendance.objects.filter(user=self.user).exists())
        self.assertFalse(MealFood.objects.exists())


class NutritionLookupTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_local_food_lookup_scales_macros(self):
        result = calculate_macros("Roti", "2 roti")
        self.assertEqual(result["food"], "Roti")
        self.assertEqual(result["source"], "local food list")
        self.assertEqual(result["macros"]["calories"], "237.6")
        self.assertEqual(result["macros"]["protein_g"], "7.8")

    def test_missing_food_raises_error(self):
        with self.assertRaises(NutritionLookupError):
            calculate_macros("", "")

    def test_gemini_lookup_missing_api_key_raises_error(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            with self.assertRaises(NutritionLookupError) as ctx:
                calculate_macros("Paneer Butter Masala", "1 bowl")
            self.assertIn("GEMINI_API_KEY", str(ctx.exception))

    @patch("attendance.local_nutrition.urlopen")
    def test_gemini_lookup_success(self, mock_urlopen):
        mock_response = MagicMock()
        gemini_data = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps({
                                    "food": "Paneer Butter Masala",
                                    "portion": "1 bowl (approx 200 g)",
                                    "serving_grams": 200,
                                    "calories": 350.0,
                                    "protein_g": 12.0,
                                    "carbs_g": 15.0,
                                    "fat_g": 26.0,
                                })
                            }
                        ]
                    }
                }
            ]
        }
        mock_response.read.return_value = json.dumps(gemini_data).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            result = calculate_macros("Paneer Butter Masala", "1 bowl")
            self.assertEqual(result["food"], "Paneer Butter Masala")
            self.assertEqual(result["source"], "Gemini AI")
            self.assertEqual(result["macros"]["calories"], "350.0")
            self.assertEqual(result["macros"]["protein_g"], "12.0")
            self.assertEqual(result["macros"]["carbs_g"], "15.0")
            self.assertEqual(result["macros"]["fat_g"], "26.0")

    def test_views_nutrition_lookup_endpoint(self):
        response = self.client.get(reverse("attendance:nutrition_lookup"), {"food": "Roti", "portion": "1 roti"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["food"], "Roti")
        self.assertEqual(data["source"], "local food list")


class PhotoNutritionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="photouser", password="password123")
        self.client.force_login(self.user)
        self.attendance = MealAttendance.objects.create(
            user=self.user, date=date(2026, 11, 19), meal="LUNCH", status="EATEN"
        )

    @patch("attendance.local_nutrition.urlopen")
    def test_analyze_food_photo_success(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps({
                                    "summary": "Indian thali with roti and dal",
                                    "total_calories": 370,
                                    "foods": [
                                        {"name": "Roti", "serving": "2 pieces (approx 70 g)", "calories": 210.0, "protein_g": 6.8, "carbs_g": 38.0, "fat_g": 3.2},
                                        {"name": "Dal Tadka", "serving": "1 bowl (approx 150 g)", "calories": 160.0, "protein_g": 7.5, "carbs_g": 22.0, "fat_g": 4.5},
                                    ],
                                })
                            }
                        ]
                    }
                }
            ]
        }).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        dummy_img = SimpleUploadedFile("meal.jpg", b"\xff\xd8\xff\xe0test_image_bytes", content_type="image/jpeg")
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            result = analyze_food_photo(dummy_img)
            self.assertEqual(len(result["foods"]), 2)
            self.assertEqual(result["foods"][0]["name"], "Roti")
            self.assertEqual(result["foods"][1]["name"], "Dal Tadka")
            self.assertEqual(result["total_calories"], "370.0")

    def test_bulk_add_foods_endpoint(self):
        url = reverse("attendance:add_bulk_foods", args=[self.attendance.pk])
        payload = {
            "foods": [
                {"name": "Roti", "serving": "2 pieces", "calories": "210", "protein_g": "6.8", "carbs_g": "38", "fat_g": "3.2"},
                {"name": "Dal", "serving": "1 bowl", "calories": "160", "protein_g": "7.5", "carbs_g": "22", "fat_g": "4.5"},
            ]
        }
        response = self.client.post(url, json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["added_count"], 2)
        self.assertEqual(self.attendance.foods.count(), 2)


class AuthTests(TestCase):
    def test_anonymous_user_can_access_dashboard_directly_without_login(self):
        response = self.client.get(reverse("attendance:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_guest"])
        self.assertContains(response, "Guest Mode")
        self.assertContains(response, "Save Data")
        self.assertContains(response, "Log in")

    def test_guest_can_mark_attendance_and_add_food(self):
        # Initial visit creates session
        self.client.get(reverse("attendance:dashboard"))
        session_key = self.client.session.session_key
        self.assertTrue(bool(session_key))

        # Mark lunch
        res = self.client.post(reverse("attendance:update"), {
            "date": "2026-11-20", "meal": "LUNCH", "status": "EATEN"
        })
        self.assertEqual(res.status_code, 302)
        att = MealAttendance.objects.get(session_key=session_key, user__isnull=True, date="2026-11-20", meal="LUNCH")
        self.assertEqual(att.status, "EATEN")

        # Add food to attendance
        food_res = self.client.post(reverse("attendance:meal_foods", args=[att.pk]), {
            "name": "Dal",
            "serving": "1 bowl",
            "calories": "180",
            "protein_g": "10",
            "carbs_g": "24",
            "fat_g": "4",
        })
        self.assertEqual(food_res.status_code, 302)
        self.assertEqual(att.foods.count(), 1)

        # Dashboard shows guest data
        dash = self.client.get(reverse("attendance:dashboard"), {"date": "2026-11-20"})
        self.assertEqual(dash.context["macro_totals"]["calories"], Decimal("180"))
        self.assertEqual(dash.context["eaten_count"], 1)

    def test_guest_data_migrated_on_signup(self):
        # Guest marks meal and adds food
        self.client.get(reverse("attendance:dashboard"))
        session_key = self.client.session.session_key
        att = MealAttendance.objects.create(
            session_key=session_key, user=None, date=date(2026, 11, 20), meal="LUNCH", status="EATEN"
        )
        MealFood.objects.create(
            attendance=att, name="Rice", calories=220, protein_g=4, carbs_g=45, fat_g=1
        )

        signup_url = reverse("attendance:signup")
        post_data = {
            "username": "newstudent",
            "email": "student@hostel.edu",
            "password1": "ValidPassword123!",
            "password2": "ValidPassword123!",
        }
        res = self.client.post(signup_url, post_data)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, reverse("attendance:dashboard"))

        # User is created and now owns the attendance and food
        user = User.objects.get(username="newstudent")
        att.refresh_from_db()
        self.assertEqual(att.user, user)
        self.assertIsNone(att.session_key)
        self.assertEqual(att.foods.count(), 1)

    def test_guest_data_migrated_on_login(self):
        user = User.objects.create_user(username="existinguser", password="secretpassword123")

        # Guest marks dinner
        self.client.get(reverse("attendance:dashboard"))
        session_key = self.client.session.session_key
        att = MealAttendance.objects.create(
            session_key=session_key, user=None, date=date(2026, 11, 20), meal="DINNER", status="EATEN"
        )

        # Login
        login_res = self.client.post(reverse("attendance:login"), {
            "username": "existinguser",
            "password": "secretpassword123",
        })
        self.assertEqual(login_res.status_code, 302)

        att.refresh_from_db()
        self.assertEqual(att.user, user)

    def test_logout_redirects_to_dashboard_in_guest_mode(self):
        user = User.objects.create_user(username="testuser_logout", password="secretpassword123")
        self.client.force_login(user)

        logout_res = self.client.post(reverse("attendance:logout"), follow=True)
        self.assertEqual(logout_res.status_code, 200)
        self.assertTrue(logout_res.context["is_guest"])
        self.assertContains(logout_res, "Guest Mode")

    def test_user_data_isolation(self):
        user_a = User.objects.create_user(username="usera", password="passwordA123")
        user_b = User.objects.create_user(username="userb", password="passwordB123")

        # User A logs in and records attendance + food
        self.client.force_login(user_a)
        att_a = MealAttendance.objects.create(
            user=user_a, date=date(2026, 11, 20), meal="LUNCH", status="EATEN"
        )
        MealFood.objects.create(
            attendance=att_a, name="Paneer", calories=300, protein_g=15, carbs_g=10, fat_g=20
        )

        dash_a = self.client.get(reverse("attendance:dashboard"), {"date": "2026-11-20"})
        self.assertEqual(dash_a.context["macro_totals"]["calories"], Decimal("300"))

        # User B logs in
        self.client.force_login(user_b)
        dash_b = self.client.get(reverse("attendance:dashboard"), {"date": "2026-11-20"})
        # User B has no records for that day yet
        self.assertEqual(dash_b.context["macro_totals"]["calories"], Decimal("0"))
        self.assertEqual(dash_b.context["food_count"], 0)

        # User B creates attendance for the same day and meal without collision
        att_b = MealAttendance.objects.create(
            user=user_b, date=date(2026, 11, 20), meal="LUNCH", status="SKIPPED"
        )
        self.assertEqual(att_b.status, "SKIPPED")
        self.assertEqual(att_a.status, "EATEN")

        # User B cannot access User A's meal foods detail (404)
        detail_res = self.client.get(reverse("attendance:meal_foods", args=[att_a.pk]))
        self.assertEqual(detail_res.status_code, 404)

        # User B cannot delete User A's food (404)
        food_a = att_a.foods.first()
        del_res = self.client.post(reverse("attendance:delete_food", args=[food_a.pk]))
        self.assertEqual(del_res.status_code, 404)
        self.assertTrue(MealFood.objects.filter(pk=food_a.pk).exists())



