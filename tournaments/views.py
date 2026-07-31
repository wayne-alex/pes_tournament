import json
from datetime import date

from django.db.models import F, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import Fixture, Group, Result, Team, Tournament, Poll, PollVote


def dashboard(request, tournament_id):
    tournament = get_object_or_404(Tournament, id=tournament_id)

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

    # Ungrouped / league-wide standings (used when the tournament has no groups)
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


def tournament_live_api(request, tournament_id):
    """JSON endpoint for live dynamic updating."""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    teams = Team.objects.filter(tournament=tournament)
    fixtures = Fixture.objects.filter(tournament=tournament, is_played=False)
    results = Result.objects.filter(fixture__tournament=tournament).select_related(
        "fixture", "fixture__home_team", "fixture__away_team"
    ).order_by("-fixture__match_date")

    standings_data = [
        {
            "id": t.id,
            "name": t.name,
            "initials": t.initials,
            "played": t.played,
            "wins": t.wins,
            "draws": t.draws,
            "losses": t.losses,
            "goals_for": t.goals_for,
            "goals_against": t.goals_against,
            "points": t.points,
        }
        for t in teams
    ]
    fixtures_data = [
        {
            "id": f.id,
            "home_team__name": f.home_team.name,
            "away_team__name": f.away_team.name,
            "match_date": f.match_date.isoformat() if f.match_date else None,
            "is_played": f.is_played,
            "is_live": f.is_live,
        }
        for f in fixtures
    ]
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
        }

    return JsonResponse({
        "standings": standings_data,
        "fixtures": fixtures_data,
        "results": results_data,
        "live": live_data,
        "played_count": tournament.played_fixtures_count,
        "total_count": tournament.total_fixtures_count,
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