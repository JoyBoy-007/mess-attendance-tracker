from django.urls import path
from . import views

app_name = "attendance"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("signup/", views.signup_view, name="signup"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("attendance/update/", views.update_attendance, name="update"),
    path("attendance/<int:attendance_id>/foods/", views.meal_foods, name="meal_foods"),
    path("food/<int:food_id>/delete/", views.delete_food, name="delete_food"),
    path("menu/", views.weekly_menu, name="weekly_menu"),
    path("nutrition/lookup/", views.nutrition_lookup, name="nutrition_lookup"),
    path("nutrition/analyze-photo/", views.analyze_photo, name="analyze_photo"),
    path("attendance/<int:attendance_id>/add-bulk-foods/", views.add_bulk_foods, name="add_bulk_foods"),
]
