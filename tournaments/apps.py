from django.apps import AppConfig


class TournamentsConfig(AppConfig):
    name = 'tournaments'
def ready(self):
    import tournaments.signals