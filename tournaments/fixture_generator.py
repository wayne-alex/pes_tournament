import random
import math
from datetime import date, timedelta
from itertools import combinations

from .models import Tournament, Team, Group, Fixture


class FixtureGenerator:

    def __init__(self, tournament: Tournament, config: dict):
        self.tournament = tournament
        self.config = config

        self.start_date = date.fromisoformat(config["start_date"])
        self.end_date = date.fromisoformat(config["end_date"])

        self.home_away = tournament.mode == "home_away"

        # slot pool will be built AFTER we calculate required density
        self._slot_pool = []

    # ---------------------------
    # MAIN GENERATE
    # ---------------------------
    def generate(self):

        Fixture.objects.filter(tournament=self.tournament).delete()
        Group.objects.filter(tournament=self.tournament).delete()

        fmt = self.tournament.tournament_format

        if fmt == "league":
            self._generate_league()
        elif fmt == "knockout":
            self._generate_knockout()
        elif fmt == "group_knockout":
            self._generate_group_knockout()
        else:
            raise ValueError(f"Unknown format: {fmt}")

    # ---------------------------
    # SLOT SYSTEM (AUTO BALANCED)
    # ---------------------------
    def _build_slot_pool(self, total_matches: int):

        days = (self.end_date - self.start_date).days + 1
        if days <= 0:
            raise ValueError("Invalid date range")

        games_per_day = math.ceil(total_matches / days)

        slots = []
        current = self.start_date

        while current <= self.end_date:
            for _ in range(games_per_day):
                slots.append(current)
            current += timedelta(days=1)

        return slots

    def _pop_slot(self):
        if self._slot_pool:
            return self._slot_pool.pop(0)
        return self.end_date  # fallback safety

    # ---------------------------
    # LEAGUE
    # ---------------------------
    def _generate_league(self):

        teams = list(Team.objects.filter(tournament=self.tournament))
        if len(teams) < 2:
            raise ValueError("Need at least 2 teams")

        matchups = list(combinations(teams, 2))

        if self.home_away:
            matchups += [(b, a) for a, b in matchups]

        random.shuffle(matchups)

        # 🔥 AUTO SLOT BUILD BASED ON TOTAL MATCHES
        self._slot_pool = self._build_slot_pool(len(matchups))

        round_num = 1

        for home, away in matchups:
            Fixture.objects.create(
                tournament=self.tournament,
                home_team=home,
                away_team=away,
                match_date=self._pop_slot(),
                round=round_num,
            )
            round_num += 1

    # ---------------------------
    # KNOCKOUT
    # ---------------------------
    def _generate_knockout(self):

        teams = list(Team.objects.filter(tournament=self.tournament))
        random.shuffle(teams)

        if len(teams) < 2:
            raise ValueError("Need at least 2 teams")

        size = self._next_power_of_two(len(teams))
        teams += [None] * (size - len(teams))

        matchups = [(teams[i], teams[i + 1]) for i in range(0, len(teams), 2)]

        self._slot_pool = self._build_slot_pool(len(matchups))

        for home, away in matchups:
            if home is None or away is None:
                continue

            Fixture.objects.create(
                tournament=self.tournament,
                home_team=home,
                away_team=away,
                match_date=self._pop_slot(),
                round=1,
            )

    # ---------------------------
    # GROUP + KNOCKOUT
    # ---------------------------
    def _generate_group_knockout(self):

        num_groups = int(self.config.get("groups", 2))
        qualify = int(self.config.get("qualify_per_group", 2))

        teams = list(Team.objects.filter(tournament=self.tournament))
        random.shuffle(teams)

        groups_teams = [[] for _ in range(num_groups)]

        for i, team in enumerate(teams):
            groups_teams[i % num_groups].append(team)

        # 🔥 STEP 1: Create groups
        groups = []
        group_match_lists = []

        for idx, group_teams in enumerate(groups_teams):

            group = Group.objects.create(
                tournament=self.tournament,
                name=f"Group {chr(65 + idx)}"
            )

            group.teams.set(group_teams)
            groups.append(group)

            matches = list(combinations(group_teams, 2))

            if self.home_away:
                matches += [(b, a) for a, b in matches]

            random.shuffle(matches)

            # store matches per group
            group_match_lists.append([
                (group, home, away) for home, away in matches
            ])

        # 🔥 STEP 2: INTERLEAVE matches across groups
        mixed_matches = []

        while any(group_match_lists):
            for group_list in group_match_lists:
                if group_list:
                    mixed_matches.append(group_list.pop(0))

        # 🔥 STEP 3: RANDOMIZE SLIGHTLY (optional but recommended)
        random.shuffle(mixed_matches)

        # 🔥 STEP 4: BUILD SLOT POOL BASED ON TOTAL MATCHES
        self._slot_pool = self._build_slot_pool(len(mixed_matches))

        # 🔥 STEP 5: CREATE FIXTURES
        round_num = 1

        for group, home, away in mixed_matches:
            Fixture.objects.create(
                tournament=self.tournament,
                group=group,
                home_team=home,
                away_team=away,
                match_date=self._pop_slot(),
                round=round_num,
            )
            round_num += 1

    # ---------------------------
    # HELPERS
    # ---------------------------
    def _next_power_of_two(self, n: int) -> int:
        power = 1
        while power < n:
            power *= 2
        return power