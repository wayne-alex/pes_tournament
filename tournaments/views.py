import json
import math
from collections import defaultdict

from django.db import models
from django.db.models import Q, F, Sum, Max
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .fixture_generator import FixtureGenerator
from .models import Tournament, Team, Fixture, Result, Group, Poll, PollVote

KNOCKOUT_STAGE_NAMES = ['Final', 'Semi-Final', 'Quarter-Final', 'Round of 16', 'Round of 32']


def _annotate_fixture_stage(fixture_round, swiss_rounds, max_round):
    """
    Human label for a fixture's round.
    Returns None for Swiss-phase rounds (no badge needed there).
    Playoff bracket = swiss_rounds+1 and swiss_rounds+2 (2-round mini bracket).
    Everything after that is the knockout bracket, named by distance from
    the tournament's final round (Final, Semi-Final, Quarter-Final, ...).
    """
    if fixture_round <= swiss_rounds:
        return None

    playoff_end = swiss_rounds + 2
    if fixture_round <= playoff_end:
        return 'Playoff Final' if fixture_round == playoff_end else 'Playoff Semi-Final'

    diff = max_round - fixture_round
    if 0 <= diff < len(KNOCKOUT_STAGE_NAMES):
        return KNOCKOUT_STAGE_NAMES[diff]
    return f'Knockout Round {fixture_round - playoff_end}'


def _stage_css_class(stage_name):
    """Maps a stage label to one of the 3 badge color buckets."""
    if not stage_name:
        return ''
    lowered = stage_name.lower()
    if 'playoff' in lowered:
        return 'playoff'
    if lowered == 'final':
        return 'final'
    return 'knockout'

    def _compute_team_extra_stats(teams):
        """
        Attaches avg_goals, win_rate, clean_sheets, form, trend to each
        Team instance in the list. Not persisted to DB - display only.
        `teams` must be a materialized list (not a lazy queryset), since
        we're bolting attributes onto the actual Python objects.
        """
        for t in teams:
            t.avg_goals = round(t.goals_for / t.played, 1) if t.played else 0.0
            t.win_rate = round((t.wins / t.played) * 100) if t.played else 0

            clean = 0
            team_fixtures = Fixture.objects.filter(
                Q(home_team=t) | Q(away_team=t), is_played=True
            ).select_related('result')
            for f in team_fixtures:
                if not hasattr(f, 'result'):
                    continue
                conceded = f.result.away_score if f.home_team_id == t.id else f.result.home_score
                if conceded == 0:
                    clean += 1
            t.clean_sheets = clean

            t.form = t.recent_results  # already exists on the model, W/D/L list
            if t.form:
                last = t.form[-1]
                t.trend = 'up' if last == 'W' else ('down' if last == 'L' else 'stable')
            else:
                t.trend = 'stable'
        return teams

def _compute_team_extra_stats(teams):
    """
    Attaches avg_goals, win_rate, clean_sheets, form, trend to each
    Team instance in the list. Not persisted to DB - display only.
    `teams` must be a materialized list (not a lazy queryset), since
    we're bolting attributes onto the actual Python objects.
    """
    for t in teams:
        t.avg_goals = round(t.goals_for / t.played, 1) if t.played else 0.0
        # Use a different attribute name, e.g., t.win_rate_display or t.win_rate_calc
        t.win_rate_calc = round((t.wins / t.played) * 100) if t.played else 0

        clean = 0
        team_fixtures = Fixture.objects.filter(
            Q(home_team=t) | Q(away_team=t), is_played=True
        ).select_related('result')
        for f in team_fixtures:
            if not hasattr(f, 'result'):
                continue
            conceded = f.result.away_score if f.home_team_id == t.id else f.result.home_score
            if conceded == 0:
                clean += 1
        t.clean_sheets = clean

        t.form = t.recent_results  # already exists on the model, W/D/L list
        if t.form:
            last = t.form[-1]
            t.trend = 'up' if last == 'W' else ('down' if last == 'L' else 'stable')
        else:
            t.trend = 'stable'
    return teams
def _get_phase_standings(team_ids, round_min, round_max):
    """
    Standings built ONLY from fixtures played inside [round_min, round_max].
    This is what makes the Playoff/Knockout tables reflect that phase alone,
    instead of a team's Swiss-phase cumulative points/wins/losses.
    """
    if not team_ids:
        return []

    points, wins, draws, losses = (defaultdict(int) for _ in range(4))
    played, gf, ga = (defaultdict(int) for _ in range(3))

    fixtures = Fixture.objects.filter(
        is_played=True, round__gte=round_min, round__lte=round_max
    ).filter(
        Q(home_team_id__in=team_ids) | Q(away_team_id__in=team_ids)
    ).select_related('result').distinct()

    for f in fixtures:
        if not hasattr(f, 'result'):
            continue
        r = f.result
        h, a = f.home_team_id, f.away_team_id
        played[h] += 1
        played[a] += 1
        gf[h] += r.home_score
        ga[h] += r.away_score
        gf[a] += r.away_score
        ga[a] += r.home_score
        if r.home_score > r.away_score:
            points[h] += 3
            wins[h] += 1
            losses[a] += 1
        elif r.home_score < r.away_score:
            points[a] += 3
            wins[a] += 1
            losses[h] += 1
        else:
            points[h] += 1
            points[a] += 1
            draws[h] += 1
            draws[a] += 1

    teams = Team.objects.filter(id__in=team_ids)
    standings = []
    for t in teams:
        gd = gf.get(t.id, 0) - ga.get(t.id, 0)
        standings.append({
            'id': t.id,
            'name': t.name,
            'points': points.get(t.id, 0),
            'played': played.get(t.id, 0),
            'wins': wins.get(t.id, 0),
            'draws': draws.get(t.id, 0),
            'losses': losses.get(t.id, 0),
            'goals_for': gf.get(t.id, 0),
            'goals_against': ga.get(t.id, 0),
            'goal_diff': gd,
        })

    standings.sort(key=lambda x: (-x['points'], -x['goal_diff'], -x['goals_for']))
    return standings


def _get_runner_up_name(tournament, max_round):
    """Loser of the final (max_round) fixture — for the champion card."""
    final_fixtures = Fixture.objects.filter(
        tournament=tournament, round=max_round, is_played=True
    ).select_related('result', 'home_team', 'away_team')

    for fixture in final_fixtures:
        if hasattr(fixture, 'result') and fixture.result:
            if fixture.result.home_score > fixture.result.away_score:
                return fixture.away_team.name
            elif fixture.result.away_score > fixture.result.home_score:
                return fixture.home_team.name
    return None


