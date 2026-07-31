from django.contrib.auth import logout, authenticate, login
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.urls import reverse
from django.db.models import Count, Q
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.forms import ModelForm
from django.contrib.auth.forms import UserCreationForm

from tournaments.fixture_generator import FixtureGenerator
from tournaments.models import User, Tournament, Team, Fixture, Result
from .forms import UserForm, TournamentForm, TeamForm, FixtureForm


def is_superadmin(user):
    return user.is_authenticated and user.is_superadmin


from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render


@login_required
def admin_logout(request):
    """Log out the user with proper session cleanup"""
    if request.method == 'POST':
        # 1. Log the logout activity & add flash message
        if request.user.is_authenticated:
            logout(request)

        messages.success(request, 'You have been successfully logged out.')

        # 2. Prepare redirect response
        response = redirect('admin_login')

        # 3. Explicitly specify key when deleting cookies
        response.delete_cookie('remember_me')
        # If clearing standard Django session cookie manually:
        # response.delete_cookie('sessionid')

        return response

    # GET request - show logout confirmation
    return render(request, 'superadmin/logout.html')


def admin_login(request):
    """Custom login view with enhanced security"""
    if request.user.is_authenticated:
        return redirect('superadmin_dashboard')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            if user.is_active:
                login(request, user)

                # Check if user is superadmin
                if user.is_superadmin:
                    messages.success(request, f'Welcome back, {user.get_full_name() or user.username}!')
                else:
                    messages.info(request, 'You do not have permission to access the admin panel.')
                    logout(request)
                    return redirect('admin_login')

                next_url = request.GET.get('next')
                if next_url:
                    return redirect(next_url)
                return redirect('superadmin_dashboard')
            else:
                messages.error(request, 'Your account has been deactivated.')
        else:
            messages.error(request, 'Invalid username or password.')

    return render(request, 'superadmin/login.html')

@login_required
@user_passes_test(is_superadmin)
def superadmin_dashboard(request):
    context = {
        'total_users': User.objects.count(),
        'total_tournaments': Tournament.objects.count(),
        'total_teams': Team.objects.count(),
        'upcoming_fixtures': Fixture.objects.filter(is_played=False).count(),
        'total_fixtures': Fixture.objects.count(),
        'total_results': Result.objects.count(),
        'recent_activities': [],
    }
    return render(request, 'superadmin/dashboard.html', context)


# User Management Views
@login_required
@user_passes_test(is_superadmin)
def admin_user_list(request):
    users = User.objects.all().order_by('-date_joined')
    paginator = Paginator(users, 10)
    page = request.GET.get('page')
    users_page = paginator.get_page(page)

    context = {
        'users': users_page,
        'user_count': users.count(),
    }
    return render(request, 'superadmin/user_list.html', context)


@login_required
@user_passes_test(is_superadmin)
def admin_user_create(request):
    if request.method == 'POST':
        form = UserForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f'User {user.username} created successfully!')
            return redirect('admin_user_list')
    else:
        form = UserForm()

    return render(request, 'superadmin/user_form.html', {'form': form, 'title': 'Create User'})


@login_required
@user_passes_test(is_superadmin)
def admin_user_edit(request, user_id):
    user = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        form = UserForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, f'User {user.username} updated successfully!')
            return redirect('admin_user_list')
    else:
        form = UserForm(instance=user)

    return render(request, 'superadmin/user_form.html', {'form': form, 'title': 'Edit User'})


@login_required
@user_passes_test(is_superadmin)
def admin_user_delete(request, user_id):
    user = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        username = user.username
        user.delete()
        messages.success(request, f'User {username} deleted successfully!')
        return redirect('admin_user_list')

    return render(request, 'superadmin/user_delete.html', {'user': user})


# Tournament Management Views
@login_required
@user_passes_test(is_superadmin)
def admin_tournament_list(request):
    tournaments = Tournament.objects.all().order_by('-created_at')
    paginator = Paginator(tournaments, 10)
    page = request.GET.get('page')
    tournaments_page = paginator.get_page(page)

    context = {
        'tournaments': tournaments_page,
        'tournament_count': tournaments.count(),
    }
    return render(request, 'superadmin/tournaments_list.html', context)


@login_required
@user_passes_test(is_superadmin)
def admin_tournament_create(request):
    if request.method == 'POST':
        form = TournamentForm(request.POST)
        if form.is_valid():
            tournament = form.save()
            messages.success(request, f'Tournament {tournament.name} created successfully!')
            return redirect('admin_tournament_list')
    else:
        form = TournamentForm()

    return render(request, 'superadmin/tournaments_form.html', {'form': form, 'title': 'Create Tournament'})


@login_required
@user_passes_test(is_superadmin)
def admin_tournament_edit(request, tournament_id):
    tournament = get_object_or_404(Tournament, id=tournament_id)
    if request.method == 'POST':
        form = TournamentForm(request.POST, instance=tournament)
        if form.is_valid():
            form.save()
            messages.success(request, f'Tournament {tournament.name} updated successfully!')
            return redirect('admin_tournament_list')
    else:
        form = TournamentForm(instance=tournament)

    return render(request, 'superadmin/tournaments_form.html', {'form': form, 'title': 'Edit Tournament'})


