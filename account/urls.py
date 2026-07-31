from django.urls import path
from . import views


urlpatterns = [
# Authentication
    path('login/', views.admin_login, name='admin_login'),
    path('logout/', views.admin_logout, name='admin_logout'),
    # Dashboard
    path('', views.superadmin_dashboard, name='superadmin_dashboard'),

    # User Management
    path('users/', views.admin_user_list, name='admin_user_list'),
    path('users/create/', views.admin_user_create, name='admin_user_create'),
    path('users/<int:user_id>/edit/', views.admin_user_edit, name='admin_user_edit'),
    path('users/<int:user_id>/delete/', views.admin_user_delete, name='admin_user_delete'),

    # Tournament Management
    path('tournaments/', views.admin_tournament_list, name='admin_tournament_list'),
    path('tournaments/create/', views.admin_tournament_create, name='admin_tournament_create'),
    path('tournaments/<int:tournament_id>/edit/', views.admin_tournament_edit, name='admin_tournament_edit'),
    path('tournaments/<int:tournament_id>/delete/', views.admin_tournament_delete, name='admin_tournament_delete'),

    # Team Management
    path('teams/', views.admin_team_list, name='admin_team_list'),
    path('teams/create/', views.admin_team_create, name='admin_team_create'),
    path('teams/bulk-create/', views.admin_team_bulk_create, name='admin_team_bulk_create'),
    path('teams/<int:team_id>/edit/', views.admin_team_edit, name='admin_team_edit'),
    path('teams/<int:team_id>/delete/', views.admin_team_delete, name='admin_team_delete'),
    path('teams/<int:team_id>/stats/', views.admin_team_stats, name='admin_team_stats'),
    path('teams/export/', views.admin_team_export, name='admin_team_export'),
    path('teams/import/', views.admin_team_import, name='admin_team_import'),

    # Fixture Management
    path('fixtures/', views.admin_fixture_list, name='admin_fixture_list'),
    path('fixtures/create/', views.admin_fixture_create, name='admin_fixture_create'),
    path('fixtures/<int:fixture_id>/edit/', views.admin_fixture_edit, name='admin_fixture_edit'),
    path('fixtures/<int:fixture_id>/delete/', views.admin_fixture_delete, name='admin_fixture_delete'),
    path('fixtures/generate/', views.admin_fixture_generate, name='admin_fixture_generate'),
    path('fixtures/next-round/', views.admin_fixture_next_round, name='admin_fixture_next_round'),
    path('fixtures/delete-all/', views.admin_fixture_delete_all, name='admin_fixture_delete_all'),
    path('fixtures/schedule-edit/', views.admin_fixture_schedule_edit, name='admin_fixture_schedule_edit'),
    path('fixtures/quick-edit/', views.admin_fixture_quick_edit, name='admin_fixture_quick_edit'),
    # Results Management
    path('results/', views.admin_result_list, name='admin_result_list'),
    path('results/enter/', views.admin_result_enter, name='admin_result_enter'),
    path('results/enter/<int:fixture_id>/', views.admin_result_enter, name='admin_result_enter'),
    path('results/<int:result_id>/edit/', views.admin_result_edit, name='admin_result_edit'),
    path('results/<int:result_id>/delete/', views.admin_result_delete, name='admin_result_delete'),
    path('results/batch-enter/', views.admin_result_batch_enter, name='admin_result_batch_enter'),
    path('results/standings/', views.admin_standings, name='admin_standings'),
    path('results/standings/<int:tournament_id>/', views.admin_standings, name='admin_standings'),
    path('results/export/', views.admin_result_export, name='admin_result_export'),

    # API Endpoints
    path('api/fixtures/get-unplayed/',views.api_get_unplayed_fixtures, name='api_get_unplayed_fixtures'),


]