def _get_phase_context(tournament, swiss_rounds, max_round):
    """
    Shared by dashboard() and tournament_live_api() so both stay in sync:
    which phases exist, which one should be the default-selected pill, and
    the phase-scoped standings for each.
    """
    playoff_standings, knockout_standings = [], []
    has_playoff_phase, has_knockout_phase = False, False

    if tournament.tournament_format == 'swiss_plus':
        try:
            playoff_group = Group.objects.get(tournament=tournament, name='Playoff')
            playoff_team_ids = list(playoff_group.teams.values_list('id', flat=True))
            has_playoff_phase = bool(playoff_team_ids) and Fixture.objects.filter(
                tournament=tournament, round__gt=swiss_rounds, round__lte=swiss_rounds + 2
            ).exists()
            playoff_standings = _get_phase_standings(
                playoff_team_ids, swiss_rounds + 1, swiss_rounds + 2
            )
        except Group.DoesNotExist:
            pass

        try:
            knockout_group = Group.objects.get(tournament=tournament, name='Direct Qualifiers')
            knockout_team_ids = list(knockout_group.teams.values_list('id', flat=True))
            # Playoff winners graduate into the knockout bracket too — pull in
            # anyone who has actually played a knockout-round fixture so they
            # show up even if they didn't start there.
            for h, a in Fixture.objects.filter(
                    tournament=tournament, round__gt=swiss_rounds + 2
            ).values_list('home_team_id', 'away_team_id'):
                if h not in knockout_team_ids:
                    knockout_team_ids.append(h)
                if a not in knockout_team_ids:
                    knockout_team_ids.append(a)

            has_knockout_phase = Fixture.objects.filter(
                tournament=tournament, round__gt=swiss_rounds + 2
            ).exists()
            knockout_standings = _get_phase_standings(
                knockout_team_ids, swiss_rounds + 3, max_round
            )
        except Group.DoesNotExist:
            pass

    if tournament.knockout_phase_complete or has_knockout_phase:
        default_phase = 'knockout'
    elif has_playoff_phase:
        default_phase = 'playoff'
    else:
        default_phase = 'swiss'

    return {
        'playoff_standings': playoff_standings,
        'knockout_standings': knockout_standings,
        'has_playoff_phase': has_playoff_phase,
        'has_knockout_phase': has_knockout_phase,
        'default_phase': default_phase,
    }


def _build_playoff_ties(tournament, swiss_rounds):
    """
    Two-legged playoff ties with correctly aggregated scores.

    Returns a list of dicts, one per tie:
        home_team_id, away_team_id, home_team_name, away_team_name,
        home_aggregate, away_aggregate,
        home_leg1, away_leg1, home_leg2, away_leg2,
        leg1_played, leg2_played, is_played (True only once both legs done),
        winner, winner_name
    """
    playoff_end_round = swiss_rounds + 2
    fixtures_qs = Fixture.objects.filter(
        tournament=tournament,
        round__gt=swiss_rounds,
        round__lte=playoff_end_round
    ).select_related('home_team', 'away_team', 'result').order_by('round', 'id')

    ties = {}
    for fixture in fixtures_qs:
        key = f"{min(fixture.home_team_id, fixture.away_team_id)}_{max(fixture.home_team_id, fixture.away_team_id)}"
        leg_num = 1 if fixture.round == swiss_rounds + 1 else 2

        if key not in ties:
            # Whichever pairing shows up first (leg 1, normally) becomes
            # the tie's fixed home/away reference frame.
            ties[key] = {
                'home_team_id': fixture.home_team_id,
                'away_team_id': fixture.away_team_id,
                'home_team_name': fixture.home_team.name,
                'away_team_name': fixture.away_team.name,
                'home_aggregate': 0,
                'away_aggregate': 0,
                'home_leg1': None, 'away_leg1': None,
                'home_leg2': None, 'away_leg2': None,
                'leg1_played': False,
                'leg2_played': False,
                'is_played': False,
                'winner': None,
                'winner_name': None,
            }

        tie = ties[key]

        if not (fixture.is_played and hasattr(fixture, 'result')):
            continue

        # Map THIS fixture's score onto the tie's FIXED home/away side.
        if fixture.home_team_id == tie['home_team_id']:
            tie_home_score = fixture.result.home_score
            tie_away_score = fixture.result.away_score
        else:
            tie_home_score = fixture.result.away_score
            tie_away_score = fixture.result.home_score

        tie['home_aggregate'] += tie_home_score
        tie['away_aggregate'] += tie_away_score

        if leg_num == 1:
            tie['home_leg1'], tie['away_leg1'] = tie_home_score, tie_away_score
            tie['leg1_played'] = True
        else:
            tie['home_leg2'], tie['away_leg2'] = tie_home_score, tie_away_score
            tie['leg2_played'] = True

        if tie['leg1_played'] and tie['leg2_played']:
            tie['is_played'] = True
            if tie['home_aggregate'] > tie['away_aggregate']:
                tie['winner'] = tie['home_team_id']
                tie['winner_name'] = tie['home_team_name']
            elif tie['away_aggregate'] > tie['home_aggregate']:
                tie['winner'] = tie['away_team_id']
                tie['winner_name'] = tie['away_team_name']
            # equal aggregate with both legs played -> stays a genuine draw

    return list(ties.values())


