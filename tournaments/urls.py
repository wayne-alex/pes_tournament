from django.urls import path

from . import views

urlpatterns = [
    path('dashboard/<int:tournament_id>/', views.dashboard, name='dashboard'),
    path('admin_login/', views.admin_login, name='admin_login'),
    path('admin_dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path("admin_tournament/", views.admin_tournament, name="tournament_create"),
    path("admin_teams/", views.admin_teams, name="teams"),
    path("admin_fixtures/<int:tournament_id>/", views.admin_fixtures, name="fixtures"),
    path("generate_fixtures/<str:int>/", views.generate_fixtures, name="generate_fixtures"),
    path("admin_results/", views.admin_results, name="results"),
    path("tournament/edit/<int:id>/", views.tournament_edit, name="tournament_edit"),
    path("tournament/delete/<int:id>/", views.tournament_delete, name="tournament_delete"),
    path("teams/edit/<int:id>/", views.team_edit, name="team_edit"),
    path("teams/delete/<int:id>/", views.team_delete, name="team_delete"),
]