@login_required
@user_passes_test(is_superadmin)
def admin_tournament_delete(request, tournament_id):
    tournament = get_object_or_404(Tournament, id=tournament_id)
    if request.method == 'POST':
        name = tournament.name
        tournament.delete()
        messages.success(request, f'Tournament {name} deleted successfully!')
        return redirect('admin_tournament_list')

    return render(request, 'superadmin/tournaments_delete.html', {'tournament': tournament})


# Team Management Views
@login_required
@user_passes_test(is_superadmin)
def admin_team_list(request):
    teams = Team.objects.all().select_related('tournament').order_by('tournament', 'name')

    # Filter by tournament if specified
    tournament_id = request.GET.get('tournament')
    if tournament_id:
        teams = teams.filter(tournament_id=tournament_id)

    paginator = Paginator(teams, 10)
    page = request.GET.get('page')
    teams_page = paginator.get_page(page)

    tournaments = Tournament.objects.all().order_by('name')

    context = {
        'teams': teams_page,
        'team_count': Team.objects.count(),
        'tournaments': tournaments,
        'selected_tournament': tournament_id,
    }
    return render(request, 'superadmin/teams_list.html', context)


@login_required
@user_passes_test(is_superadmin)
def admin_team_create(request):
    if request.method == 'POST':
        form = TeamForm(request.POST)
        if form.is_valid():
            team = form.save()
            messages.success(request, f'Team "{team.name}" created successfully!')
            return redirect('admin_team_list')
    else:
        form = TeamForm()

    return render(request, 'superadmin/teams_form.html', {
        'form': form,
        'title': 'Create Team',
        'action': 'Create'
    })