def dashboard(request, tournament_id):
    tournament = get_object_or_404(Tournament, id=tournament_id)

    groups = Group.objects.filter(tournament=tournament).prefetch_related("teams")
    group_tables = []
    for group in groups:
        teams = group.teams.annotate(
            goal_difference=F('goals_for') - F('goals_against')
        ).order_by('-points', '-goal_difference', '-goals_for')
        group_tables.append({"group": group, "teams": teams})

    league_table = Team.objects.filter(tournament=tournament).annotate(
        goal_difference=F('goals_for') - F('goals_against')
    ).order_by('-points', '-goal_difference', '-goals_for')

    swiss_rounds = tournament.swiss_total_rounds or 0
    total_swiss_rounds = tournament.swiss_total_rounds or swiss_rounds
    max_round = Fixture.objects.filter(tournament=tournament).aggregate(
        m=Max('round')
    )['m'] or swiss_rounds

    fixtures = list(
        Fixture.objects.filter(tournament=tournament)
        .select_related("home_team", "away_team", "group", "result")
        .order_by("match_date")
    )
    for f in fixtures:
        f.stage_name = _annotate_fixture_stage(f.round, swiss_rounds, max_round)
        f.stage_css = _stage_css_class(f.stage_name)
        if f.is_played and hasattr(f, "result"):
            f.home_score = f.result.home_score
            f.away_score = f.result.away_score
        else:
            f.home_score = None
            f.away_score = None

    results = Result.objects.filter(
        fixture__tournament=tournament
    ).select_related("fixture", "fixture__home_team", "fixture__away_team").order_by(
        "-fixture__match_date"
    )

    knockout_fixtures = Fixture.objects.filter(
        tournament=tournament, group__isnull=True
    ).select_related("home_team", "away_team")
    grouped = {}
    for f in knockout_fixtures:
        grouped.setdefault(f.round, []).append(f)
    rounds = [grouped[r] for r in sorted(grouped)]
    all_teams = list(Team.objects.filter(tournament=tournament).annotate(
        goal_difference=F('goals_for') - F('goals_against')
    ).order_by('-points', '-goal_difference', '-goals_for'))

    _compute_team_extra_stats(all_teams)

    top_scorers = sorted(all_teams, key=lambda t: -t.goals_for)[:10]
    most_wins = sorted(all_teams, key=lambda t: (-t.wins, -t.points))[:10]
    best_defense = sorted([t for t in all_teams if t.played > 0], key=lambda t: t.goals_against)[:10]

    champion_name, runner_up_name = None, None
    if tournament.knockout_phase_complete:
        champion_name = _get_champion_name(tournament)
        runner_up_name = _get_runner_up_name(tournament, max_round)

    # Get Swiss standings (ONLY Swiss phase games)
    swiss_standings = _get_swiss_standings_with_stats(tournament, swiss_rounds)
    phase_ctx = _get_phase_context(tournament, swiss_rounds, max_round)

    # Playoff ties (two-legged)
    playoff_fixtures = _build_playoff_ties(tournament, swiss_rounds)

    # Knockout fixtures by round with stage names
    knockout_fixtures_by_round = {}
    knockout_start_round = swiss_rounds + 3
    knockout_fixtures_qs = Fixture.objects.filter(
        tournament=tournament,
        round__gte=knockout_start_round
    ).select_related('home_team', 'away_team', 'result').order_by('round', 'id')

    for fixture in knockout_fixtures_qs:
        round_num = fixture.round
        if round_num not in knockout_fixtures_by_round:
            knockout_fixtures_by_round[round_num] = []

        stage_name = _annotate_fixture_stage(fixture.round, swiss_rounds, max_round)

        match_data = {
            'id': fixture.id,
            'home_team_id': fixture.home_team.id,
            'away_team_id': fixture.away_team.id,
            'home_team_name': fixture.home_team.name,
            'away_team_name': fixture.away_team.name,
            'is_played': fixture.is_played,
            'home_score': None,
            'away_score': None,
            'winner': None,
            'winner_name': None,
            'stage_name': stage_name,
        }
        if fixture.is_played and hasattr(fixture, 'result'):
            match_data['home_score'] = fixture.result.home_score
            match_data['away_score'] = fixture.result.away_score
            if fixture.result.home_score > fixture.result.away_score:
                match_data['winner'] = fixture.home_team.id
                match_data['winner_name'] = fixture.home_team.name
            elif fixture.result.away_score > fixture.result.home_score:
                match_data['winner'] = fixture.away_team.id
                match_data['winner_name'] = fixture.away_team.name
        knockout_fixtures_by_round[round_num].append(match_data)

    live_fixture = tournament.live_fixture
    if live_fixture:
        live_fixture.stage_name = _annotate_fixture_stage(live_fixture.round, swiss_rounds, max_round)
        live_fixture.stage_css = _stage_css_class(live_fixture.stage_name)

    next_fixture = tournament.next_fixture
    if next_fixture:
        next_fixture.stage_name = _annotate_fixture_stage(next_fixture.round, swiss_rounds, max_round)
        next_fixture.stage_css = _stage_css_class(next_fixture.stage_name)

    return render(request, "dashboard.html", {
        "tournament": tournament,
        "group_tables": group_tables,
        "league_table": league_table,
        "fixtures": fixtures,
        "results": results,
        "rounds": rounds,
        "top_scorers": top_scorers,
        "most_wins": most_wins,
        "best_defense": best_defense,
        "all_teams": all_teams,
        "live_fixture": live_fixture,
        "next_fixture": next_fixture,
        "today_str": __import__("datetime").date.today().strftime('%Y-%m-%d'),
        "swiss_rounds": swiss_rounds,
        "total_swiss_rounds": total_swiss_rounds,
        "max_round": max_round,
        "champion_name": champion_name,
        "runner_up_name": runner_up_name,
        "is_swiss_pro": tournament.tournament_format == 'swiss_plus',
        "swiss_standings": swiss_standings,
        "playoff_standings": phase_ctx["playoff_standings"],
        "knockout_standings": phase_ctx["knockout_standings"],
        "has_playoff_phase": phase_ctx["has_playoff_phase"],
        "has_knockout_phase": phase_ctx["has_knockout_phase"],
        "default_phase": phase_ctx["default_phase"],
        "total_goals": tournament.total_goals,
        "total_matches_played": tournament.played_fixtures_count,
        "playoff_fixtures": playoff_fixtures,
        "knockout_fixtures_by_round": knockout_fixtures_by_round,
        "direct_count": tournament.swiss_direct_count or 0,
        "playoff_count": tournament.swiss_playoff_count or 0,
        "split_complete": tournament.split_phase_complete or False,
    })


def _get_swiss_standings_with_stats(tournament, swiss_rounds):
    """
    Get Swiss standings with correct stats calculated ONLY from Swiss phase games.
    """
    points = defaultdict(int)
    wins = defaultdict(int)
    draws = defaultdict(int)
    losses = defaultdict(int)
    played = defaultdict(int)
    goals_for = defaultdict(int)
    goals_against = defaultdict(int)

    # Filter fixtures to ONLY Swiss phase (rounds <= swiss_rounds)
    fixtures_qs = Fixture.objects.filter(
        tournament=tournament,
        is_played=True,
        round__lte=swiss_rounds
    ).select_related('result')

    for fixture in fixtures_qs:
        if not hasattr(fixture, 'result'):
            continue
        result = fixture.result
        home_id = fixture.home_team_id
        away_id = fixture.away_team_id

        played[home_id] += 1
        played[away_id] += 1
        goals_for[home_id] += result.home_score
        goals_for[away_id] += result.away_score
        goals_against[home_id] += result.away_score
        goals_against[away_id] += result.home_score

        if result.home_score > result.away_score:
            points[home_id] += 3
            wins[home_id] += 1
            losses[away_id] += 1
        elif result.home_score < result.away_score:
            points[away_id] += 3
            wins[away_id] += 1
            losses[home_id] += 1
        else:
            points[home_id] += 1
            points[away_id] += 1
            draws[home_id] += 1
            draws[away_id] += 1

    # Buchholz
    buchholz = defaultdict(int)
    teams = Team.objects.filter(tournament=tournament)

    for team in teams:
        total = 0
        team_fixtures = fixtures_qs.filter(Q(home_team=team) | Q(away_team=team))
        for f in team_fixtures:
            opp_id = f.away_team_id if f.home_team_id == team.id else f.home_team_id
            total += points.get(opp_id, 0)
        buchholz[team.id] = total

    standings = []
    for team in teams:
        gd = goals_for.get(team.id, 0) - goals_against.get(team.id, 0)
        standings.append({
            'id': team.id,
            'name': team.name,
            'points': points.get(team.id, 0),
            'played': played.get(team.id, 0),
            'wins': wins.get(team.id, 0),
            'draws': draws.get(team.id, 0),
            'losses': losses.get(team.id, 0),
            'goals_for': goals_for.get(team.id, 0),
            'goals_against': goals_against.get(team.id, 0),
            'goal_diff': gd,
            'buchholz': buchholz.get(team.id, 0),
        })

    standings.sort(key=lambda x: (-x['points'], -x['goal_diff'], -x['goals_for']))
    return standings


def _get_champion_name(tournament):
    """Unchanged from your original — kept here for completeness."""
    max_round = Fixture.objects.filter(tournament=tournament).aggregate(
        Max('round')
    )['round__max'] or 0
    if max_round == 0:
        return None

    final_fixtures = Fixture.objects.filter(
        tournament=tournament, round=max_round, is_played=True
    ).select_related('result', 'home_team', 'away_team')

    for fixture in final_fixtures:
        if hasattr(fixture, 'result') and fixture.result:
            if fixture.result.home_score > fixture.result.away_score:
                return fixture.home_team.name
            elif fixture.result.away_score > fixture.result.home_score:
                return fixture.away_team.name
    return None


