from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import MealFood, WeeklyMenu

User = get_user_model()


class SignUpForm(UserCreationForm):
    email = forms.EmailField(
        required=False,
        label="Email address (optional)",
        widget=forms.EmailInput(attrs={"placeholder": "e.g. name@college.edu"}),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({"placeholder": "Choose a username"})
        if "password1" in self.fields:
            self.fields["password1"].widget.attrs.update({"placeholder": "Enter password"})
        if "password2" in self.fields:
            self.fields["password2"].widget.attrs.update({"placeholder": "Confirm password"})


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({
            "placeholder": "Your username",
            "autofocus": True,
        })
        self.fields["password"].widget.attrs.update({
            "placeholder": "Your password",
        })


class MealFoodForm(forms.ModelForm):
    class Meta:
        model = MealFood
        fields = ("name", "serving", "calories", "protein_g", "carbs_g", "fat_g")
        labels = {
            "name": "Food name",
            "serving": "Portion",
            "calories": "Calories (kcal)",
            "protein_g": "Protein (g)",
            "carbs_g": "Carbs (g)",
            "fat_g": "Fat (g)",
        }
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Dal"}),
            "serving": forms.TextInput(attrs={"placeholder": "e.g. 1 bowl"}),
            "calories": forms.NumberInput(attrs={"min": "0", "step": "0.1"}),
            "protein_g": forms.NumberInput(attrs={"min": "0", "step": "0.1"}),
            "carbs_g": forms.NumberInput(attrs={"min": "0", "step": "0.1"}),
            "fat_g": forms.NumberInput(attrs={"min": "0", "step": "0.1"}),
        }


class WeeklyMenuPhotoForm(forms.ModelForm):
    class Meta:
        model = WeeklyMenu
        fields = ("photo",)
        widgets = {
            "photo": forms.ClearableFileInput(
                attrs={"accept": "image/jpeg,image/png,image/webp"}
            )
        }