@login_required
@user_passes_test(is_superadmin)
def admin_team_edit(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    if request.method == 'POST':
        form = TeamForm(request.POST, instance=team)
        if form.is_valid():
            form.save()
            messages.success(request, f'Team "{team.name}" updated successfully!')
            return redirect('admin_team_list')
    else:
        form = TeamForm(instance=team)

    return render(request, 'superadmin/teams_form.html', {
        'form': form,
        'title': 'Edit Team',
        'action': 'Update',
        'team': team
    })


@login_required
@user_passes_test(is_superadmin)
def admin_team_delete(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    if request.method == 'POST':
        team_name = team.name
        team.delete()
        messages.success(request, f'Team "{team_name}" deleted successfully!')
        return redirect('admin_team_list')

    # Check if team has fixtures
    has_fixtures = Fixture.objects.filter(
        Q(home_team=team) | Q(away_team=team)
    ).exists()

    return render(request, 'superadmin/teams_delete.html', {
        'team': team,
        'has_fixtures': has_fixtures
    })


@login_required
@user_passes_test(is_superadmin)
def admin_team_bulk_create(request):
    if request.method == 'POST':
        tournament_id = request.POST.get('tournament')
        team_names = request.POST.get('team_names', '').strip()

        if not tournament_id or not team_names:
            messages.error(request, 'Please select a tournament and enter team names.')
            return redirect('admin_team_bulk_create')

        tournament = get_object_or_404(Tournament, id=tournament_id)
        names = [name.strip() for name in team_names.split('\n') if name.strip()]

        created_count = 0
        skipped_count = 0

        for name in names:
            # Check if team already exists in this tournament
            if Team.objects.filter(tournament=tournament, name__iexact=name).exists():
                skipped_count += 1
                continue

            Team.objects.create(
                tournament=tournament,
                name=name,
                player_name=request.POST.get('default_player_name', name)
            )
            created_count += 1

        messages.success(
            request,
            f'Successfully created {created_count} teams. Skipped {skipped_count} duplicates.'
        )
        return redirect('admin_team_list')

    tournaments = Tournament.objects.all().order_by('name')
    context = {
        'tournaments': tournaments,
        'title': 'Bulk Create Teams'
    }
    return render(request, 'superadmin/teamsbulk_create.html', context)


@login_required
@user_passes_test(is_superadmin)
def admin_team_stats(request, team_id):
    team = get_object_or_404(Team, id=team_id)

    # Get all fixtures for this team
    fixtures = Fixture.objects.filter(
        Q(home_team=team) | Q(away_team=team)
    ).select_related('result')

    total_fixtures = fixtures.count()
    played_fixtures = fixtures.filter(is_played=True).count()

    # Calculate stats from results
    wins = 0
    losses = 0
    draws = 0
    goals_for = 0
    goals_against = 0

    for fixture in fixtures.filter(is_played=True):
        if hasattr(fixture, 'result'):
            result = fixture.result
            if fixture.home_team == team:
                goals_for += result.home_score
                goals_against += result.away_score
                if result.home_score > result.away_score:
                    wins += 1
                elif result.home_score < result.away_score:
                    losses += 1
                else:
                    draws += 1
            else:  # away team
                goals_for += result.away_score
                goals_against += result.home_score
                if result.away_score > result.home_score:
                    wins += 1
                elif result.away_score < result.home_score:
                    losses += 1
                else:
                    draws += 1

    # Calculate recent form (last 5 matches)
    recent_fixtures = fixtures.filter(is_played=True).order_by('-match_date')[:5]
    recent_form = []
    for fixture in recent_fixtures:
        if hasattr(fixture, 'result'):
            result = fixture.result
            if fixture.home_team == team:
                if result.home_score > result.away_score:
                    recent_form.append('W')
                elif result.home_score < result.away_score:
                    recent_form.append('L')
                else:
                    recent_form.append('D')
            else:
                if result.away_score > result.home_score:
                    recent_form.append('W')
                elif result.away_score < result.home_score:
                    recent_form.append('L')
                else:
                    recent_form.append('D')

    context = {
        'team': team,
        'total_fixtures': total_fixtures,
        'played_fixtures': played_fixtures,
        'wins': wins,
        'losses': losses,
        'draws': draws,
        'goals_for': goals_for,
        'goals_against': goals_against,
        'goal_difference': goals_for - goals_against,
        'points': wins * 3 + draws,
        'recent_form': recent_form,
        'win_rate': round((wins / played_fixtures * 100) if played_fixtures > 0 else 0, 1),
        'fixtures': fixtures.order_by('-match_date')[:10],
    }
    return render(request, 'superadmin/teams_stats.html', context)


@login_required
@user_passes_test(is_superadmin)
def admin_team_export(request):
    """Export teams to CSV"""
    import csv
    from django.http import HttpResponse

    tournament_id = request.GET.get('tournament')
    teams = Team.objects.all().select_related('tournament')

    if tournament_id:
        teams = teams.filter(tournament_id=tournament_id)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="teams_export.csv"'

    writer = csv.writer(response)
    writer.writerow(
        ['Team Name', 'Player Name', 'Tournament', 'Points', 'Played', 'Wins', 'Draws', 'Losses', 'Goals For',
         'Goals Against'])

    for team in teams:
        writer.writerow([
            team.name,
            team.player_name,
            team.tournament.name,
            team.points,
            team.played,
            team.wins,
            team.draws,
            team.losses,
            team.goals_for,
            team.goals_against
        ])

    return response


@login_required
@user_passes_test(is_superadmin)
def admin_team_import(request):
    """Import teams from CSV"""
    if request.method == 'POST' and request.FILES.get('csv_file'):
        import csv
        import io

        csv_file = request.FILES['csv_file']
        tournament_id = request.POST.get('tournament')

        if not tournament_id:
            messages.error(request, 'Please select a tournament.')
            return redirect('admin_team_import')

        tournament = get_object_or_404(Tournament, id=tournament_id)

        # Read CSV
        decoded_file = csv_file.read().decode('utf-8')
        io_string = io.StringIO(decoded_file)
        reader = csv.reader(io_string)

        created_count = 0
        skipped_count = 0

        # Skip header if exists
        header = next(reader, None)
        is_header = header and 'Team Name' in header[0] if header else False

        for row in reader:
            if not row or not row[0].strip():
                continue

            team_name = row[0].strip()
            player_name = row[1].strip() if len(row) > 1 and row[1].strip() else team_name

            # Check for duplicates
            if Team.objects.filter(tournament=tournament, name__iexact=team_name).exists():
                skipped_count += 1
                continue

            Team.objects.create(
                tournament=tournament,
                name=team_name,
                player_name=player_name
            )
            created_count += 1

        messages.success(
            request,
            f'Successfully imported {created_count} teams. Skipped {skipped_count} duplicates.'
        )
        return redirect('admin_team_list')

    tournaments = Tournament.objects.all().order_by('name')
    return render(request, 'superadmin/teams_import.html', {'tournaments': tournaments})


# Fixture Management Views
@login_required
@user_passes_test(is_superadmin)
def admin_fixture_list(request):
    fixtures = Fixture.objects.all().select_related(
        'tournament', 'home_team', 'away_team', 'group'
    ).order_by('-match_date', 'round')

    # Filters
    tournament_id = request.GET.get('tournament')
    if tournament_id:
        fixtures = fixtures.filter(tournament_id=tournament_id)

    round_num = request.GET.get('round')
    if round_num:
        fixtures = fixtures.filter(round=round_num)

    status = request.GET.get('status')
    if status == 'played':
        fixtures = fixtures.filter(is_played=True)
    elif status == 'upcoming':
        fixtures = fixtures.filter(is_played=False)

    paginator = Paginator(fixtures, 20)
    page = request.GET.get('page')
    fixtures_page = paginator.get_page(page)

    tournaments = Tournament.objects.all().order_by('name')
    rounds = fixtures.values_list('round', flat=True).distinct().order_by('round')

    context = {
        'fixtures': fixtures_page,
        'fixture_count': Fixture.objects.count(),
        'tournaments': tournaments,
        'rounds': rounds,
        'selected_tournament': tournament_id,
        'selected_round': round_num,
        'selected_status': status,
    }
    return render(request, 'superadmin/fixtures_list.html', context)


@login_required
@user_passes_test(is_superadmin)
def admin_fixture_create(request):
    if request.method == 'POST':
        form = FixtureForm(request.POST)
        if form.is_valid():
            fixture = form.save()
            messages.success(request, f'Fixture created: {fixture.home_team} vs {fixture.away_team}')
            return redirect('admin_fixture_list')
    else:
        form = FixtureForm()

    return render(request, 'superadmin/fixtures_form.html', {
        'form': form,
        'title': 'Create Fixture',
        'action': 'Create'
    })


@login_required
@user_passes_test(is_superadmin)
def admin_fixture_edit(request, fixture_id):
    fixture = get_object_or_404(Fixture, id=fixture_id)
    if request.method == 'POST':
        form = FixtureForm(request.POST, instance=fixture)
        if form.is_valid():
            form.save()
            messages.success(request, f'Fixture updated: {fixture.home_team} vs {fixture.away_team}')
            return redirect('admin_fixture_list')
    else:
        form = FixtureForm(instance=fixture)

    return render(request, 'superadmin/fixtures_form.html', {
        'form': form,
        'title': 'Edit Fixture',
        'action': 'Update',
        'fixture': fixture
    })


@login_required
@user_passes_test(is_superadmin)
def admin_fixture_delete(request, fixture_id):
    fixture = get_object_or_404(Fixture, id=fixture_id)
    if request.method == 'POST':
        fixture_name = str(fixture)
        fixture.delete()
        messages.success(request, f'Fixture "{fixture_name}" deleted successfully!')
        return redirect('admin_fixture_list')

    return render(request, 'superadmin/fixtures_delete.html', {'fixture': fixture})


@login_required
@user_passes_test(is_superadmin)
def admin_fixture_generate(request):
    if request.method == 'POST':
        tournament_id = request.POST.get('tournament')
        format_type = request.POST.get('format_type')

        if not tournament_id:
            messages.error(request, 'Please select a tournament.')
            return redirect('admin_fixture_generate')

        tournament = get_object_or_404(Tournament, id=tournament_id)

        # Check if teams exist
        team_count = Team.objects.filter(tournament=tournament).count()
        if team_count < 2:
            messages.error(request, 'Tournament needs at least 2 teams to generate fixtures.')
            return redirect('admin_fixture_generate')

        try:
            # Prepare config based on tournament format
            config = {
                'start_date': request.POST.get('start_date'),
                'end_date': request.POST.get('end_date'),
                'groups': request.POST.get('groups', 2),
                'qualify_per_group': request.POST.get('qualify_per_group', 2),
                'num_rounds': request.POST.get('num_rounds'),
            }

            # Validate dates
            if not config['start_date'] or not config['end_date']:
                messages.error(request, 'Please provide start and end dates.')
                return redirect('admin_fixture_generate')

            # Generate fixtures
            generator = FixtureGenerator(tournament, config)
            generator.generate()

            # For Swiss format, set total rounds
            if tournament.tournament_format == 'swiss':
                total_rounds = generator._recommended_swiss_rounds(team_count)
                tournament.swiss_total_rounds = total_rounds
                tournament.save()

            fixture_count = Fixture.objects.filter(tournament=tournament).count()
            messages.success(
                request,
                f'Successfully generated {fixture_count} fixtures for {tournament.name}!'
            )

            # For Swiss, show message about next round generation
            if tournament.tournament_format == 'swiss':
                messages.info(
                    request,
                    f'Swiss format: Round 1 generated. Use "Generate Next Round" after results are entered.'
                )

            return redirect('admin_fixture_list')

        except Exception as e:
            messages.error(request, f'Error generating fixtures: {str(e)}')
            return redirect('admin_fixture_generate')

    tournaments = Tournament.objects.all().order_by('name')
    return render(request, 'superadmin/fixtures_generate.html', {'tournaments': tournaments})


@login_required
@user_passes_test(is_superadmin)
def admin_fixture_next_round(request):
    if request.method == 'POST':
        tournament_id = request.POST.get('tournament')
        if not tournament_id:
            messages.error(request, 'Please select a tournament.')
            return redirect('admin_fixture_next_round')

        tournament = get_object_or_404(Tournament, id=tournament_id)

        if tournament.tournament_format != 'swiss':
            messages.error(request, 'Next round generation is only available for Swiss format tournaments.')
            return redirect('admin_fixture_next_round')

        # Get current round number
        current_round = Fixture.objects.filter(tournament=tournament).values_list('round', flat=True).distinct().count()
        next_round = current_round + 1

        # Check if all fixtures in current round are played
        pending_fixtures = Fixture.objects.filter(
            tournament=tournament,
            round=current_round,
            is_played=False
        ).exclude(away_team__isnull=True)  # Exclude byes

        if pending_fixtures.exists():
            messages.warning(
                request,
                f'Round {current_round} still has {pending_fixtures.count()} unplayed fixtures. '
                'Please enter results before generating the next round.'
            )
            return redirect('admin_fixture_list')

        try:
            generator = FixtureGenerator(tournament, {})
            generator.generate_next_swiss_round(next_round)
            messages.success(request, f'Round {next_round} generated successfully!')
        except Exception as e:
            messages.error(request, f'Error generating next round: {str(e)}')

        return redirect('admin_fixture_list')

    tournaments = Tournament.objects.filter(tournament_format='swiss').order_by('name')
    return render(request, 'superadmin/fixtures_next_round.html', {'tournaments': tournaments})


@login_required
@user_passes_test(is_superadmin)
def admin_fixture_delete_all(request):
    if request.method == 'POST':
        tournament_id = request.POST.get('tournament')
        if not tournament_id:
            messages.error(request, 'Please select a tournament.')
            return redirect('admin_fixture_delete_all')

        tournament = get_object_or_404(Tournament, id=tournament_id)

        # Check if fixtures are played
        played_fixtures = Fixture.objects.filter(tournament=tournament, is_played=True)
        if played_fixtures.exists():
            messages.warning(
                request,
                f'Warning: {played_fixtures.count()} fixtures are already played. '
                'Deleting them will also delete their results.'
            )

        count = Fixture.objects.filter(tournament=tournament).delete()
        messages.success(request, f'Deleted {count[0]} fixtures from {tournament.name}.')
        return redirect('admin_fixture_list')

    tournaments = Tournament.objects.all().order_by('name')
    return render(request, 'superadmin/fixtures_delete_all.html', {'tournaments': tournaments})


@login_required
@user_passes_test(is_superadmin)
def admin_fixture_schedule_edit(request):
    """Edit the schedule of multiple fixtures at once"""
    if request.method == 'POST':
        tournament_id = request.POST.get('tournament')
        date_offset = request.POST.get('date_offset')
        time_offset = request.POST.get('time_offset')
        action = request.POST.get('action')

        if not tournament_id:
            messages.error(request, 'Please select a tournament.')
            return redirect('admin_fixture_schedule_edit')

        tournament = get_object_or_404(Tournament, id=tournament_id)
        fixtures = Fixture.objects.filter(tournament=tournament, is_played=False)

        if action == 'shift_dates':
            if not date_offset:
                messages.error(request, 'Please specify date offset in days.')
                return redirect('admin_fixture_schedule_edit')

            try:
                offset = int(date_offset)
                for fixture in fixtures:
                    if fixture.match_date:
                        from datetime import timedelta
                        fixture.match_date = fixture.match_date + timedelta(days=offset)
                        fixture.save()
                messages.success(request, f'Updated {fixtures.count()} fixtures by {offset} days.')
            except ValueError:
                messages.error(request, 'Invalid date offset. Please enter a number.')

        elif action == 'shift_time':
            if not time_offset:
                messages.error(request, 'Please specify time offset in hours.')
                return redirect('admin_fixture_schedule_edit')

            try:
                offset = int(time_offset)
                from datetime import timedelta
                for fixture in fixtures:
                    if fixture.match_date:
                        fixture.match_date = fixture.match_date + timedelta(hours=offset)
                        fixture.save()
                messages.success(request, f'Updated {fixtures.count()} fixtures by {offset} hours.')
            except ValueError:
                messages.error(request, 'Invalid time offset. Please enter a number.')

        elif action == 'set_date':
            new_date = request.POST.get('new_date')
            if not new_date:
                messages.error(request, 'Please select a new date.')
                return redirect('admin_fixture_schedule_edit')

            try:
                from datetime import datetime
                new_datetime = datetime.strptime(new_date, '%Y-%m-%dT%H:%M')
                for fixture in fixtures:
                    fixture.match_date = new_datetime
                    fixture.save()
                messages.success(request, f'Updated {fixtures.count()} fixtures to {new_date}.')
            except ValueError:
                messages.error(request, 'Invalid date format.')

        return redirect('admin_fixture_list')

    tournaments = Tournament.objects.all().order_by('name')
    return render(request, 'superadmin/fixture_schedule_edit.html', {'tournaments': tournaments})


@login_required
@user_passes_test(is_superadmin)
def admin_fixture_quick_edit(request):
    """AJAX endpoint for quick fixture edits"""
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        fixture_id = request.POST.get('fixture_id')
        field = request.POST.get('field')
        value = request.POST.get('value')

        try:
            fixture = Fixture.objects.get(id=fixture_id)

            if field == 'match_date':
                from datetime import datetime
                fixture.match_date = datetime.strptime(value, '%Y-%m-%dT%H:%M')
            elif field == 'round':
                fixture.round = int(value)
            elif field == 'home_score':
                # Update result if exists
                if hasattr(fixture, 'result'):
                    fixture.result.home_score = int(value)
                    fixture.result.save()
                else:
                    return JsonResponse({'success': False, 'error': 'Result not found for this fixture'})
            elif field == 'away_score':
                if hasattr(fixture, 'result'):
                    fixture.result.away_score = int(value)
                    fixture.result.save()
                else:
                    return JsonResponse({'success': False, 'error': 'Result not found for this fixture'})
            elif field == 'is_played':
                fixture.is_played = value.lower() == 'true'

            fixture.save()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Invalid request'})



def update_team_stats(fixture):
    """Update team statistics after a result is saved"""
    if not fixture.is_played or not hasattr(fixture, 'result'):
        return

    result = fixture.result
    home = fixture.home_team
    away = fixture.away_team

    # Update home team stats
    home.played += 1
    home.goals_for += result.home_score
    home.goals_against += result.away_score

    if result.home_score > result.away_score:
        home.wins += 1
        home.points += 3
    elif result.home_score < result.away_score:
        home.losses += 1
    else:
        home.draws += 1
        home.points += 1

    # Update away team stats
    away.played += 1
    away.goals_for += result.away_score
    away.goals_against += result.home_score

    if result.away_score > result.home_score:
        away.wins += 1
        away.points += 3
    elif result.away_score < result.home_score:
        away.losses += 1
    else:
        away.draws += 1
        away.points += 1

    home.save()
    away.save()


# Results Management Views
@login_required
@user_passes_test(is_superadmin)
def admin_result_list(request):
    results = Result.objects.all().select_related(
        'fixture', 'fixture__tournament', 'fixture__home_team', 'fixture__away_team'
    ).order_by('-updated_at', '-fixture__match_date')

    # Filters
    tournament_id = request.GET.get('tournament')
    if tournament_id:
        results = results.filter(fixture__tournament_id=tournament_id)

    team_id = request.GET.get('team')
    if team_id:
        results = results.filter(
            Q(fixture__home_team_id=team_id) | Q(fixture__away_team_id=team_id)
        )

    date_from = request.GET.get('date_from')
    if date_from:
        results = results.filter(fixture__match_date__date__gte=date_from)

    date_to = request.GET.get('date_to')
    if date_to:
        results = results.filter(fixture__match_date__date__lte=date_to)

    paginator = Paginator(results, 20)
    page = request.GET.get('page')
    results_page = paginator.get_page(page)

    tournaments = Tournament.objects.all().order_by('name')
    teams = Team.objects.all().order_by('name')

    context = {
        'results': results_page,
        'result_count': Result.objects.count(),
        'tournaments': tournaments,
        'teams': teams,
        'selected_tournament': tournament_id,
        'selected_team': team_id,
        'date_from': date_from,
        'date_to': date_to,
    }
    return render(request, 'superadmin/results_list.html', context)


@login_required
@user_passes_test(is_superadmin)
def admin_result_enter(request, fixture_id=None):
    if fixture_id:
        fixture = get_object_or_404(Fixture, id=fixture_id)

        if fixture.away_team is None:
            messages.error(request, 'Cannot enter result for a bye fixture.')
            return redirect('admin_fixture_list')

        # Get or create result
        result, created = Result.objects.get_or_create(fixture=fixture)

        if request.method == 'POST':
            home_score = request.POST.get('home_score')
            away_score = request.POST.get('away_score')
            is_played = request.POST.get('is_played') == 'on'

            if home_score is not None and away_score is not None:
                try:
                    home_score = int(home_score)
                    away_score = int(away_score)

                    if home_score < 0 or away_score < 0:
                        messages.error(request, 'Scores cannot be negative.')
                        return render(request, 'superadmin/results_enter.html', {
                            'fixture': fixture,
                            'result': result,
                        })

                    result.home_score = home_score
                    result.away_score = away_score
                    result.save()

                    # Update fixture status
                    fixture.is_played = is_played
                    fixture.save()

                    # Update team stats
                    update_team_stats(fixture)

                    messages.success(
                        request,
                        f'Result saved: {fixture.home_team} {home_score} - {away_score} {fixture.away_team}'
                    )
                    return redirect('admin_result_list')
                except ValueError:
                    messages.error(request, 'Please enter valid numbers for scores.')

        context = {
            'fixture': fixture,
            'result': result,
        }
        return render(request, 'superadmin/results_enter.html', context)

    # Show fixture selection for result entry
    if request.method == 'POST':
        fixture_id = request.POST.get('fixture_id')
        if fixture_id:
            return redirect('admin_result_enter', fixture_id=fixture_id)
        messages.error(request, 'Please select a fixture.')

    upcoming_fixtures = Fixture.objects.filter(
        is_played=False
    ).exclude(away_team__isnull=True).select_related(
        'tournament', 'home_team', 'away_team'
    ).order_by('match_date', 'tournament')

    context = {
        'fixtures': upcoming_fixtures,
    }
    return render(request, 'superadmin/results_select_fixture.html', context)


@login_required
@user_passes_test(is_superadmin)
def admin_result_edit(request, result_id):
    result = get_object_or_404(Result, id=result_id)
    fixture = result.fixture

    if request.method == 'POST':
        home_score = request.POST.get('home_score')
        away_score = request.POST.get('away_score')

        if home_score is not None and away_score is not None:
            try:
                old_home = result.home_score
                old_away = result.away_score

                result.home_score = int(home_score)
                result.away_score = int(away_score)
                result.save()

                # Recalculate team stats
                recalculate_team_stats(fixture, old_home, old_away)

                messages.success(request, 'Result updated successfully!')
                return redirect('admin_result_list')
            except ValueError:
                messages.error(request, 'Please enter valid numbers for scores.')

    context = {
        'result': result,
        'fixture': fixture,
    }
    return render(request, 'superadmin/results_edit.html', context)


@login_required
@user_passes_test(is_superadmin)
def admin_result_delete(request, result_id):
    result = get_object_or_404(Result, id=result_id)
    fixture = result.fixture

    if request.method == 'POST':
        # Remove result and update stats
        fixture.is_played = False
        fixture.save()

        # Revert team stats
        revert_team_stats(fixture)

        result.delete()
        messages.success(request, 'Result deleted successfully!')
        return redirect('admin_result_list')

    context = {
        'result': result,
        'fixture': fixture,
    }
    return render(request, 'superadmin/results_delete.html', context)


@login_required
@user_passes_test(is_superadmin)
def admin_result_batch_enter(request):
    """Batch enter results for multiple fixtures"""
    if request.method == 'POST':
        tournament_id = request.POST.get('tournament')
        round_num = request.POST.get('round')

        if not tournament_id:
            messages.error(request, 'Please select a tournament.')
            return redirect('admin_result_batch_enter')

        tournament = get_object_or_404(Tournament, id=tournament_id)
        fixtures = Fixture.objects.filter(
            tournament=tournament,
            is_played=False
        ).exclude(away_team__isnull=True)

        if round_num:
            fixtures = fixtures.filter(round=round_num)

        if not fixtures.exists():
            messages.warning(request, 'No unplayed fixtures found for this tournament.')
            return redirect('admin_result_batch_enter')

        # Process results
        results_entered = 0
        for fixture in fixtures:
            home_score = request.POST.get(f'home_score_{fixture.id}')
            away_score = request.POST.get(f'away_score_{fixture.id}')

            if home_score is not None and away_score is not None:
                try:
                    home_score = int(home_score)
                    away_score = int(away_score)

                    if home_score >= 0 and away_score >= 0:
                        result, created = Result.objects.get_or_create(fixture=fixture)
                        result.home_score = home_score
                        result.away_score = away_score
                        result.save()

                        fixture.is_played = True
                        fixture.save()

                        update_team_stats(fixture)
                        results_entered += 1
                except ValueError:
                    continue

        messages.success(request, f'Successfully entered {results_entered} results!')
        return redirect('admin_result_list')

    tournaments = Tournament.objects.all().order_by('name')
    context = {
        'tournaments': tournaments,
    }
    return render(request, 'superadmin/results_batch_enter.html', context)


@login_required
@user_passes_test(is_superadmin)
def admin_standings(request, tournament_id=None):
    """View tournament standings/leaderboard"""
    if not tournament_id and request.method == 'GET':
        # Show tournament selection
        tournaments = Tournament.objects.all().order_by('name')
        return render(request, 'superadmin/results_standings_select.html', {'tournaments': tournaments})

    if request.method == 'POST':
        tournament_id = request.POST.get('tournament')
        if tournament_id:
            return redirect('admin_standings', tournament_id=tournament_id)
        messages.error(request, 'Please select a tournament.')
        return redirect('admin_standings')

    tournament = get_object_or_404(Tournament, id=tournament_id)

    # Get all teams for this tournament with their stats
    teams = Team.objects.filter(tournament=tournament).order_by(
        '-points', '-wins', '-goals_for', 'goals_against'
    )

    # Calculate additional stats
    for team in teams:
        team.goal_difference = team.goals_for - team.goals_against
        team.form = get_team_form(team)
        team.recent_matches = get_recent_matches(team, limit=5)

    context = {
        'tournament': tournament,
        'teams': teams,
        'total_matches': Fixture.objects.filter(tournament=tournament, is_played=True).count(),
        'total_teams': teams.count(),
    }
    return render(request, 'superadmin/results_standings.html', context)


@login_required
@user_passes_test(is_superadmin)
def admin_result_export(request):
    """Export results to CSV"""
    import csv
    from django.http import HttpResponse

    tournament_id = request.GET.get('tournament')
    results = Result.objects.all().select_related(
        'fixture', 'fixture__tournament', 'fixture__home_team', 'fixture__away_team'
    )

    if tournament_id:
        results = results.filter(fixture__tournament_id=tournament_id)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="results_export.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Tournament', 'Round', 'Date', 'Home Team', 'Home Score',
        'Away Score', 'Away Team', 'Status'
    ])

    for result in results:
        writer.writerow([
            result.fixture.tournament.name,
            result.fixture.round,
            result.fixture.match_date.strftime('%Y-%m-%d %H:%M') if result.fixture.match_date else '',
            result.fixture.home_team.name,
            result.home_score,
            result.away_score,
            result.fixture.away_team.name,
            'Played' if result.fixture.is_played else 'Pending'
        ])

    return response