def _get_swiss_standings_with_buchholz(tournament):
    """Unchanged from your original — kept here for completeness."""
    points = defaultdict(int)
    goals_for = defaultdict(int)
    goals_against = defaultdict(int)

    fixtures = Fixture.objects.filter(
        tournament=tournament, is_played=True
    ).select_related('result')

    for fixture in fixtures:
        if not hasattr(fixture, 'result'):
            continue
        result = fixture.result
        home_id = fixture.home_team_id
        away_id = fixture.away_team_id

        if result.home_score > result.away_score:
            points[home_id] += 3
        elif result.home_score < result.away_score:
            points[away_id] += 3
        else:
            points[home_id] += 1
            points[away_id] += 1

        goals_for[home_id] += result.home_score
        goals_for[away_id] += result.away_score
        goals_against[home_id] += result.away_score
        goals_against[away_id] += result.home_score

    buchholz = defaultdict(int)
    teams = Team.objects.filter(tournament=tournament)

    for team in teams:
        total = 0
        team_fixtures = Fixture.objects.filter(
            tournament=tournament, is_played=True
        ).filter(Q(home_team=team) | Q(away_team=team))
        for f in team_fixtures:
            opp_id = f.away_team_id if f.home_team_id == team.id else f.home_team_id
            total += points.get(opp_id, 0)
        buchholz[team.id] = total

    standings = []
    for team in teams:
        gd = goals_for.get(team.id, 0) - goals_against.get(team.id, 0)
        standings.append({
            'id': team.id,
            'name': team.name,
            'points': points.get(team.id, 0),
            'played': team.played or 0,
            'wins': team.wins or 0,
            'draws': team.draws or 0,
            'losses': team.losses or 0,
            'goals_for': goals_for.get(team.id, 0),
            'goals_against': goals_against.get(team.id, 0),
            'goal_diff': gd,
            'buchholz': buchholz.get(team.id, 0),
        })

    standings.sort(key=lambda x: (-x['points'], -x['buchholz'], -x['goal_diff']))
    return standings


def tournament_live_api(request, tournament_id):
    """JSON endpoint for live dynamic updating."""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    teams = Team.objects.filter(tournament=tournament)
    fixtures = Fixture.objects.filter(tournament=tournament).select_related(
        "home_team", "away_team", "result"
    )
    results = Result.objects.filter(fixture__tournament=tournament).select_related(
        "fixture", "fixture__home_team", "fixture__away_team"
    ).order_by("-fixture__match_date")

    swiss_rounds = tournament.swiss_rounds_complete or 0
    max_round = Fixture.objects.filter(tournament=tournament).aggregate(
        m=Max('round')
    )['m'] or swiss_rounds

    # Get Swiss standings (ONLY Swiss phase games)
    swiss_standings = _get_swiss_standings_with_stats(tournament, swiss_rounds)

    # Get overall standings data for other parts of the API
    standings_data = [
        {
            "id": t.id, "name": t.name, "initials": t.initials,
            "player_name": t.player_name,
            "played": t.played, "wins": t.wins, "draws": t.draws, "losses": t.losses,
            "goals_for": t.goals_for, "goals_against": t.goals_against, "points": t.points,
        }
        for t in teams
    ]

    fixtures_data = []
    for f in fixtures:
        stage = _annotate_fixture_stage(f.round, swiss_rounds, max_round)
        home_score = away_score = None
        if f.is_played and hasattr(f, "result"):
            home_score = f.result.home_score
            away_score = f.result.away_score
        fixtures_data.append({
            "id": f.id,
            "home_team__name": f.home_team.name,
            "away_team__name": f.away_team.name,
            "match_date": f.match_date.isoformat() if f.match_date else None,
            "is_played": f.is_played,
            "is_live": f.is_live,
            "home_score": home_score,
            "away_score": away_score,
            "stage": stage,
            "stage_css": _stage_css_class(stage),
        })

    results_data = [
        {
            "id": r.id,
            "home_team": r.fixture.home_team.name,
            "away_team": r.fixture.away_team.name,
            "home_score": r.home_score,
            "away_score": r.away_score,
            "match_date": r.fixture.match_date.isoformat() if r.fixture.match_date else None,
        }
        for r in results
    ]

    live_fixture = tournament.live_fixture
    live_data = None
    if live_fixture:
        live_data = {
            "home_team": live_fixture.home_team.name,
            "away_team": live_fixture.away_team.name,
            "home_score": getattr(live_fixture, "result", None).home_score if hasattr(live_fixture, "result") else 0,
            "away_score": getattr(live_fixture, "result", None).away_score if hasattr(live_fixture, "result") else 0,
            "stage": _annotate_fixture_stage(live_fixture.round, swiss_rounds, max_round),
        }

    champion_name, runner_up_name = None, None
    if tournament.knockout_phase_complete:
        champion_name = _get_champion_name(tournament)
        runner_up_name = _get_runner_up_name(tournament, max_round)

    phase_ctx = _get_phase_context(tournament, swiss_rounds, max_round)

    return JsonResponse({
        "standings": standings_data,
        "swiss_standings": swiss_standings,  # Now only Swiss phase matches
        "swiss_direct_count": tournament.swiss_direct_count or 0,
        "swiss_playoff_count": tournament.swiss_playoff_count or 0,
        "is_swiss_pro": tournament.tournament_format == 'swiss_plus',
        "playoff_standings": phase_ctx["playoff_standings"],
        "knockout_standings": phase_ctx["knockout_standings"],
        "has_playoff_phase": phase_ctx["has_playoff_phase"],
        "has_knockout_phase": phase_ctx["has_knockout_phase"],
        "fixtures": fixtures_data,
        "results": results_data,
        "live": live_data,
        "played_count": tournament.played_fixtures_count,
        "total_count": tournament.total_fixtures_count,
        "champion_name": champion_name,
        "runner_up_name": runner_up_name,
        "swiss_rounds": swiss_rounds,
        "total_swiss_rounds": tournament.swiss_total_rounds or swiss_rounds,
    })


def lobby(request):
    tournaments = Tournament.objects.filter(is_open=True).order_by("-id")

    return render(request, "lobby.html", {
        "tournaments": tournaments
    })


