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

    # Manifest
    path('manifest.json', TemplateView.as_view(
        template_name='manifest.json',
        content_type='application/json'
    ), name='manifest'),

]
