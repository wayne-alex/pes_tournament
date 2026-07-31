from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.contrib.auth import get_user_model
from tournaments.models import Tournament, Team, Fixture, Group

User = get_user_model()


class UserForm(UserCreationForm):
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'role', 'is_active']
        widgets = {
            'role': forms.Select(attrs={'class': 'form-select'}),
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].widget.attrs.update({'class': 'form-control'})
        self.fields['password2'].widget.attrs.update({'class': 'form-control'})


class TournamentForm(forms.ModelForm):
    class Meta:
        model = Tournament
        fields = ['name', 'tournament_format', 'mode', 'qualify_per_group', 'is_open']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'tournament_format': forms.Select(attrs={'class': 'form-select'}),
            'mode': forms.Select(attrs={'class': 'form-select'}),
            'qualify_per_group': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'is_open': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class TeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ['name', 'player_name', 'tournament']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'player_name': forms.TextInput(attrs={'class': 'form-control'}),
            'tournament': forms.Select(attrs={'class': 'form-select'}),
        }


class FixtureForm(forms.ModelForm):
    class Meta:
        model = Fixture
        fields = ['tournament', 'home_team', 'away_team', 'group', 'match_date', 'round']
        widgets = {
            'tournament': forms.Select(attrs={'class': 'form-select'}),
            'home_team': forms.Select(attrs={'class': 'form-select'}),
            'away_team': forms.Select(attrs={'class': 'form-select'}),
            'group': forms.Select(attrs={'class': 'form-select'}),
            'match_date': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'round': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
        }