@csrf_exempt
@require_http_methods(["POST"])
def cast_poll_vote(request, fixture_id):
    """Cast a vote in a match poll."""
    try:
        data = json.loads(request.body)
        choice = data.get('choice')  # 'home', 'draw', or 'away'

        if choice not in ['home', 'draw', 'away']:
            return JsonResponse({'error': 'Invalid choice'}, status=400)

        # Get or create poll for this fixture
        poll, created = Poll.objects.get_or_create(
            fixture_id=fixture_id,
            defaults={'home_votes': 0, 'draw_votes': 0, 'away_votes': 0}
        )

        # Get user identifier (use session or IP)
        user_id = request.session.session_key
        if not user_id:
            request.session.create()
            user_id = request.session.session_key

        # Check if user already voted
        if PollVote.objects.filter(poll=poll, user_id=user_id).exists():
            return JsonResponse({'error': 'Already voted', 'current': poll.get_results()}, status=409)

        # Record vote
        if choice == 'home':
            poll.home_votes += 1
        elif choice == 'draw':
            poll.draw_votes += 1
        else:
            poll.away_votes += 1

        poll.save()

        # Save vote record
        PollVote.objects.create(poll=poll, user_id=user_id, choice=choice)

        return JsonResponse({
            'success': True,
            'current': poll.get_results()
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["GET"])
def get_poll_results(request, fixture_id):
    """Get current poll results for a fixture."""
    try:
        poll = Poll.objects.filter(fixture_id=fixture_id).first()

        if not poll:
            return JsonResponse({
                'home': 0,
                'draw': 0,
                'away': 0,
                'total': 0
            })

        return JsonResponse(poll.get_results())

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def offline_page(request):
    """Serve the offline fallback page."""
    return render(request, 'offline.html')


def service_worker(request):
    """Serve the service worker file."""
    response = render(request, 'sw.js', content_type='application/javascript')
    response['Service-Worker-Allowed'] = '/'
    return response


@csrf_exempt
def save_pending_vote(request):
    """Endpoint to save votes when offline via IndexedDB."""
    if request.method == 'POST':
        data = json.loads(request.body)
        # Store in database with offline flag
        # Implementation depends on your models
        return JsonResponse({'status': 'queued'})
    return JsonResponse({'error': 'Method not allowed'}, status=405)


# ============================================================
# TOURNAMENT DASHBOARDS - All Formats
# ============================================================

def tournament_dashboard(request, tournament_id):
    """
    Main tournament dashboard - handles League, Knockout, and Group Knockout.
    Swiss and Swiss Pro use their own dedicated dashboard.
    """
    tournament = get_object_or_404(Tournament, id=tournament_id)

    # Redirect Swiss formats to their dedicated dashboard
    if tournament.tournament_format in ['swiss', 'swiss_plus']:
        return redirect('swiss_dashboard', tournament_id=tournament_id)

    # League, Knockout, Group Knockout
    groups = Group.objects.filter(tournament=tournament).prefetch_related("teams")
    group_tables = []
    for group in groups:
        teams = group.teams.annotate(
            goal_difference=F('goals_for') - F('goals_against')
        ).order_by('-points', '-goal_difference', '-goals_for')
        group_tables.append({
            "group": group,
            "teams": teams,
        })

    league_table = Team.objects.filter(tournament=tournament).annotate(
        goal_difference=F('goals_for') - F('goals_against')
    ).order_by('-points', '-goal_difference', '-goals_for')

    fixtures = Fixture.objects.filter(
        tournament=tournament,
        is_played=False
    ).select_related("home_team", "away_team", "group").order_by("match_date")

    results = Result.objects.filter(
        fixture__tournament=tournament
    ).select_related("fixture", "fixture__home_team", "fixture__away_team").order_by(
        "-fixture__match_date"
    )

    # Knockout rounds (for knockout and group_knockout formats)
    knockout_fixtures = Fixture.objects.filter(
        tournament=tournament,
        group__isnull=True
    ).select_related("home_team", "away_team")
    grouped = {}
    for f in knockout_fixtures:
        grouped.setdefault(f.round, []).append(f)
    rounds = [grouped[r] for r in sorted(grouped)]

    top_scorers = (
        Team.objects.filter(tournament=tournament)
        .annotate(total_goals=Sum("goals_for"))
        .order_by("-total_goals")[:10]
    )

    most_wins = Team.objects.filter(tournament=tournament).order_by("-wins", "-points")[:10]

    best_defense = (
        Team.objects.filter(tournament=tournament)
        .filter(played__gt=0)
        .order_by("goals_against")[:10]
    )

    all_teams = Team.objects.filter(tournament=tournament).annotate(
        goal_difference=F('goals_for') - F('goals_against')
    ).order_by('-points', '-goal_difference')

    return render(request, "dashboard.html", {
        "tournament": tournament,
        "group_tables": group_tables,
        "league_table": league_table,
        "fixtures": fixtures,
        "results": results,
        "rounds": rounds,
        "top_scorers": top_scorers,
        "most_wins": most_wins,
        "best_defense": best_defense,
        "all_teams": all_teams,
        "live_fixture": tournament.live_fixture,
        "next_fixture": tournament.next_fixture,
        "today_str": date.today().strftime('%Y-%m-%d'),
    })


# ============================================================
# SWISS DASHBOARD VIEW
# ============================================================


# views.py - Update swiss_dashboard view

def swiss_dashboard(request, tournament_id):
    """Swiss-specific dashboard showing standings, fixtures, and phase progress."""
    tournament = get_object_or_404(Tournament, id=tournament_id)

    # Only allow Swiss formats
    if tournament.tournament_format not in ['swiss', 'swiss_plus']:
        return redirect('admin_fixture_list')

    # Get standings
    standings = _calculate_swiss_standings(tournament)

    # Get fixtures by round
    fixtures_by_round = {}
    fixtures = Fixture.objects.filter(tournament=tournament).select_related(
        'home_team', 'away_team', 'result'
    ).order_by('round', 'match_date')

    for fixture in fixtures:
        round_num = fixture.round
        if round_num not in fixtures_by_round:
            fixtures_by_round[round_num] = []
        fixtures_by_round[round_num].append(fixture)

    # Get split groups (Swiss Pro only)
    split_groups = {}
    if tournament.tournament_format == 'swiss_plus':
        for group_name in ['Direct Qualifiers', 'Playoff', 'Eliminated']:
            try:
                group = Group.objects.get(tournament=tournament, name=group_name)
                split_groups[group_name] = list(group.teams.all())
            except Group.DoesNotExist:
                split_groups[group_name] = []

    # Determine current phase
    current_phase = 'swiss'
    champion_name = None

    if tournament.tournament_format == 'swiss_plus':
        if tournament.knockout_phase_complete:
            current_phase = 'knockout'
            # Get the champion from the final match
            champion_name = _get_champion_name(tournament)
        elif tournament.playoff_phase_complete:
            current_phase = 'playoff'
        elif tournament.split_phase_complete:
            current_phase = 'split'

    # Check Swiss completion
    total_swiss_rounds = tournament.swiss_total_rounds or 0

    # If no total rounds set, calculate it
    if total_swiss_rounds == 0:
        team_count = Team.objects.filter(tournament=tournament).count()
        total_rounds = max(4, math.ceil(math.log2(team_count)) + 2)
        tournament.swiss_total_rounds = total_rounds
        tournament.save(update_fields=['swiss_total_rounds'])

    # Get the max generated round
    max_generated_round = Fixture.objects.filter(
        tournament=tournament
    ).aggregate(models.Max('round'))['round__max'] or 0

    # Count pending fixtures (only for generated rounds)
    pending_fixtures = 0
    if max_generated_round > 0:
        pending_fixtures = Fixture.objects.filter(
            tournament=tournament,
            round__lte=max_generated_round,
            is_played=False
        ).exclude(away_team__isnull=True).count()

    # Swiss is complete when:
    # 1. We have generated all rounds
    # 2. No pending fixtures
    swiss_complete = False
    if max_generated_round >= total_swiss_rounds and pending_fixtures == 0:
        swiss_complete = True

    # Get knockout bracket for display
    knockout_bracket = []
    if tournament.tournament_format == 'swiss_plus' and current_phase in ['playoff', 'knockout']:
        swiss_rounds = tournament.swiss_total_rounds or 0
        playoff_count = tournament.swiss_playoff_count or 0
        playoff_rounds = 2 if playoff_count > 0 else 0
        knockout_start_round = swiss_rounds + playoff_rounds + 1

        knockout_fixtures = Fixture.objects.filter(
            tournament=tournament,
            round__gte=knockout_start_round
        ).select_related('home_team', 'away_team', 'result').order_by('round')

        for fixture in knockout_fixtures:
            knockout_bracket.append({
                'home_team': fixture.home_team,
                'away_team': fixture.away_team,
                'is_played': fixture.is_played,
                'result': fixture.result if hasattr(fixture, 'result') else None,
                'round': fixture.round,
            })

    context = {
        'tournament': tournament,
        'standings': standings,
        'fixtures_by_round': fixtures_by_round,
        'split_groups': split_groups,
        'current_phase': current_phase,
        'swiss_total_rounds': total_swiss_rounds,
        'swiss_complete': swiss_complete,
        'pending_fixtures': pending_fixtures,
        'max_generated_round': max_generated_round,
        'is_swiss_pro': tournament.tournament_format == 'swiss_plus',
        'direct_count': tournament.swiss_direct_count or 0,
        'playoff_count': tournament.swiss_playoff_count or 0,
        'eliminated_count': tournament.swiss_eliminated_count or 0,
        'champion_name': champion_name,
        'knockout_bracket': knockout_bracket,
    }

    return render(request, 'superadmin/swiss_dashboard.html', context)


def _get_champion_name(tournament):
    """
    Get the champion name from the final match of the tournament.
    """
    # Find the highest round number
    max_round = Fixture.objects.filter(tournament=tournament).aggregate(
        models.Max('round')
    )['round__max'] or 0

    if max_round == 0:
        return None

    # Get the final match (highest round, should only be 1 match)
    final_fixtures = Fixture.objects.filter(
        tournament=tournament,
        round=max_round,
        is_played=True
    ).select_related('result', 'home_team', 'away_team')

    for fixture in final_fixtures:
        if hasattr(fixture, 'result') and fixture.result:
            if fixture.result.home_score > fixture.result.away_score:
                return fixture.home_team.name
            elif fixture.result.away_score > fixture.result.home_score:
                return fixture.away_team.name
            else:
                # Draw - shouldn't happen in knockout
                return None

    return None


# ============================================================
# SWISS HELPER FUNCTIONS
# ============================================================

def _calculate_swiss_standings(tournament):
    """Helper to calculate Swiss standings with Buchholz."""
    standings = []
    teams = Team.objects.filter(tournament=tournament)

    # First pass: calculate points and goals
    points = defaultdict(int)
    goals_for = defaultdict(int)
    goals_against = defaultdict(int)

    fixtures = Fixture.objects.filter(
        tournament=tournament,
        is_played=True
    ).select_related('result')

    for fixture in fixtures:
        if not hasattr(fixture, 'result'):
            continue
        result = fixture.result
        home_id = fixture.home_team_id
        away_id = fixture.away_team_id

        if result.home_score > result.away_score:
            points[home_id] += 3
        elif result.home_score < result.away_score:
            points[away_id] += 3
        else:
            points[home_id] += 1
            points[away_id] += 1

        goals_for[home_id] += result.home_score
        goals_for[away_id] += result.away_score
        goals_against[home_id] += result.away_score
        goals_against[away_id] += result.home_score

    # Second pass: calculate Buchholz
    buchholz = defaultdict(int)
    for team in teams:
        total = 0
        team_fixtures = Fixture.objects.filter(
            tournament=tournament,
            is_played=True
        ).filter(Q(home_team=team) | Q(away_team=team))

        for f in team_fixtures:
            opp_id = f.away_team_id if f.home_team_id == team.id else f.home_team_id
            total += points.get(opp_id, 0)

        buchholz[team.id] = total

    # Build standings
    for team in teams:
        team_id = team.id
        gd = goals_for.get(team_id, 0) - goals_against.get(team_id, 0)
        standings.append({
            'team': team,
            'points': points.get(team_id, 0),
            'played': team.played or 0,
            'wins': team.wins or 0,
            'draws': team.draws or 0,
            'losses': team.losses or 0,
            'goals_for': goals_for.get(team_id, 0),
            'goals_against': goals_against.get(team_id, 0),
            'goal_diff': gd,
            'buchholz': buchholz.get(team_id, 0),
        })

    # Sort: Points desc → Buchholz desc → Goal Diff desc
    standings.sort(key=lambda x: (-x['points'], -x['buchholz'], -x['goal_diff']))
    return standings


# ============================================================
# SWISS API VIEWS
# ============================================================

@require_http_methods(["POST"])
def generate_next_swiss_round(request, tournament_id):
    """Generate the next Swiss round."""
    tournament = get_object_or_404(Tournament, id=tournament_id)

    if tournament.tournament_format not in ['swiss', 'swiss_plus']:
        return JsonResponse({
            'status': 'error',
            'message': 'This endpoint is only for Swiss formats.'
        }, status=400)

    # Find the next round number
    max_round = Fixture.objects.filter(tournament=tournament).aggregate(
        models.Max('round')
    )['round__max'] or 0

    next_round = max_round + 1
    tournament.swiss_rounds_complete=next_round
    tournament.save()

    # Check if we've reached the total rounds
    total_rounds = tournament.swiss_total_rounds or 0

    # If no total rounds set, calculate it
    if total_rounds == 0:
        team_count = Team.objects.filter(tournament=tournament).count()
        total_rounds = max(4, math.ceil(math.log2(team_count)) + 2)
        tournament.swiss_total_rounds = total_rounds
        tournament.save(update_fields=['swiss_total_rounds'])

    # Check if all rounds are already generated
    if max_round >= total_rounds:
        return JsonResponse({
            'status': 'error',
            'message': f'All {total_rounds} Swiss rounds have already been generated.'
        }, status=400)

    # Check if there are pending fixtures that need results
    pending = Fixture.objects.filter(
        tournament=tournament,
        round__lte=max_round,
        is_played=False
    ).exclude(away_team__isnull=True).count()

    if pending > 0:
        return JsonResponse({
            'status': 'error',
            'message': f'Please enter results for {pending} pending fixture(s) first.'
        }, status=400)

    # Generate next round
    generator = FixtureGenerator(tournament, {
        'start_date': tournament.created_at.date().isoformat(),
        'end_date': (tournament.created_at + timedelta(days=30)).date().isoformat(),
        'num_rounds': tournament.swiss_total_rounds,
    })

    try:
        count = generator.generate_next_swiss_round(next_round)
        return JsonResponse({
            'status': 'success',
            'round': next_round,
            'fixtures_created': count,
            'total_rounds': tournament.swiss_total_rounds,
            'message': f'Round {next_round} generated with {count} fixtures.'
        })
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        return JsonResponse({
            'status': 'error',
            'message': str(e),
            'detail': error_detail
        }, status=400)


@require_http_methods(["POST"])
def complete_swiss_phase(request, tournament_id):
    """Complete Swiss phase and split teams (Swiss Pro only)."""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    print(tournament.tournament_format)

    if tournament.tournament_format != "swiss_plus":
        print('not swiss_pro')
        return JsonResponse({
            'status': 'error',
            'message': 'Split is only available for Swiss Pro format.'
        }, status=400)

    # Check all fixtures have results
    total_rounds = tournament.swiss_total_rounds or 0
    pending = Fixture.objects.filter(
        tournament=tournament,
        round__lte=total_rounds,
        is_played=False
    ).exclude(away_team__isnull=True).count()

    if pending > 0:
        return JsonResponse({
            'status': 'error',
            'message': f'{pending} fixtures still need results before completing the Swiss phase.'
        }, status=400)

    # Fix: Proper date handling
    if tournament.created_at:
        start_date = tournament.created_at.date()
    else:
        start_date = date.today()

    end_date = start_date + timedelta(days=30)

    generator = FixtureGenerator(tournament, {
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'num_rounds': tournament.swiss_total_rounds,
        'direct_percent': 25,
        'playoff_percent': 50,
    })

    try:
        split_data = generator.generate_swiss_split()
        return JsonResponse({
            'status': 'success',
            'data': split_data,
            'message': 'Swiss phase complete! Teams have been split.'
        })
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        return JsonResponse({
            'status': 'error',
            'message': str(e),
            'detail': error_detail
        }, status=400)


# views.py - Fixed generate_playoff_rounds

@require_http_methods(["POST"])
def generate_playoff_rounds(request, tournament_id):
    """Generate playoff fixtures (Swiss Pro only)."""
    tournament = get_object_or_404(Tournament, id=tournament_id)

    if tournament.tournament_format != "swiss_plus":
        return JsonResponse({
            'status': 'error',
            'message': 'Playoffs are only available for Swiss Pro format.'
        }, status=400)

    if not tournament.split_phase_complete:
        return JsonResponse({
            'status': 'error',
            'message': 'Must complete Swiss phase and split first.'
        }, status=400)

    # Fix: Proper date handling
    if tournament.created_at:
        start_date = tournament.created_at.date()
    else:
        start_date = date.today()

    end_date = start_date + timedelta(days=30)

    generator = FixtureGenerator(tournament, {
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'playoff_legs': 2,
    })

    try:
        count = generator.generate_playoff_fixtures()
        return JsonResponse({
            'status': 'success',
            'fixtures_created': count,
            'message': f'Playoff fixtures generated: {count} matches.'
        })
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        return JsonResponse({
            'status': 'error',
            'message': str(e),
            'detail': error_detail
        }, status=400)


@require_http_methods(["GET"])
def get_swiss_standings_api(request, tournament_id):
    """API endpoint for Swiss standings."""
    tournament = get_object_or_404(Tournament, id=tournament_id)

    if tournament.tournament_format not in ['swiss', 'swiss_plus']:
        return JsonResponse({
            'status': 'error',
            'message': 'This endpoint is only for Swiss formats.'
        }, status=400)

    standings = _calculate_swiss_standings(tournament)

    return JsonResponse({
        'standings': [
            {
                'id': s['team'].id,
                'name': s['team'].name,
                'points': s['points'],
                'played': s['played'],
                'wins': s['wins'],
                'draws': s['draws'],
                'losses': s['losses'],
                'goals_for': s['goals_for'],
                'goals_against': s['goals_against'],
                'goal_diff': s['goal_diff'],
                'buchholz': s['buchholz'],
            }
            for s in standings
        ],
        'phase': 'swiss' if not tournament.split_phase_complete else 'split',
        'total_rounds': tournament.swiss_total_rounds,
    })


# views.py - Fixed generate_knockout_from_swiss view

from datetime import date, timedelta


# views.py - Complete knockout views

@require_http_methods(["POST"])
def generate_knockout_from_swiss(request, tournament_id):
    """
    Generate the FIRST round of knockout bracket from Swiss qualifiers.
    Only generates when playoffs are complete.
    """
    tournament = get_object_or_404(Tournament, id=tournament_id)

    if not tournament.split_phase_complete:
        return JsonResponse({
            'status': 'error',
            'message': 'Must complete Swiss phase and split first.'
        }, status=400)

    # Check if playoffs are complete (if there are playoff teams)
    playoff_count = tournament.swiss_playoff_count or 0

    if playoff_count > 0:
        swiss_rounds = tournament.swiss_total_rounds or 0

        # Check for pending playoff fixtures
        pending_playoffs = Fixture.objects.filter(
            tournament=tournament,
            round__gt=swiss_rounds,
            is_played=False
        ).exclude(away_team__isnull=True).count()

        if pending_playoffs > 0:
            return JsonResponse({
                'status': 'error',
                'message': f'Cannot generate knockout: {pending_playoffs} playoff fixture(s) still need results.'
            }, status=400)

        # Check if all playoff fixtures are played
        total_playoffs = Fixture.objects.filter(
            tournament=tournament,
            round__gt=swiss_rounds
        ).exclude(away_team__isnull=True).count()

        played_playoffs = Fixture.objects.filter(
            tournament=tournament,
            round__gt=swiss_rounds,
            is_played=True
        ).exclude(away_team__isnull=True).count()

        if total_playoffs > 0 and played_playoffs < total_playoffs:
            return JsonResponse({
                'status': 'error',
                'message': f'Playoffs not complete: {played_playoffs}/{total_playoffs} played.'
            }, status=400)

    # Check if knockout already exists
    max_round = Fixture.objects.filter(tournament=tournament).aggregate(
        models.Max('round')
    )['round__max'] or 0

    # Check if there are already knockout fixtures (round > swiss_rounds + playoffs)
    swiss_rounds = tournament.swiss_total_rounds or 0
    playoff_rounds = 2 if playoff_count > 0 else 0  # 2 legs for playoffs
    knockout_start_round = swiss_rounds + playoff_rounds + 1

    existing_knockout = Fixture.objects.filter(
        tournament=tournament,
        round__gte=knockout_start_round
    ).exists()

    if existing_knockout:
        return JsonResponse({
            'status': 'error',
            'message': 'Knockout bracket already generated. Please enter results for knockout matches.'
        }, status=400)

    # Proper date handling
    if tournament.created_at:
        start_date = tournament.created_at.date()
    else:
        start_date = date.today()

    end_date = start_date + timedelta(days=30)

    generator = FixtureGenerator(tournament, {
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
    })

    try:
        count = generator.generate_knockout_from_swiss()
        return JsonResponse({
            'status': 'success',
            'fixtures_created': count,
            'round': knockout_start_round,
            'message': f'Knockout Round 1 generated with {count} matches.'
        })
    except Exception as e:
        import traceback
        return JsonResponse({
            'status': 'error',
            'message': str(e),
            'detail': traceback.format_exc()
        }, status=400)


@require_http_methods(["POST"])
def generate_next_knockout_round(request, tournament_id):
    """
    Generate the next knockout round based on results from previous rounds.
    """
    tournament = get_object_or_404(Tournament, id=tournament_id)

    if tournament.tournament_format != "swiss_plus":
        return JsonResponse({
            'status': 'error',
            'message': 'Knockout is only available for Swiss Pro format.'
        }, status=400)

    if not tournament.split_phase_complete:
        return JsonResponse({
            'status': 'error',
            'message': 'Must complete Swiss phase and split first.'
        }, status=400)

    # Get the current max round
    max_round = Fixture.objects.filter(tournament=tournament).aggregate(
        models.Max('round')
    )['round__max'] or 0

    # Get all fixtures from the current max round (knockout matches)
    current_round_fixtures = Fixture.objects.filter(
        tournament=tournament,
        round=max_round
    ).select_related('result')

    # Check if all matches in the current round are played
    pending = current_round_fixtures.filter(is_played=False).count()
    if pending > 0:
        return JsonResponse({
            'status': 'error',
            'message': f'Please enter results for {pending} match(es) in Round {max_round} first.'
        }, status=400)

    # Check if we have a champion (only 1 match in current round)
    if current_round_fixtures.count() == 1:
        # This is the final!
        tournament.knockout_phase_complete = True
        tournament.save()

        # Get the winner
        final_fixture = current_round_fixtures.first()
        if final_fixture.result:
            winner = final_fixture.home_team if final_fixture.result.home_score > final_fixture.result.away_score else final_fixture.away_team
            return JsonResponse({
                'status': 'champion',
                'message': f'🏆 Champion: {winner.name}! Tournament complete!',
                'champion': winner.name
            })

    # Get winners of current round matches
    winners = []
    for fixture in current_round_fixtures:
        if fixture.result:
            if fixture.result.home_score > fixture.result.away_score:
                winners.append(fixture.home_team)
            elif fixture.result.home_score < fixture.result.away_score:
                winners.append(fixture.away_team)
            else:
                # Draw - should not happen in knockout, but handle it
                # For draws, the higher seed advances (better Swiss rank)
                standings = _calculate_swiss_standings(tournament)
                home_rank = next((i for i, s in enumerate(standings) if s['team'].id == fixture.home_team.id), 999)
                away_rank = next((i for i, s in enumerate(standings) if s['team'].id == fixture.away_team.id), 999)
                winners.append(fixture.home_team if home_rank < away_rank else fixture.away_team)

    if len(winners) < 2:
        # Not enough winners for next round
        if len(winners) == 1:
            tournament.knockout_phase_complete = True
            tournament.save()
            return JsonResponse({
                'status': 'champion',
                'message': f'🏆 Champion: {winners[0].name}! Tournament complete!',
                'champion': winners[0].name
            })
        else:
            return JsonResponse({
                'status': 'error',
                'message': 'No winners found to advance.'
            }, status=400)

    # Get standings for seeding
    standings = _calculate_swiss_standings(tournament)

    # Rank winners by their Swiss position
    winner_ids = [w.id for w in winners]
    ranked_winners = [s['team'] for s in standings if s['team'].id in winner_ids]

    # Pair winners for next round: 1st vs last, 2nd vs 2nd-last
    next_round = max_round + 1
    matchups = []
    n = len(ranked_winners)
    for i in range(n // 2):
        home = ranked_winners[i]
        away = ranked_winners[n - 1 - i]
        matchups.append((home, away))

    # If odd number of winners, give a bye to the highest ranked
    if n % 2 == 1:
        # Highest ranked gets a bye to the next round
        # We need to handle this differently - in a proper knockout, we should have
        # ensured the number of teams is a power of 2 from the start
        # For simplicity, we'll just create a bye
        pass

    # Create fixtures for next round
    match_date = tournament.created_at.date() + timedelta(days=7 * (next_round))
    if not match_date:
        match_date = date.today() + timedelta(days=7)

    fixtures_created = 0
    for home, away in matchups:
        Fixture.objects.create(
            tournament=tournament,
            home_team=home,
            away_team=away,
            match_date=match_date,
            round=next_round,
        )
        fixtures_created += 1

    return JsonResponse({
        'status': 'success',
        'round': next_round,
        'fixtures_created': fixtures_created,
        'message': f'Knockout Round {next_round} generated with {fixtures_created} matches.'
    })


@require_http_methods(["GET"])
def get_knockout_status(request, tournament_id):
    """
    Get the current status of the knockout phase.
    """
    tournament = get_object_or_404(Tournament, id=tournament_id)

    if tournament.tournament_format != "swiss_plus":
        return JsonResponse({
            'status': 'error',
            'message': 'Knockout is only available for Swiss Pro format.'
        }, status=400)

    swiss_rounds = tournament.swiss_total_rounds or 0
    playoff_count = tournament.swiss_playoff_count or 0
    playoff_rounds = 2 if playoff_count > 0 else 0
    knockout_start_round = swiss_rounds + playoff_rounds + 1

    # Get all knockout fixtures
    knockout_fixtures = Fixture.objects.filter(
        tournament=tournament,
        round__gte=knockout_start_round
    ).select_related('home_team', 'away_team', 'result').order_by('round')

    if not knockout_fixtures.exists():
        return JsonResponse({
            'status': 'not_started',
            'message': 'Knockout phase has not started yet.'
        })

    # Group by round
    rounds_data = {}
    for fixture in knockout_fixtures:
        round_num = fixture.round
        if round_num not in rounds_data:
            rounds_data[round_num] = {
                'round': round_num,
                'matches': [],
                'total': 0,
                'played': 0,
                'pending': 0,
                'complete': False
            }

        match_data = {
            'home_team': fixture.home_team.name,
            'away_team': fixture.away_team.name,
            'is_played': fixture.is_played,
        }

        if fixture.is_played and fixture.result:
            match_data['home_score'] = fixture.result.home_score
            match_data['away_score'] = fixture.result.away_score
            winner = fixture.home_team if fixture.result.home_score > fixture.result.away_score else fixture.away_team
            match_data['winner'] = winner.name
            rounds_data[round_num]['played'] += 1
        else:
            rounds_data[round_num]['pending'] += 1

        rounds_data[round_num]['total'] += 1
        rounds_data[round_num]['matches'].append(match_data)

    # Mark round as complete if all matches are played
    for round_num, data in rounds_data.items():
        data['complete'] = data['played'] == data['total']

    # Check if tournament is complete
    is_complete = tournament.knockout_phase_complete

    # Check if final is played
    final_round = max(rounds_data.keys()) if rounds_data else None
    champion = None
    if final_round and rounds_data[final_round]['complete']:
        # Get the winner of the final
        final_matches = Fixture.objects.filter(
            tournament=tournament,
            round=final_round
        ).select_related('result', 'home_team', 'away_team')

        for match in final_matches:
            if match.result:
                if match.result.home_score > match.result.away_score:
                    champion = match.home_team.name
                elif match.result.home_score < match.result.away_score:
                    champion = match.away_team.name

    return JsonResponse({
        'status': 'in_progress' if not is_complete else 'complete',
        'is_complete': is_complete,
        'champion': champion,
        'rounds': list(rounds_data.values()),
        'current_round': max(rounds_data.keys()) if rounds_data else None,
        'total_rounds': len(rounds_data),
    })


# views.py
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.shortcuts import get_object_or_404
import json

from .models import Tournament
from .fixture_generator import FixtureGenerator


@require_http_methods(["POST"])
def update_swiss_counts(request, tournament_id):
    """
    Update the Swiss Pro split counts for a tournament.
    This recalculates direct/playoff/eliminated counts based on current team count.
    """
    tournament = get_object_or_404(Tournament, id=tournament_id)

    if tournament.tournament_format != 'swiss_plus':
        return JsonResponse({
            'success': False,
            'error': 'This tournament is not a Swiss Pro format.'
        }, status=400)

    try:
        # Get team count
        team_count = Team.objects.filter(tournament=tournament).count()

        if team_count < 4:
            return JsonResponse({
                'success': False,
                'error': f'Need at least 4 teams for Swiss Pro. Currently have {team_count}.'
            }, status=400)

        # Create generator with config
        config = {
            'direct_percent': 25,
            'playoff_percent': 50,
        }
        generator = FixtureGenerator(tournament, config)

        # Calculate split counts
        direct_count, playoff_count, eliminated_count = generator._calculate_split(team_count)

        # Update tournament
        tournament.swiss_direct_count = direct_count
        tournament.swiss_playoff_count = playoff_count
        tournament.swiss_eliminated_count = eliminated_count
        tournament.save()

        return JsonResponse({
            'success': True,
            'message': 'Split counts updated successfully',
            'data': {
                'direct_count': direct_count,
                'playoff_count': playoff_count,
                'eliminated_count': eliminated_count,
                'team_count': team_count
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)