from django.contrib import admin

from tournaments.models import Tournament, Fixture, Group, Team

# Register your models here.
admin.site.register(Tournament)
admin.site.register(Fixture)
admin.site.register(Group)
admin.site.register(Team)