# Helper Functions
def update_team_stats(fixture):
    """Update team statistics after a result is saved"""
    if not fixture.is_played or not hasattr(fixture, 'result'):
        return

    result = fixture.result
    home = fixture.home_team
    away = fixture.away_team

    # Reset stats first (in case this is a re-entry)
    recalculate_team_stats(fixture, None, None, force_recalc=True)


def recalculate_team_stats(fixture, old_home_score=None, old_away_score=None, force_recalc=False):
    """Recalculate team stats for a fixture"""
    if not force_recalc and fixture.is_played:
        # If fixture is still played, we need to adjust stats
        result = fixture.result

        # Remove old stats first by recalculating all fixtures for these teams
        recalc_all_team_stats(fixture.tournament)
    else:
        # Force recalculation of all stats for the tournament
        recalc_all_team_stats(fixture.tournament)


def recalc_all_team_stats(tournament):
    """Completely recalculate all team stats for a tournament"""
    # Reset all teams
    teams = Team.objects.filter(tournament=tournament)
    for team in teams:
        team.points = 0
        team.played = 0
        team.wins = 0
        team.draws = 0
        team.losses = 0
        team.goals_for = 0
        team.goals_against = 0
        team.save()

    # Recalculate from played fixtures
    fixtures = Fixture.objects.filter(tournament=tournament, is_played=True).select_related('result')
    for fixture in fixtures:
        if hasattr(fixture, 'result'):
            result = fixture.result
            home = fixture.home_team
            away = fixture.away_team

            # Update home team stats
            home.played += 1
            home.goals_for += result.home_score
            home.goals_against += result.away_score

            if result.home_score > result.away_score:
                home.wins += 1
                home.points += 3
            elif result.home_score < result.away_score:
                home.losses += 1
            else:
                home.draws += 1
                home.points += 1

            # Update away team stats
            away.played += 1
            away.goals_for += result.away_score
            away.goals_against += result.home_score

            if result.away_score > result.home_score:
                away.wins += 1
                away.points += 3
            elif result.away_score < result.home_score:
                away.losses += 1
            else:
                away.draws += 1
                away.points += 1

            home.save()
            away.save()


