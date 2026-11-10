from django import forms

from .models import MealFood


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
