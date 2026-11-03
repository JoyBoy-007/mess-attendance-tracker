from django.urls import path
from . import views

app_name = "attendance"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("attendance/update/", views.update_attendance, name="update"),
]
