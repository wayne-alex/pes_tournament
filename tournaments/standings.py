from django.db.models import F
from .models import Team, Result


class StandingsService:

    @staticmethod
    def reset_stats(tournament):
        Team.objects.filter(tournament=tournament).update(
            points=0, played=0, wins=0, draws=0,
            losses=0, goals_for=0, goals_against=0,
        )

    @staticmethod
    def calculate(tournament):
        StandingsService.reset_stats(tournament)

        # Cache all teams in a dict keyed by pk
        teams = {team.pk: team for team in Team.objects.filter(tournament=tournament)}

        results = Result.objects.filter(
            fixture__tournament=tournament
        ).select_related("fixture__home_team", "fixture__away_team")

        for result in results:
            # Use cached objects instead of the freshly-fetched related ones
            home = teams[result.fixture.home_team_id]
            away = teams[result.fixture.away_team_id]

            home_score = result.home_score
            away_score = result.away_score

            home.played += 1
            away.played += 1

            home.goals_for += home_score
            home.goals_against += away_score
            away.goals_for += away_score
            away.goals_against += home_score

            if home_score > away_score:
                home.wins += 1
                home.points += 3
                away.losses += 1
            elif home_score < away_score:
                away.wins += 1
                away.points += 3
                home.losses += 1
            else:
                home.draws += 1
                away.draws += 1
                home.points += 1
                away.points += 1

        # Bulk save at the end — much more efficient too
        Team.objects.bulk_update(
            teams.values(),
            ["points", "played", "wins", "draws", "losses", "goals_for", "goals_against"]
        )