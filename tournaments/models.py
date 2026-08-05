from django.contrib.auth.models import AbstractUser

from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        SUPERADMIN = "superadmin", "Super Admin"
        TOURNAMENT_ADMIN = "tournament_admin", "Tournament Admin"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.TOURNAMENT_ADMIN
    )

    managed_tournaments = models.ManyToManyField(
        "Tournament",
        related_name="admins",
        blank=True
    )

    # Fix the conflict with auth.User
    groups = models.ManyToManyField(
        'auth.Group',
        related_name='custom_user_set',
        blank=True,
        verbose_name='groups',
        help_text='The groups this user belongs to.',
        related_query_name='custom_user',
    )

    user_permissions = models.ManyToManyField(
        'auth.Permission',
        related_name='custom_user_set',
        blank=True,
        verbose_name='user permissions',
        help_text='Specific permissions for this user.',
        related_query_name='custom_user',
    )

    @property
    def is_superadmin(self) -> bool:
        return self.is_superuser or self.role == self.Role.SUPERADMIN

    def can_manage(self, tournament) -> bool:
        if self.is_superadmin:
            return True
        return self.managed_tournaments.filter(pk=tournament.pk).exists()

    def __str__(self):
        return self.get_full_name() or self.username

    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'


class Tournament(models.Model):
    FORMAT_CHOICES = [
        ("league", "League"),
        ("knockout", "Knockout"),
        ("group_knockout", "Group + Knockout"),
        ("swiss", "Swiss"),
        ("swiss_plus", "Swiss Plus"),
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
    is_open = models.BooleanField(default=False)
    swiss_total_rounds = models.IntegerField(null=True, blank=True)
    swiss_rounds_complete = models.IntegerField(null=True, blank=True,default=0)
    swiss_phase_complete = models.BooleanField(default=False)
    split_phase_complete = models.BooleanField(default=False)
    playoff_phase_complete = models.BooleanField(default=False)
    knockout_phase_complete = models.BooleanField(default=False)

    # Split counts (stored for reference)
    swiss_direct_count = models.IntegerField(null=True, blank=True)
    swiss_playoff_count = models.IntegerField(null=True, blank=True)
    swiss_eliminated_count = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def played_fixtures_count(self):
        return self.fixtures.filter(is_played=True).count()

    @property
    def total_fixtures_count(self):
        return self.fixtures.count()

    @property
    def remaining_fixtures_count(self):
        return max(self.total_fixtures_count - self.played_fixtures_count, 0)

    @property
    def progress_percent(self):
        total = self.total_fixtures_count
        if not total:
            return 0
        return round((self.played_fixtures_count / total) * 100)

    @property
    def live_fixture(self):
        """A single in-progress fixture to feature on the scoreboard hero, if any."""
        return self.fixtures.filter(is_live=True).select_related(
            "home_team", "away_team"
        ).first()

    @property
    def next_fixture(self):
        return (
            self.fixtures.filter(is_played=False, is_live=False)
            .exclude(match_date__isnull=True)
            .select_related("home_team", "away_team")
            .order_by("match_date")
            .first()
        )

    @property
    def total_goals(self):
        agg = self.fixtures.filter(is_played=True).aggregate(
            total=models.Sum("result__home_score") + models.Sum("result__away_score")
        )
        return agg.get("total") or 0

    def __str__(self):
        return f"{self.name} ({self.get_tournament_format_display()})"


class Team(models.Model):
    name = models.CharField(max_length=255)
    player_name = models.CharField(max_length=255, default='Player')
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE)

    points = models.IntegerField(default=0)
    played = models.IntegerField(default=0)
    wins = models.IntegerField(default=0)
    draws = models.IntegerField(default=0)
    losses = models.IntegerField(default=0)
    goals_for = models.IntegerField(default=0)
    goals_against = models.IntegerField(default=0)
    previous_position = models.IntegerField(default=0)
    bye_count = models.IntegerField(default=0)  # NEW - swiss bye tracking

    class Meta:
        unique_together = ("tournament", "name")

    @property
    def initials(self):
        """Two-letter badge initials for the crest placeholder, e.g. 'Turbo FC' -> 'TF'."""
        words = [w for w in self.name.split() if w.isalnum()]
        if not words:
            return self.name[:2].upper()
        if len(words) == 1:
            return words[0][:2].upper()
        return (words[0][0] + words[1][0]).upper()

    @property
    def win_rate(self):
        return round((self.wins / self.played) * 100) if self.played else 0

    @property
    def recent_results(self):
        """Last 5 completed fixtures involving this team, oldest first, as 'W'/'D'/'L'."""
        fixtures = (
            Fixture.objects.filter(
                is_played=True
            )
            .filter(models.Q(home_team=self) | models.Q(away_team=self))
            .select_related("result")
            .order_by("-match_date")[:5]
        )
        form = []
        for f in reversed(fixtures):
            if not hasattr(f, "result"):
                continue
            is_home = f.home_team_id == self.id
            mine = f.result.home_score if is_home else f.result.away_score
            theirs = f.result.away_score if is_home else f.result.home_score
            form.append("W" if mine > theirs else "L" if mine < theirs else "D")
        return form

    def __str__(self):
        return self.name


