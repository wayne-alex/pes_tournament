from django.db.models import F
from .models import Team, Result


class StandingsService:

    @staticmethod
    def reset_stats(tournament):
        Team.objects.filter(tournament=tournament).update(
            points=0,
            played=0,
            wins=0,
            draws=0,
            losses=0,
            goals_for=0,
            goals_against=0,
        )

    @staticmethod
    def calculate(tournament):
        # RESET EVERYTHING FIRST
        StandingsService.reset_stats(tournament)

        results = Result.objects.filter(
            fixture__tournament=tournament
        ).select_related("fixture__home_team", "fixture__away_team")

        for result in results:
            home = result.fixture.home_team
            away = result.fixture.away_team

            home_score = result.home_score
            away_score = result.away_score

            # PLAYED
            home.played += 1
            away.played += 1

            # GOALS
            home.goals_for += home_score
            home.goals_against += away_score

            away.goals_for += away_score
            away.goals_against += home_score

            # RESULT
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

            home.save()
            away.save()