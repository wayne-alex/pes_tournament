import random
import math
from datetime import date, timedelta
from itertools import combinations
from collections import defaultdict

from .models import Tournament, Team, Group, Fixture


class FixtureGenerator:

    def __init__(self, tournament: Tournament, config: dict):
        self.tournament = tournament
        self.config = config

        self.start_date = date.fromisoformat(config["start_date"])
        self.end_date = date.fromisoformat(config["end_date"])

        self.home_away = tournament.mode == "home_away"

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
        elif fmt == "swiss":
            self._generate_swiss_round_one()
        else:
            raise ValueError(f"Unknown format: {fmt}")

    # ---------------------------
    # ROUND-BASED DATE ASSIGNMENT
    # ---------------------------
    # Every format below is now generated round-by-round, where a
    # "round" means every team plays at most once. All matches in
    # the same round share the same date, and rounds are assigned
    # dates in order across the tournament window. This guarantees
    # no team can play its 2nd match before another team has played
    # its 1st - the previous version numbered fixtures sequentially
    # after a random shuffle, which didn't make that guarantee.

    def _date_for_round(self, round_num: int, total_rounds: int):
        days = (self.end_date - self.start_date).days + 1
        if days <= 0:
            raise ValueError("Invalid date range")

        if days >= total_rounds:
            # spread rounds evenly across the whole window
            step = days / total_rounds
            offset = int((round_num - 1) * step)
        else:
            # more rounds than days available - compress rounds
            # onto shared days, but still strictly in round order
            rounds_per_day = math.ceil(total_rounds / days)
            offset = (round_num - 1) // rounds_per_day

        return self.start_date + timedelta(days=offset)

    def _circle_round_robin(self, teams, double=False):
        """
        Standard circle method. Returns a list of rounds, each round
        a list of (home, away) tuples. Every team appears at most
        once per round; an odd team count gets a bye each round
        (whichever team lands on the padded slot). `double=True`
        mirrors every round with home/away swapped, for a full
        home-and-away league.
        """
        working = list(teams)
        if len(working) % 2 == 1:
            working.append(None)  # bye placeholder

        n = len(working)
        rounds = []
        rotation = working[:]

        for _ in range(n - 1):
            round_matches = []
            for i in range(n // 2):
                home = rotation[i]
                away = rotation[n - 1 - i]
                if home is not None and away is not None:
                    round_matches.append((home, away))
            rounds.append(round_matches)
            # rotate everyone except the fixed first slot
            rotation = [rotation[0]] + [rotation[-1]] + rotation[1:-1]

        if double:
            second_leg = [
                [(away, home) for home, away in round_matches]
                for round_matches in rounds
            ]
            rounds += second_leg

        return rounds

    # ---------------------------
    # LEAGUE
    # ---------------------------
    def _generate_league(self):

        teams = list(Team.objects.filter(tournament=self.tournament))
        if len(teams) < 2:
            raise ValueError("Need at least 2 teams")

        random.shuffle(teams)  # randomize seeding, not match order
        rounds = self._circle_round_robin(teams, double=self.home_away)
        total_rounds = len(rounds)

        for round_num, matches in enumerate(rounds, start=1):
            match_date = self._date_for_round(round_num, total_rounds)
            for home, away in matches:
                Fixture.objects.create(
                    tournament=self.tournament,
                    home_team=home,
                    away_team=away,
                    match_date=match_date,
                    round=round_num,
                )

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

        # single round - every remaining team plays exactly once
        match_date = self._date_for_round(1, 1)

        for home, away in matchups:
            if home is None or away is None:
                continue

            Fixture.objects.create(
                tournament=self.tournament,
                home_team=home,
                away_team=away,
                match_date=match_date,
                round=1,
            )

    # ---------------------------
    # GROUP + KNOCKOUT
    # ---------------------------
    def _generate_group_knockout(self):

        num_groups = int(self.config.get("groups", 2))
        # qualify_per_group is used later at the knockout-seeding stage,
        # not during group fixture generation - kept here for callers
        # that read it off self.config after calling generate().
        _qualify = int(self.config.get("qualify_per_group", 2))

        teams = list(Team.objects.filter(tournament=self.tournament))
        random.shuffle(teams)

        groups_teams = [[] for _ in range(num_groups)]

        for i, team in enumerate(teams):
            groups_teams[i % num_groups].append(team)

        # ? STEP 1: Create groups + a real round-robin per group
        groups = []
        group_round_lists = []  # per-group list of rounds

        for idx, group_teams in enumerate(groups_teams):

            group = Group.objects.create(
                tournament=self.tournament,
                name=f"Group {chr(65 + idx)}"
            )

            group.teams.set(group_teams)
            groups.append(group)

            group_round_lists.append(
                self._circle_round_robin(group_teams, double=self.home_away)
            )

        # ? STEP 2: WALK ROUNDS IN LOCKSTEP ACROSS GROUPS
        # Round 1 for every group happens on the same date, round 2
        # for every group happens on the next date, and so on - so
        # no group runs ahead of the others. Smaller groups simply
        # run out of rounds earlier and drop out of later dates.
        max_rounds = max((len(r) for r in group_round_lists), default=0)

        for round_num in range(1, max_rounds + 1):
            match_date = self._date_for_round(round_num, max_rounds)

            for group, group_rounds in zip(groups, group_round_lists):
                if round_num - 1 >= len(group_rounds):
                    continue  # this group already finished its rounds

                for home, away in group_rounds[round_num - 1]:
                    Fixture.objects.create(
                        tournament=self.tournament,
                        group=group,
                        home_team=home,
                        away_team=away,
                        match_date=match_date,
                        round=round_num,
                    )

    # ---------------------------
    # SWISS SYSTEM
    # ---------------------------
    # NOTE: unlike the formats above, Swiss pairing after round 1
    # depends on live standings, so it CANNOT be fully generated
    # upfront. Call `_generate_swiss_round_one()` (via generate())
    # to create round 1, then call `generate_next_swiss_round(n)`
    # yourself after round n-1's results are saved.

    def _recommended_swiss_rounds(self, num_teams: int) -> int:
        """
        UEFA plays 8 of 35 possible opponents (~23%) with 36 teams.
        That ratio doesn't translate to small fields - for <=6 teams
        a full round robin is simpler and fairer than Swiss, so we
        just return that. For 10-12 team fields this lands around
        5-6 rounds by default (override via config["num_rounds"]).
        """
        if num_teams <= 2:
            return 1

        max_possible = num_teams - 1  # full round robin length

        if num_teams <= 6:
            return max_possible

        suggested = max(4, math.ceil(math.log2(num_teams)) + 2)
        return min(suggested, max_possible)

    def _generate_swiss_round_one(self):
        teams = list(Team.objects.filter(tournament=self.tournament))
        if len(teams) < 2:
            raise ValueError("Need at least 2 teams")

        num_rounds = int(
            self.config.get("num_rounds")
            or self._recommended_swiss_rounds(len(teams))
        )

        # requires a `swiss_total_rounds` IntegerField on Tournament
        self.tournament.swiss_total_rounds = num_rounds
        self.tournament.save(update_fields=["swiss_total_rounds"])

        random.shuffle(teams)
        pairs, bye_team = self._pair_teams(teams, played_pairs=set())

        match_date = self._date_for_round(1, num_rounds)
        self._create_round_fixtures(
            pairs, round_num=1, match_date=match_date, bye_team=bye_team
        )

    def generate_next_swiss_round(self, round_num: int):
        """
        Call this after every fixture in `round_num - 1` has a
        result saved. Re-ranks teams by current standings and pairs
        neighbours in that ranking, skipping any pair that has
        already played this tournament where possible.
        """
        total_rounds = getattr(self.tournament, "swiss_total_rounds", None)
        if total_rounds and round_num > total_rounds:
            raise ValueError(f"Swiss phase only runs {total_rounds} rounds")

        standings = self._swiss_standings()
        ordered_teams = [team for team, _points in standings]

        played_pairs = self._played_pairs()
        byes_taken = self._teams_with_byes()

        pairs, bye_team = self._pair_teams(
            ordered_teams, played_pairs=played_pairs, avoid_bye=byes_taken
        )

        match_date = self._date_for_round(round_num, total_rounds)
        self._create_round_fixtures(
            pairs, round_num=round_num, match_date=match_date, bye_team=bye_team
        )

    # ---- swiss helpers ----

    def _pair_teams(self, ordered_teams, played_pairs, avoid_bye=None):
        """
        Walks down a standings-ordered list pairing neighbours,
        skipping opponents already played where a fresh option
        exists. Odd team counts get a bye, preferring a team that
        hasn't had one yet.
        """
        avoid_bye = avoid_bye or set()
        teams = list(ordered_teams)

        bye_team = None
        if len(teams) % 2 == 1:
            for team in reversed(teams):
                if team.id not in avoid_bye:
                    bye_team = team
                    break
            if bye_team is None:
                bye_team = teams[-1]
            teams.remove(bye_team)

        pairs = []
        unpaired = teams[:]

        while unpaired:
            current = unpaired.pop(0)
            opponent = self._find_opponent(current, unpaired, played_pairs)
            unpaired.remove(opponent)
            pairs.append((current, opponent))

        return pairs, bye_team

    def _find_opponent(self, team, candidates, played_pairs):
        for opponent in candidates:
            if frozenset({team.id, opponent.id}) not in played_pairs:
                return opponent
        # everyone left has already played this team (common in small
        # fields with many rounds) - fall back to the closest-ranked one
        return candidates[0]

    def _played_pairs(self):
        pairs = set()
        fixtures = Fixture.objects.filter(tournament=self.tournament).values_list(
            "home_team_id", "away_team_id"
        )
        for home_id, away_id in fixtures:
            if away_id is not None:
                pairs.add(frozenset({home_id, away_id}))
        return pairs

    def _teams_with_byes(self):
        # a bye fixture is stored with away_team=None
        return set(
            Fixture.objects.filter(
                tournament=self.tournament, away_team__isnull=True
            ).values_list("home_team_id", flat=True)
        )

    def _swiss_standings(self):
        """
        3/1/0 points off Fixture -> Result. Adjust field names here
        to match your actual Result model if it differs.
        """
        points = defaultdict(int)
        teams = {t.id: t for t in Team.objects.filter(tournament=self.tournament)}

        fixtures = Fixture.objects.filter(
            tournament=self.tournament, result__isnull=False
        ).select_related("result")

        for fixture in fixtures:
            result = fixture.result
            if result.home_score > result.away_score:
                points[fixture.home_team_id] += 3
            elif result.home_score < result.away_score:
                points[fixture.away_team_id] += 3
            else:
                points[fixture.home_team_id] += 1
                points[fixture.away_team_id] += 1

        ranked = sorted(teams.values(), key=lambda t: points[t.id], reverse=True)
        return [(team, points[team.id]) for team in ranked]

    def _create_round_fixtures(self, pairs, round_num, match_date, bye_team=None):
        for home, away in pairs:
            Fixture.objects.create(
                tournament=self.tournament,
                home_team=home,
                away_team=away,
                match_date=match_date,
                round=round_num,
            )
        if bye_team is not None:
            Fixture.objects.create(
                tournament=self.tournament,
                home_team=bye_team,
                away_team=None,
                match_date=match_date,
                round=round_num,
            )

    # ---------------------------
    # HELPERS
    # ---------------------------
    def _next_power_of_two(self, n: int) -> int:
        power = 1
        while power < n:
            power *= 2
        return power