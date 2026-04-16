from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Result
from .standings import StandingsService


@receiver(post_save, sender=Result)
def update_standings(sender, instance, **kwargs):
    tournament = instance.fixture.tournament
    StandingsService.calculate(tournament)