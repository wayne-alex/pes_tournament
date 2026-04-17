from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.db.models import F, Sum, ExpressionWrapper, IntegerField
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt

from .fixture_generator import FixtureGenerator
from .models import Tournament, Team, Fixture, Group, Result
from .standings import StandingsService


def dashboard(request, tournament_id):
    tournament = Tournament.objects.get(id=tournament_id)

    groups = Group.objects.filter(tournament=tournament).prefetch_related("teams")

    group_tables = []

    for group in groups:
        teams = group.teams.annotate(
            goal_difference=F('goals_for') - F('goals_against')
        ).order_by('-points', '-goal_difference', '-goals_for')

        group_tables.append({
            "group": group,
            "teams": teams
        })

    # 🔥 ADD THIS: FIXTURES
    fixtures = Fixture.objects.filter(
        tournament=tournament,
        is_played=False
    ).select_related("home_team", "away_team", "group").order_by("match_date")

    # 🔥 ADD THIS: RESULTS
    results = Result.objects.filter(
        fixture__tournament=tournament
    ).select_related("fixture", "fixture__home_team", "fixture__away_team")

    # 🔥 OPTIONAL: BRACKET PLACEHOLDER (since you haven't built knockout rounds storage yet)
    rounds = []
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

    return render(request, "dashboard.html", {
        "tournament": tournament,
        "group_tables": group_tables,
        "fixtures": fixtures,
        "results": results,
        "rounds": rounds,
        "top_scorers": top_scorers,
    })


