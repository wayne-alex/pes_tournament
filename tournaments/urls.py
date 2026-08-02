from django.urls import path
from django.views.generic import TemplateView

from . import views

urlpatterns = [
    path('dashboard/<int:tournament_id>/', views.dashboard, name='dashboard'),
    path("dashboard/", views.lobby, name="dashboard_home"),
    path("tournament-live/<int:tournament_id>/", views.tournament_live_api, name="tournament-live"),
    path('api/poll/<int:fixture_id>/vote/', views.cast_poll_vote, name='cast_poll_vote'),
    path('api/poll/<int:fixture_id>/results/', views.get_poll_results, name='get_poll_results'),

    # PWA URLs
    path('offline/', views.offline_page, name='offline'),
    path('sw.js', views.service_worker, name='service-worker'),
    path('api/save-pending-vote/', views.save_pending_vote, name='save_pending_vote'),

    # Swiss Plus URLs
    path('tournament/<int:tournament_id>/swiss/', views.swiss_dashboard, name='swiss_dashboard'),
    path('tournament/<int:tournament_id>/swiss/next-round/', views.generate_next_swiss_round,
         name='generate_next_swiss_round'),
    path('tournament/<int:tournament_id>/swiss/complete/', views.complete_swiss_phase, name='complete_swiss_phase'),
    path('tournament/<int:tournament_id>/swiss/playoff/', views.generate_playoff_rounds,
         name='generate_playoff_rounds'),
    path('tournament/<int:tournament_id>/swiss/knockout/', views.generate_knockout_from_swiss,
         name='generate_knockout_from_swiss'),
    path('tournament/<int:tournament_id>/swiss/standings/', views.get_swiss_standings_api, name='swiss_standings_api'),
    path('api/swiss/update-counts/<int:tournament_id>/', views.update_swiss_counts, name='update_swiss_counts'),

    path('tournament/<int:tournament_id>/swiss/knockout/next/',
         views.generate_next_knockout_round,
         name='generate_next_knockout_round'),

    path('tournament/<int:tournament_id>/swiss/knockout/status/',
         views.get_knockout_status,
         name='get_knockout_status'),

    # Tournament Dashboard (League, Knockout, Group Knockout)
    path('tournament/<int:tournament_id>/', views.tournament_dashboard, name='tournament_dashboard'),

    # Manifest
    path('manifest.json', TemplateView.as_view(
        template_name='manifest.json',
        content_type='application/json'
    ), name='manifest'),

]
