from django.db import models


from django.db import models


class Tournament(models.Model):
    FORMAT_CHOICES = [
        ("league", "League"),
        ("knockout", "Knockout"),
        ("group_knockout", "Group + Knockout"),
    ]

    MODE_CHOICES = [
        ("single", "Single Leg"),
        ("home_away", "Home & Away"),
    ]

    name = models.CharField(max_length=255)

    tournament_format = models.CharField(
        max_length=20,
        choices=FORMAT_CHOICES
    )

    mode = models.CharField(
        max_length=20,
        choices=MODE_CHOICES,
        default="single"
    )
    qualify_per_group = models.IntegerField(default=2)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.get_tournament_format_display()})"


class Team(models.Model):
    name = models.CharField(max_length=255)
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE)

    points = models.IntegerField(default=0)
    played = models.IntegerField(default=0)
    wins = models.IntegerField(default=0)
    draws = models.IntegerField(default=0)
    losses = models.IntegerField(default=0)
    goals_for = models.IntegerField(default=0)
    goals_against = models.IntegerField(default=0)

    class Meta:
        unique_together = ("tournament", "name")

    def __str__(self):
        return self.name




class Group(models.Model):
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE)
    name = models.CharField(max_length=50)  # Group A, B, etc.
    teams = models.ManyToManyField(Team)

    def __str__(self):
        return f"{self.tournament.name} - {self.name}"


class Fixture(models.Model):
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE)

    home_team = models.ForeignKey(
        Team, related_name="home_fixtures", on_delete=models.CASCADE
    )
    away_team = models.ForeignKey(
        Team, related_name="away_fixtures", on_delete=models.CASCADE
    )

    group = models.ForeignKey(Group, null=True, blank=True, on_delete=models.SET_NULL)

    match_date = models.DateTimeField(null=True, blank=True)

    round = models.IntegerField(default=1)  # 🔥 NEW

    is_played = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.home_team} vs {self.away_team} (Round {self.round})"


class Result(models.Model):
    fixture = models.OneToOneField(Fixture, on_delete=models.CASCADE)

    home_score = models.IntegerField(default=0)
    away_score = models.IntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.fixture.home_team} {self.home_score} - {self.away_score} {self.fixture.away_team}"