@csrf_exempt
def admin_login(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return JsonResponse({"success": True})

        return JsonResponse({"success": False, "message": "Invalid credentials"})

    return render(request, "admin_login.html")


@login_required
def admin_dashboard(request):
    total_tournaments = Tournament.objects.all().count()
    total_teams = Team.objects.all().count()
    total_fixtures = Fixture.objects.all().count()
    total_results = Result.objects.all().count()
    return render(request, 'admin_dashboard.html',
                  {'total_tournaments': total_tournaments, 'total_teams': total_teams, 'total_fixtures': total_fixtures,
                   'total_results': total_results})


@login_required
def admin_tournament(request):
    if request.method == "POST":
        Tournament.objects.create(
            name=request.POST.get("name"),
            tournament_format=request.POST.get("tournament_format"),
            mode=request.POST.get("mode")
        )
        return redirect("tournament_create")

    tournaments = Tournament.objects.all().order_by("-id")

    return render(request, "tournament_create.html", {
        "tournaments": tournaments
    })


@login_required
def tournament_edit(request, id):
    tournament = get_object_or_404(Tournament, id=id)

    if request.method == "POST":
        tournament.name = request.POST.get("name")
        tournament.tournament_format = request.POST.get("tournament_format")
        tournament.mode = request.POST.get("mode")
        tournament.save()

        return redirect("tournament_create")

    return render(request, "tournament/edit.html", {
        "tournament": tournament
    })


@login_required
def tournament_delete(request, id):
    tournament = get_object_or_404(Tournament, id=id)
    tournament.delete()
    return redirect("tournament_create")


@login_required
def admin_teams(request):
    if request.method == "POST":
        name = request.POST.get("name")
        tournament_id = request.POST.get("tournament_id")

        if name and tournament_id:
            tournament = Tournament.objects.get(id=tournament_id)
            Team.objects.create(name=name, tournament=tournament)
            return redirect("teams")

    teams = Team.objects.all().order_by("-id")
    tournaments = Tournament.objects.all().order_by("-id")

    return render(request, "teams.html", {"teams": teams, "tournaments": tournaments})


@login_required
def team_edit(request, id):
    team = get_object_or_404(Team, id=id)
    tournaments = Tournament.objects.all().order_by("-id")

    if request.method == "POST":
        team.name = request.POST.get("name")
        team.save()
        return redirect("teams")

    return render(request, "edit_team.html", {"team": team, "tournaments": tournaments})


@login_required
def team_delete(request, id):
    team = get_object_or_404(Team, id=id)
    team.delete()
    return redirect("teams")


@login_required
def admin_fixtures(request, tournament_id):
    tournament = get_object_or_404(Tournament, id=tournament_id)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "update_score":
            fixture_id = request.POST.get("fixture_id")
            home_score = int(request.POST.get("home_score", 0))
            away_score = int(request.POST.get("away_score", 0))

            fixture = get_object_or_404(Fixture, id=fixture_id, tournament=tournament)

            # Create or update the Result
            result, created = Result.objects.update_or_create(
                fixture=fixture,
                defaults={
                    "home_score": home_score,
                    "away_score": away_score,
                }
            )
            fixture.is_played = True
            fixture.save()
            StandingsService.calculate(tournament)

            messages.success(request, "Score updated successfully.")
            return redirect("fixtures", tournament_id=tournament_id)
        config = {
            "start_date": request.POST.get("start_date"),
            "end_date": request.POST.get("end_date"),
            "games_per_day": request.POST.get("games_per_day", 2),
            "groups": request.POST.get("groups", 2),
            "teams_per_group": request.POST.get("teams_per_group"),
            "qualify_per_group": request.POST.get("qualify_per_group", 2),
        }

        try:
            generator = FixtureGenerator(tournament, config)
            generator.generate()
            messages.success(request, "Fixtures generated successfully.")
        except ValueError as e:
            messages.error(request, str(e))

        return redirect("fixtures", tournament_id=tournament_id)

    fixtures = Fixture.objects.filter(
        tournament=tournament
    ).select_related(
        "home_team", "away_team", "tournament", "result"
    ).order_by("match_date")

    return render(request, "fixtures.html", {
        "tournament": tournament,
        "fixtures": fixtures
    })


@login_required
def fixture_delete(request, id):
    fixture = get_object_or_404(Fixture, id=id)
    fixture.delete()
    return redirect("fixtures")


@login_required
def fixture_update(request, id):
    fixture = get_object_or_404(Fixture, id=id)

    if request.method == "POST":
        fixture.home_score = request.POST.get("home_score")
        fixture.away_score = request.POST.get("away_score")

        fixture.is_played = True
        fixture.save()

        return redirect("fixtures")

    return render(request, "fixtures_edit.html", {"fixture": fixture})


@login_required
def admin_results(request):
    fixtures = Fixture.objects.select_related(
        "home_team",
        "away_team",
        "tournament",
        "result"
    ).order_by("-is_played", "match_date")

    return render(request, "results.html", {
        "fixtures": fixtures
    })


@login_required
def generate_fixtures(request, tournament_id):
    tournament = Tournament.objects.get(id=tournament_id)

    config = {
        "format": request.POST.get("format"),
        "mode": request.POST.get("mode"),
        "start_date": request.POST.get("start_date"),
        "end_date": request.POST.get("end_date"),
        "groups": request.POST.get("groups"),
        "teams_per_group": request.POST.get("teams_per_group"),
        "qualify_per_group": request.POST.get("qualify_per_group"),
    }

    generator = FixtureGenerator(tournament, config)
    generator.generate()

    return redirect("fixtures")


def dashboard_home(request):
    tournaments = Tournament.objects.filter(is_open=True).order_by("-id")

    return render(request, "dashboard_home.html", {
        "tournaments": tournaments
    })


def tournament_live_data(request, tournament_id):
    tournament = get_object_or_404(Tournament, id=tournament_id)

    # ── FIXTURES (all, including played, with group name) ─────────────────────
    fixtures_qs = (
        Fixture.objects.filter(tournament=tournament)
        .select_related("home_team", "away_team", "result", "group")
        .order_by("match_date")
    )

    fixtures = []
    for f in fixtures_qs:
        fixtures.append({
            "id": f.id,
            "home_team__name": f.home_team.name,
            "away_team__name": f.away_team.name,
            "match_date": f.match_date.isoformat() if f.match_date else None,
            "is_played": f.is_played,
            "group_name": f.group.name if f.group else None,
            "result__home_score": f.result.home_score if hasattr(f, "result") and f.result else None,
            "result__away_score": f.result.away_score if hasattr(f, "result") and f.result else None,
        })

    # ── STANDINGS ordered by points ───────────────────────────────────────────
    standings = list(
        Team.objects.filter(tournament=tournament)
        .annotate(
            goal_difference=ExpressionWrapper(
                F('goals_for') - F('goals_against'),
                output_field=IntegerField()
            )
        )
        .values("id", "name", "points", "played", "wins", "draws", "losses",
                "goals_for", "goals_against", "goal_difference")
        .order_by("-points", "-goal_difference", "-goals_for")
    )

    # ── RESULTS ───────────────────────────────────────────────────────────────
    results_qs = (
        Result.objects.filter(fixture__tournament=tournament)
        .select_related("fixture", "fixture__home_team", "fixture__away_team", "fixture__group")
        .order_by("-fixture__match_date")
    )

    results = []
    for r in results_qs:
        results.append({
            "id": r.id,
            "home_team": r.fixture.home_team.name,
            "away_team": r.fixture.away_team.name,
            "home_score": r.home_score,
            "away_score": r.away_score,
            "match_date": r.fixture.match_date.isoformat() if r.fixture.match_date else None,
            "group_name": r.fixture.group.name if r.fixture.group else None,
        })

    # ── TOP SCORERS (teams by goals_for) ──────────────────────────────────────
    top_scorers = list(
        Team.objects.filter(tournament=tournament)
        .annotate(total_goals=Sum("goals_for"))
        .order_by("-total_goals")
        .values("id", "name", "total_goals")[:10]
    )

    return JsonResponse({
        "fixtures": fixtures,
        "standings": standings,
        "results": results,
        "top_scorers": top_scorers,
    })