def revert_team_stats(fixture):
    """Revert team stats when a result is deleted"""
    recalc_all_team_stats(fixture.tournament)


def get_team_form(team, limit=5):
    """Get recent form for a team"""
    fixtures = Fixture.objects.filter(
        Q(home_team=team) | Q(away_team=team),
        is_played=True
    ).select_related('result').order_by('-match_date')[:limit]

    form = []
    for fixture in fixtures:
        if hasattr(fixture, 'result'):
            result = fixture.result
            if fixture.home_team == team:
                if result.home_score > result.away_score:
                    form.append('W')
                elif result.home_score < result.away_score:
                    form.append('L')
                else:
                    form.append('D')
            else:
                if result.away_score > result.home_score:
                    form.append('W')
                elif result.away_score < result.home_score:
                    form.append('L')
                else:
                    form.append('D')

    return form


def get_recent_matches(team, limit=5):
    """Get recent matches for a team"""
    fixtures = Fixture.objects.filter(
        Q(home_team=team) | Q(away_team=team),
        is_played=True
    ).select_related('result', 'home_team', 'away_team').order_by('-match_date')[:limit]

    matches = []
    for fixture in fixtures:
        if hasattr(fixture, 'result'):
            result = fixture.result
            is_home = fixture.home_team == team
            matches.append({
                'opponent': fixture.away_team.name if is_home else fixture.home_team.name,
                'is_home': is_home,
                'score': f"{result.home_score}-{result.away_score}",
                'team_score': result.home_score if is_home else result.away_score,
                'opponent_score': result.away_score if is_home else result.home_score,
                'result': 'W' if (is_home and result.home_score > result.away_score) or
                                 (not is_home and result.away_score > result.home_score) else
                'L' if (is_home and result.home_score < result.away_score) or
                       (not is_home and result.away_score < result.home_score) else 'D',
                'date': fixture.match_date
            })

    return matches


@login_required
@user_passes_test(is_superadmin)
def api_get_unplayed_fixtures(request):
    """AJAX endpoint to get unplayed fixtures for batch entry"""
    tournament_id = request.GET.get('tournament')
    round_num = request.GET.get('round')

    if not tournament_id:
        return JsonResponse({'error': 'Tournament ID required'}, status=400)

    fixtures = Fixture.objects.filter(
        tournament_id=tournament_id,
        is_played=False
    ).exclude(away_team__isnull=True).select_related(
        'tournament', 'home_team', 'away_team'
    ).order_by('round', 'match_date')

    if round_num:
        fixtures = fixtures.filter(round=round_num)

    data = {
        'fixtures': [
            {
                'id': f.id,
                'tournament': f.tournament.name,
                'home_team': f.home_team.name,
                'away_team': f.away_team.name,
                'round': f.round,
                'match_date': f.match_date.strftime('%Y-%m-%d %H:%M') if f.match_date else None,
                'group': f.group.name if f.group else None,
            }
            for f in fixtures
        ]
    }

    return JsonResponse(data)


