from django.urls import path
from . import views

app_name = "attendance"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("attendance/update/", views.update_attendance, name="update"),
    path("attendance/<int:attendance_id>/foods/", views.meal_foods, name="meal_foods"),
    path("food/<int:food_id>/delete/", views.delete_food, name="delete_food"),
]