class Group(models.Model):
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE)
    name = models.CharField(max_length=50)  # Group A, B, etc.
    teams = models.ManyToManyField(Team)

    def __str__(self):
        return f"{self.tournament.name} - {self.name}"


class Fixture(models.Model):
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="fixtures")

    home_team = models.ForeignKey(
        Team, related_name="home_fixtures", on_delete=models.CASCADE
    )
    away_team = models.ForeignKey(
        Team, related_name="away_fixtures", on_delete=models.CASCADE
    )

    group = models.ForeignKey(Group, null=True, blank=True, on_delete=models.SET_NULL)

    match_date = models.DateTimeField(null=True, blank=True)

    is_played = models.BooleanField(default=False, db_index=True)
    is_live = models.BooleanField(default=False, db_index=True)  # NEW - powers the scoreboard hero
    round = models.IntegerField(default=1, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['tournament', 'home_team', 'away_team', 'round'],
                name='unique_fixture_per_round'
            )
        ]

    @property
    def status(self):
        if self.is_live:
            return "live"
        if self.is_played:
            return "played"
        return "upcoming"

    def __str__(self):
        return f"{self.home_team} vs {self.away_team} (Round {self.round})"


class Result(models.Model):
    fixture = models.OneToOneField(Fixture, on_delete=models.CASCADE)

    home_score = models.IntegerField(default=0)
    away_score = models.IntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.fixture.home_team} {self.home_score} - {self.away_score} {self.fixture.away_team}"


class Poll(models.Model):
    """Match prediction poll for a fixture."""
    fixture = models.OneToOneField(
        'Fixture',
        on_delete=models.CASCADE,
        related_name='poll'
    )
    home_votes = models.IntegerField(default=0)
    draw_votes = models.IntegerField(default=0)
    away_votes = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def get_results(self):
        total = self.home_votes + self.draw_votes + self.away_votes
        return {
            'home': self.home_votes,
            'draw': self.draw_votes,
            'away': self.away_votes,
            'total': total,
            'home_pct': round((self.home_votes / total * 100)) if total > 0 else 0,
            'draw_pct': round((self.draw_votes / total * 100)) if total > 0 else 0,
            'away_pct': round((self.away_votes / total * 100)) if total > 0 else 0,
        }

    def __str__(self):
        return f"Poll for {self.fixture}"


class PollVote(models.Model):
    """Individual vote record to prevent duplicates."""
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name='votes')
    user_id = models.CharField(max_length=255)  # Session ID or user identifier
    choice = models.CharField(max_length=10)  # 'home', 'draw', 'away'
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('poll', 'user_id')

    def __str__(self):
        return f"{self.user_id} voted {self.choice} on {self.poll}"