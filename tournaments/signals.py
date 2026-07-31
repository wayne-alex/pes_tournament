from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import Result, Team, Fixture, Group


def _recalculate_team_stats(team: Team):
    """
    Fully recomputes one team's aggregate stats from every Result
    they're involved in, rather than incrementing counters. This
    keeps points/goal-difference correct even if a scoreline gets
    edited or deleted after the fact - a common real-world case.

    For group_knockout tournaments, this only counts group-stage
    Results (fixture.group is set). Knockout-round fixtures are
    created without a group, so once the knockout stage starts,
    those results are excluded here - the group table stays frozen
    at whatever it was when the group phase ended, instead of
    quietly drifting as knockout scores come in. League and Swiss
    tournaments never have Group rows at all, so this filter is a
    no-op for them and every result still counts.
    """
    has_groups = Group.objects.filter(tournament=team.tournament).exists()

    home_results = Result.objects.filter(fixture__home_team=team).select_related(
        "fixture"
    )
    away_results = Result.objects.filter(fixture__away_team=team).select_related(
        "fixture"
    )

    if has_groups:
        home_results = home_results.filter(fixture__group__isnull=False)
        away_results = away_results.filter(fixture__group__isnull=False)

    played = wins = draws = losses = 0
    goals_for = goals_against = 0

    for result in home_results:
        played += 1
        goals_for += result.home_score
        goals_against += result.away_score
        if result.home_score > result.away_score:
            wins += 1
        elif result.home_score < result.away_score:
            losses += 1
        else:
            draws += 1

    for result in away_results:
        played += 1
        goals_for += result.away_score
        goals_against += result.home_score
        if result.away_score > result.home_score:
            wins += 1
        elif result.away_score < result.home_score:
            losses += 1
        else:
            draws += 1

    points = wins * 3 + draws

    # .update() instead of .save() to skip triggering unrelated
    # Team signals/validation and avoid a race with stale instances
    Team.objects.filter(pk=team.pk).update(
        played=played,
        wins=wins,
        draws=draws,
        losses=losses,
        goals_for=goals_for,
        goals_against=goals_against,
        points=points,
    )


@receiver(post_save, sender=Result)
def update_teams_on_result_save(sender, instance: Result, **kwargs):
    fixture = instance.fixture
    _recalculate_team_stats(fixture.home_team)
    _recalculate_team_stats(fixture.away_team)

    if not fixture.is_played:
        Fixture.objects.filter(pk=fixture.pk).update(is_played=True)


@receiver(post_delete, sender=Result)
def update_teams_on_result_delete(sender, instance: Result, **kwargs):
    # fixture may already be gone if this delete cascaded from the
    # fixture itself being deleted - guard against that
    try:
        fixture = instance.fixture
    except Fixture.DoesNotExist:
        return

    _recalculate_team_stats(fixture.home_team)
    _recalculate_team_stats(fixture.away_team)
    Fixture.objects.filter(pk=fixture.pk).update(is_played=False)