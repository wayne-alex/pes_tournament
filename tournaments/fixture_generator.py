# fixture_generator.py
import random
import math
from datetime import date, timedelta
from typing import List, Dict, Optional, Any, Tuple
from collections import defaultdict

from django.db import models
from django.db.models import F, Sum, Q, Max

from .models import Tournament, Team, Group, Fixture, Result
from .fixture_engine import SwissPairingEngine, Team as EngineTeam, Fixture as EngineFixture


class FixtureGenerator:
    """
    Django integration layer for the pure fixture generation engine.
    Handles database operations while delegating logic to the engine.
    """

    def __init__(self, tournament: Tournament, config: dict):
        self.tournament = tournament
        self.config = config

        # Handle date parsing safely
        if "start_date" in config:
            self.start_date = date.fromisoformat(config["start_date"])
        else:
            self.start_date = date.today()

        if "end_date" in config:
            self.end_date = date.fromisoformat(config["end_date"])
        else:
            self.end_date = self.start_date + timedelta(days=30)

        self.home_away = tournament.mode == "home_away"

    # ---------------------------
    # MAIN GENERATE
    # ---------------------------
    def generate(self):
        """Main entry point - generates fixtures based on tournament format."""
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
            self._generate_swiss()
        elif fmt == "swiss_plus":
            self._generate_swiss_pro()
        else:
            raise ValueError(f"Unknown format: {fmt}")

    # ---------------------------
    # DATE HELPERS
    # ---------------------------
    def _date_for_round(self, round_num: int, total_rounds: int):
        """Calculate date for a specific round."""
        days = (self.end_date - self.start_date).days + 1
        if days <= 0:
            raise ValueError("Invalid date range")

        if days >= total_rounds:
            step = days / total_rounds
            offset = int((round_num - 1) * step)
        else:
            rounds_per_day = math.ceil(total_rounds / days)
            offset = (round_num - 1) // rounds_per_day

        return self.start_date + timedelta(days=offset)

    # ---------------------------
    # LEAGUE (Round Robin)
    # ---------------------------
    def _generate_league(self):
        teams = list(Team.objects.filter(tournament=self.tournament))
        if len(teams) < 2:
            raise ValueError("Need at least 2 teams")

        random.shuffle(teams)
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
        teams = list(Team.objects.filter(tournament=self.tournament))
        random.shuffle(teams)

        groups_teams = [[] for _ in range(num_groups)]
        for i, team in enumerate(teams):
            groups_teams[i % num_groups].append(team)

        groups = []
        group_round_lists = []

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

        max_rounds = max((len(r) for r in group_round_lists), default=0)

        for round_num in range(1, max_rounds + 1):
            match_date = self._date_for_round(round_num, max_rounds)
            for group, group_rounds in zip(groups, group_round_lists):
                if round_num - 1 >= len(group_rounds):
                    continue
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
    # PURE SWISS (No Split)
    # ---------------------------
    def _generate_swiss(self):
        """Generate pure Swiss tournament - just rounds, no split."""
        teams = list(Team.objects.filter(tournament=self.tournament))
        if len(teams) < 2:
            raise ValueError("Need at least 2 teams")

        num_rounds = int(
            self.config.get("num_rounds")
            or self._recommended_swiss_rounds(len(teams))
        )

        self.tournament.swiss_total_rounds = num_rounds
        self.tournament.save(update_fields=["swiss_total_rounds"])

        # Use pure engine
        engine_teams = self._get_engine_teams()
        engine = SwissPairingEngine(engine_teams, self.config)
        structure = engine.generate_swiss_round_one()

        # Save fixtures
        if structure.rounds:
            self._save_engine_fixtures(structure.rounds[0])

    # ---------------------------
    # SWISS PRO (With Split)
    # ---------------------------
    def _generate_swiss_pro(self):
        """Generate Swiss Pro - Swiss phase with split/playoff/knockout."""
        teams = list(Team.objects.filter(tournament=self.tournament))
        if len(teams) < 4:
            raise ValueError("Swiss Pro requires at least 4 teams")

        num_rounds = int(
            self.config.get("num_rounds")
            or self._recommended_swiss_rounds(len(teams))
        )

        # Calculate and store split counts
        direct_count, playoff_count, eliminated_count = self._calculate_split(len(teams))

        # Store on tournament
        self.tournament.swiss_total_rounds = num_rounds
        self.tournament.swiss_direct_count = direct_count
        self.tournament.swiss_playoff_count = playoff_count
        self.tournament.swiss_eliminated_count = eliminated_count
        self.tournament.swiss_phase_complete = False
        self.tournament.split_phase_complete = False
        self.tournament.playoff_phase_complete = False
        self.tournament.knockout_phase_complete = False
        self.tournament.save()

        # Use pure engine
        engine_teams = self._get_engine_teams()
        engine = SwissPairingEngine(engine_teams, self.config)
        structure = engine.generate_swiss_round_one()

        # Save fixtures
        if structure.rounds:
            self._save_engine_fixtures(structure.rounds[0])

    # ---------------------------
    # SWISS NEXT ROUND (Using Pure Engine)
    # ---------------------------
    def generate_next_swiss_round(self, round_num: int) -> int:
        """
        Generate the next Swiss round for BOTH Swiss and Swiss Pro.
        Returns number of fixtures created.
        """
        # Check if round already exists
        existing = Fixture.objects.filter(
            tournament=self.tournament,
            round=round_num
        ).exists()

        if existing:
            raise ValueError(f"Round {round_num} already exists")

        # Get all results so far
        engine_results = self._get_engine_results()

        # Rebuild engine from database state
        engine = self._rebuild_engine()

        # Generate next round
        structure = engine.generate_next_swiss_round(round_num, engine_results)

        # Save new fixtures
        fixtures_created = 0
        if structure.rounds:
            new_fixtures = structure.rounds[-1]
            self._save_engine_fixtures(new_fixtures)
            fixtures_created = len(new_fixtures)

        return fixtures_created

    # ---------------------------
    # SWISS SPLIT - SINGLE SOURCE OF TRUTH
    # ---------------------------
    def generate_swiss_split(self) -> Dict:
        """
        Complete Swiss phase, rank teams, and split into Direct/Playoff/Eliminated.
        Uses the SAME standings calculation as the dashboard.
        Only for Swiss Pro format.
        """
        if self.tournament.tournament_format != "swiss_plus":
            raise ValueError("Split is only available for Swiss Pro format")

        # Get standings using the SAME method as dashboard
        standings = self._calculate_standings_from_db()

        if not standings:
            raise ValueError("No standings data available")

        # Get split counts from tournament (already calculated during generation)
        direct_count = self.tournament.swiss_direct_count or 0
        playoff_count = self.tournament.swiss_playoff_count or 0

        # If counts are not set, calculate them
        if direct_count == 0 and playoff_count == 0:
            total = len(standings)
            direct_count, playoff_count, _ = self._calculate_split(total)
            self.tournament.swiss_direct_count = direct_count
            self.tournament.swiss_playoff_count = playoff_count
            self.tournament.save()

        # Extract teams from standings
        direct_teams = [s['team'] for s in standings[:direct_count]]
        playoff_teams = [s['team'] for s in standings[direct_count:direct_count + playoff_count]]
        eliminated_teams = [s['team'] for s in standings[direct_count + playoff_count:]]

        # Store on tournament
        self.tournament.swiss_phase_complete = True
        self.tournament.split_phase_complete = True
        self.tournament.save()

        # Save split to Groups
        self._save_split_groups_direct(direct_teams, playoff_teams, eliminated_teams)

        return {
            'direct_count': direct_count,
            'playoff_count': playoff_count,
            'eliminated_count': len(eliminated_teams),
            'direct_teams': [t.name for t in direct_teams],
            'playoff_teams': [t.name for t in playoff_teams],
            'eliminated_teams': [t.name for t in eliminated_teams],
        }

    def _calculate_split(self, total_teams: int) -> Tuple[int, int, int]:
        """
        Calculate split for Swiss Pro.
        Direct count is fixed at 25% (floored).
        Playoff count is adjusted to ensure power-of-2 knockout bracket.
        Eliminated gets whatever is left.

        Returns: (direct_count, playoff_count, eliminated_count)
        """
        direct_pct = self.config.get("direct_percent", 25)
        playoff_pct = self.config.get("playoff_percent", 50)

        # Step 1: Direct is fixed - use FLOOR (not round)
        direct_count = int(total_teams * direct_pct / 100)
        direct_count = max(1, direct_count)  # At least 1 direct qualifier

        # Step 2: Calculate ideal playoff count (FLOOR, make even)
        ideal_playoff = int(total_teams * playoff_pct / 100)
        if ideal_playoff % 2 != 0:
            ideal_playoff -= 1  # Make even
        ideal_playoff = max(0, ideal_playoff)  # Can be 0

        # Step 3: We need: direct_count + (playoff_count / 2) = power of 2
        # So: playoff_count = (power_of_2 - direct_count) * 2
        # And playoff_count must be <= total_teams - direct_count

        # Find the best power of 2 that works
        powers = [2, 4, 8, 16, 32, 64]
        best_playoff = ideal_playoff
        best_diff = float('inf')

        # First, try to find a power of 2 that works with the ideal playoff count
        playoff_winners = ideal_playoff // 2
        knockout_total = direct_count + playoff_winners

        if knockout_total > 0 and (knockout_total & (knockout_total - 1)) == 0:
            # Already a power of 2 - perfect!
            playoff_count = ideal_playoff
        else:
            # Need to adjust - try each power of 2
            for power in powers:
                # Skip if power is less than direct_count (can't have negative playoff)
                if power <= direct_count:
                    continue

                # Calculate required playoff count
                needed_playoff = (power - direct_count) * 2

                # Check if this is feasible
                if needed_playoff < 0:
                    continue
                if needed_playoff > total_teams - direct_count:
                    continue

                # Check how close this is to the ideal
                diff = abs(needed_playoff - ideal_playoff)

                # Prefer smaller playoff counts (more eliminated teams is better)
                # But also prefer counts closer to ideal
                if diff < best_diff or (diff == best_diff and needed_playoff < best_playoff):
                    best_diff = diff
                    best_playoff = needed_playoff

            playoff_count = best_playoff

        # Step 4: If we couldn't find a good match, try the next best option
        # This handles edge cases where no power of 2 works well
        if best_diff == float('inf'):
            # Try to adjust by adding or removing from playoff
            for adjust in range(0, total_teams, 2):
                # Try adding
                test_playoff = ideal_playoff + adjust
                if test_playoff <= total_teams - direct_count:
                    playoff_winners = test_playoff // 2
                    knockout_total = direct_count + playoff_winners
                    if knockout_total > 0 and (knockout_total & (knockout_total - 1)) == 0:
                        playoff_count = test_playoff
                        break

                # Try subtracting
                test_playoff = ideal_playoff - adjust
                if test_playoff >= 0:
                    playoff_winners = test_playoff // 2
                    knockout_total = direct_count + playoff_winners
                    if knockout_total > 0 and (knockout_total & (knockout_total - 1)) == 0:
                        playoff_count = test_playoff
                        break
            else:
                # Fallback: just use ideal and force power of 2
                playoff_count = ideal_playoff
                # Force by adjusting direct? No, we keep direct fixed.
                # Instead, adjust playoff to nearest power of 2
                for power in powers:
                    if power > direct_count:
                        playoff_count = (power - direct_count) * 2
                        if playoff_count <= total_teams - direct_count:
                            break

        # Step 5: Ensure playoff is even
        if playoff_count % 2 != 0:
            playoff_count -= 1

        # Step 6: Ensure we don't exceed total teams
        if direct_count + playoff_count > total_teams:
            playoff_count = total_teams - direct_count
            if playoff_count % 2 != 0:
                playoff_count -= 1

        # Step 7: Final validation - ensure knockout is power of 2
        playoff_winners = playoff_count // 2
        knockout_total = direct_count + playoff_winners

        # If still not power of 2, try to find the closest power
        if knockout_total > 0 and (knockout_total & (knockout_total - 1)) != 0:
            # Find the power of 2 that's closest to knockout_total
            closest_power = 2
            for power in powers:
                if power > direct_count and abs(power - knockout_total) < abs(closest_power - knockout_total):
                    closest_power = power

            # Adjust playoff to reach closest_power
            if closest_power > direct_count:
                playoff_count = (closest_power - direct_count) * 2
                if playoff_count > total_teams - direct_count:
                    # Too many teams, try next power down
                    next_power = closest_power // 2
                    if next_power > direct_count:
                        playoff_count = (next_power - direct_count) * 2
                    else:
                        # Force at least 2 teams in knockout
                        playoff_count = 2
            else:
                # Force at least 2 teams in knockout
                playoff_count = 2

            # Final validation
            if direct_count + playoff_count > total_teams:
                playoff_count = total_teams - direct_count
                if playoff_count % 2 != 0:
                    playoff_count -= 1

        # Step 8: Calculate eliminated
        eliminated_count = total_teams - direct_count - playoff_count

        # Ensure no negative counts
        if eliminated_count < 0:
            playoff_count = total_teams - direct_count
            if playoff_count % 2 != 0:
                playoff_count -= 1
            eliminated_count = total_teams - direct_count - playoff_count

        # Step 9: Ensure playoff is even one more time
        if playoff_count % 2 != 0:
            playoff_count -= 1
            eliminated_count = total_teams - direct_count - playoff_count

        return direct_count, playoff_count, eliminated_count

    def _save_split_groups_direct(self, direct_teams, playoff_teams, eliminated_teams):
        """Save split results to Group objects using direct team lists."""
        # Delete existing split groups
        Group.objects.filter(
            tournament=self.tournament,
            name__in=['Direct Qualifiers', 'Playoff', 'Eliminated']
        ).delete()

        # Direct Qualifiers
        if direct_teams:
            group = Group.objects.create(
                tournament=self.tournament,
                name='Direct Qualifiers'
            )
            team_ids = [t.id for t in direct_teams]
            group.teams.set(Team.objects.filter(id__in=team_ids))

        # Playoff
        if playoff_teams:
            group = Group.objects.create(
                tournament=self.tournament,
                name='Playoff'
            )
            team_ids = [t.id for t in playoff_teams]
            group.teams.set(Team.objects.filter(id__in=team_ids))

        # Eliminated
        if eliminated_teams:
            group = Group.objects.create(
                tournament=self.tournament,
                name='Eliminated'
            )
            team_ids = [t.id for t in eliminated_teams]
            group.teams.set(Team.objects.filter(id__in=team_ids))

    # ---------------------------
    # HELPER METHOD FOR POPULATING DB
    # ---------------------------
    def get_split_counts_for_db(self) -> Dict:
        """
        Helper method to get split counts for populating the database.
        This can be called when creating a Swiss Pro tournament to pre-populate
        the direct_count and playoff_count fields.

        Returns: {
            'direct_count': int,
            'playoff_count': int,
            'eliminated_count': int,
            'knockout_size': int,
            'total_teams': int
        }
        """
        teams = list(Team.objects.filter(tournament=self.tournament))
        total_teams = len(teams)

        if total_teams < 4:
            raise ValueError("Swiss Pro requires at least 4 teams")

        direct_count, playoff_count, eliminated_count = self._calculate_split(total_teams)
        knockout_size = direct_count + (playoff_count // 2)

        return {
            'total_teams': total_teams,
            'direct_count': direct_count,
            'playoff_count': playoff_count,
            'eliminated_count': eliminated_count,
            'knockout_size': knockout_size,
            'direct_percent': round((direct_count / total_teams) * 100, 1),
            'playoff_percent': round((playoff_count / total_teams) * 100, 1),
            'eliminated_percent': round((eliminated_count / total_teams) * 100, 1),
        }

    def populate_tournament_split_fields(self) -> Dict:
        """
        Populate the tournament's split fields in the database.
        This is a convenience method that can be called after tournament creation.

        Returns: Dict with the populated values
        """
        if self.tournament.tournament_format != "swiss_plus":
            raise ValueError("This method is only available for Swiss Pro format")

        split_data = self.get_split_counts_for_db()

        # Update tournament with split counts
        self.tournament.swiss_direct_count = split_data['direct_count']
        self.tournament.swiss_playoff_count = split_data['playoff_count']
        self.tournament.swiss_eliminated_count = split_data['eliminated_count']
        self.tournament.save()

        return split_data

    # ---------------------------
    # PLAYOFF GENERATION
    # ---------------------------
    def generate_playoff_fixtures(self) -> int:
        """
        Generate playoff fixtures (1st vs last, 2nd vs 2nd-last, etc.)
        Returns number of fixtures created.
        """
        if not self.tournament.split_phase_complete:
            raise ValueError("Must complete split phase first")

        # Get playoff teams from Group
        playoff_teams = []
        try:
            playoff_group = Group.objects.get(
                tournament=self.tournament,
                name='Playoff'
            )
            playoff_teams = list(playoff_group.teams.all())
        except Group.DoesNotExist:
            # Fallback: get from tournament split counts
            direct_count = self.tournament.swiss_direct_count or 0
            playoff_count = self.tournament.swiss_playoff_count or 0

            if playoff_count > 0:
                standings = self._calculate_standings_from_db()
                playoff_teams = [s['team'] for s in standings[direct_count:direct_count + playoff_count]]

        if len(playoff_teams) < 2:
            raise ValueError(f"Need at least 2 playoff teams. Found {len(playoff_teams)}")

        if len(playoff_teams) % 2 != 0:
            raise ValueError(f"Playoff teams must be even. Found {len(playoff_teams)}")

        # Get standings for seeding (using the SAME standings)
        standings = self._calculate_standings_from_db()
        playoff_team_ids = [t.id for t in playoff_teams]
        playoff_standings = [s for s in standings if s['team'].id in playoff_team_ids]

        # Pair: 1st vs last, 2nd vs 2nd-last, etc.
        pairs = []
        num_pairs = len(playoff_standings) // 2

        for i in range(num_pairs):
            home = playoff_standings[i]['team']
            away = playoff_standings[-(i + 1)]['team']
            pairs.append((home, away))

        # Get next round number
        max_round = Fixture.objects.filter(tournament=self.tournament).aggregate(
            Max('round')
        )['round__max'] or 0

        legs = self.config.get('playoff_legs', 2)
        fixtures_created = 0

        for leg in range(1, legs + 1):
            round_num = max_round + leg
            match_date = self._date_for_round(round_num, legs)

            for home, away in pairs:
                # Swap for second leg
                home_team = home
                away_team = away
                if leg == 2:
                    home_team, away_team = away_team, home_team

                Fixture.objects.create(
                    tournament=self.tournament,
                    home_team=home_team,
                    away_team=away_team,
                    match_date=match_date,
                    round=round_num,
                )
                fixtures_created += 1

        self.tournament.playoff_phase_complete = True
        self.tournament.save()

        return fixtures_created

    # ---------------------------
    # KNOCKOUT GENERATION - ONLY WHEN PLAYOFFS FINISHED
    # ---------------------------
    def generate_knockout_from_swiss(self) -> int:
        """
        Generate knockout bracket from direct qualifiers + playoff winners.
        ONLY generates when playoffs are complete.
        Returns number of fixtures created.
        """
        if not self.tournament.split_phase_complete:
            raise ValueError("Must complete split phase first")

        # Check if playoffs are required and if they're complete
        playoff_count = self.tournament.swiss_playoff_count or 0

        if playoff_count > 0:
            # Check if playoffs are complete
            swiss_rounds = self.tournament.swiss_total_rounds or 0

            # Count pending playoff fixtures
            pending_playoffs = Fixture.objects.filter(
                tournament=self.tournament,
                round__gt=swiss_rounds,
                is_played=False
            ).exclude(away_team__isnull=True).count()

            if pending_playoffs > 0:
                raise ValueError(f"Cannot generate knockout: {pending_playoffs} playoff fixture(s) still need results")

            # Check if all playoff fixtures are played
            total_playoffs = Fixture.objects.filter(
                tournament=self.tournament,
                round__gt=swiss_rounds
            ).exclude(away_team__isnull=True).count()

            played_playoffs = Fixture.objects.filter(
                tournament=self.tournament,
                round__gt=swiss_rounds,
                is_played=True
            ).exclude(away_team__isnull=True).count()

            if total_playoffs > 0 and played_playoffs < total_playoffs:
                raise ValueError(f"Playoffs not complete: {played_playoffs}/{total_playoffs} played")

        # Get direct qualifiers
        try:
            direct_group = Group.objects.get(
                tournament=self.tournament,
                name='Direct Qualifiers'
            )
        except Group.DoesNotExist:
            raise ValueError("No direct qualifiers found")

        direct_teams = list(direct_group.teams.all())

        # Get playoff winners (teams that won their playoff fixtures)
        playoff_winners = []
        if playoff_count > 0:
            playoff_winners = self._get_playoff_winners()

        # Combine all teams
        all_teams = direct_teams + playoff_winners

        if len(all_teams) < 2:
            raise ValueError("Need at least 2 teams for knockout")

        # Get standings for seeding (using the SAME standings)
        standings = self._calculate_standings_from_db()
        team_ids = [t.id for t in all_teams]
        ranked_teams = [s['team'] for s in standings if s['team'].id in team_ids]

        # Ensure power of 2
        size = self._next_power_of_two(len(ranked_teams))
        # Add byes (None) if needed
        teams_with_byes = ranked_teams + [None] * (size - len(ranked_teams))

        # Seed: 1st vs last, 2nd vs 2nd-last
        matchups = []
        n = len(teams_with_byes)
        for i in range(n // 2):
            home = teams_with_byes[i]
            away = teams_with_byes[n - 1 - i]
            matchups.append((home, away))

        # Get next round number
        max_round = Fixture.objects.filter(tournament=self.tournament).aggregate(
            Max('round')
        )['round__max'] or 0

        round_num = max_round + 1
        match_date = self._date_for_round(round_num, 1)

        fixtures_created = 0
        for home, away in matchups:
            if home is None or away is None:
                continue  # Skip byes
            Fixture.objects.create(
                tournament=self.tournament,
                home_team=home,
                away_team=away,
                match_date=match_date,
                round=round_num,
            )
            fixtures_created += 1

        self.tournament.knockout_phase_complete = True
        self.tournament.save()

        return fixtures_created

    # ---------------------------
    # HELPER METHODS
    # ---------------------------

    def _get_engine_teams(self) -> List[Dict]:
        """Convert Django Team objects to engine Team objects."""
        teams = Team.objects.filter(tournament=self.tournament)
        return [{'id': team.id, 'name': team.name} for team in teams]

    def _get_engine_results(self) -> List[Dict]:
        """Convert Django Results to engine result format."""
        results = Result.objects.filter(
            fixture__tournament=self.tournament
        ).select_related('fixture')

        engine_results = []
        for result in results:
            fixture = result.fixture
            engine_fixture = EngineFixture(
                home_team_id=fixture.home_team_id,
                away_team_id=fixture.away_team_id,
                round=fixture.round,
                match_date=fixture.match_date.date() if fixture.match_date else date.today()
            )
            engine_results.append({
                'fixture': engine_fixture,
                'home_score': result.home_score,
                'away_score': result.away_score
            })
        return engine_results

    def _save_engine_fixtures(self, engine_fixtures: List[EngineFixture], group: Group = None):
        """Save engine fixtures to database."""
        for eng_fixture in engine_fixtures:
            if eng_fixture.away_team_id is None:
                # Bye - no fixture needed
                continue

            Fixture.objects.create(
                tournament=self.tournament,
                home_team_id=eng_fixture.home_team_id,
                away_team_id=eng_fixture.away_team_id,
                group=group,
                match_date=eng_fixture.match_date,
                round=eng_fixture.round,
            )

    def _rebuild_engine(self) -> SwissPairingEngine:
        """Rebuild the engine from current database state."""
        engine_teams = self._get_engine_teams()

        config = {
            'start_date': self.start_date.isoformat(),
            'end_date': self.end_date.isoformat(),
            'num_rounds': self.tournament.swiss_total_rounds or 5,
            'direct_percent': 25,
            'playoff_percent': 50,
        }

        engine = SwissPairingEngine(engine_teams, config)

        # Rebuild fixtures
        fixtures = Fixture.objects.filter(
            tournament=self.tournament
        ).select_related('home_team', 'away_team').order_by('round')

        for fixture in fixtures:
            if fixture.away_team:
                engine_fixture = EngineFixture(
                    home_team_id=fixture.home_team_id,
                    away_team_id=fixture.away_team_id,
                    round=fixture.round,
                    match_date=fixture.match_date.date() if fixture.match_date else date.today()
                )
                engine.fixtures.append(engine_fixture)
                engine.played_pairs.add(frozenset({fixture.home_team_id, fixture.away_team_id}))
            else:
                # Bye
                engine.bye_teams.add(fixture.home_team_id)

        return engine

    def _get_playoff_winners(self) -> List[Team]:
        """Determine which teams won their playoff fixtures."""
        swiss_rounds = self.tournament.swiss_total_rounds or 0

        playoff_fixtures = Fixture.objects.filter(
            tournament=self.tournament,
            round__gt=swiss_rounds,
            is_played=True
        ).select_related('result', 'home_team', 'away_team')

        winners = []
        processed = set()

        for fixture in playoff_fixtures:
            key = frozenset({fixture.home_team_id, fixture.away_team_id})
            if key in processed:
                continue
            processed.add(key)

            # Get all fixtures for this tie (legs)
            tie_fixtures = Fixture.objects.filter(
                tournament=self.tournament,
                round__in=[fixture.round, fixture.round + 1] if fixture.round % 2 == 1 else [fixture.round - 1,
                                                                                             fixture.round],
                home_team__in=[fixture.home_team, fixture.away_team],
                away_team__in=[fixture.home_team, fixture.away_team]
            ).select_related('result')

            # Calculate aggregate
            home_goals = 0
            away_goals = 0

            for f in tie_fixtures:
                if hasattr(f, 'result') and f.result:
                    if f.home_team == fixture.home_team:
                        home_goals += f.result.home_score
                        away_goals += f.result.away_score
                    else:
                        home_goals += f.result.away_score
                        away_goals += f.result.home_score

            # Determine winner
            if home_goals > away_goals:
                winners.append(fixture.home_team)
            elif home_goals < away_goals:
                winners.append(fixture.away_team)
            else:
                # Draw - higher seed (better Swiss rank) advances
                standings = self._calculate_standings_from_db()
                home_rank = next((i for i, s in enumerate(standings) if s['team'].id == fixture.home_team.id), 999)
                away_rank = next((i for i, s in enumerate(standings) if s['team'].id == fixture.away_team.id), 999)
                winners.append(fixture.home_team if home_rank < away_rank else fixture.away_team)

        return winners

    # ---------------------------
    # STANDINGS - SINGLE SOURCE OF TRUTH
    # ---------------------------
    def _calculate_standings_from_db(self) -> List[Dict]:
        """
        Calculate standings directly from database.
        THIS IS THE SINGLE SOURCE OF TRUTH for both the dashboard and split logic.
        """
        points = defaultdict(int)
        goals_for = defaultdict(int)
        goals_against = defaultdict(int)

        fixtures = Fixture.objects.filter(
            tournament=self.tournament,
            is_played=True
        ).select_related('result')

        for fixture in fixtures:
            if not hasattr(fixture, 'result'):
                continue
            result = fixture.result
            home_id = fixture.home_team_id
            away_id = fixture.away_team_id

            if result.home_score > result.away_score:
                points[home_id] += 3
            elif result.home_score < result.away_score:
                points[away_id] += 3
            else:
                points[home_id] += 1
                points[away_id] += 1

            goals_for[home_id] += result.home_score
            goals_for[away_id] += result.away_score
            goals_against[home_id] += result.away_score
            goals_against[away_id] += result.home_score

        # Buchholz - sum of opponents' points
        buchholz = defaultdict(int)
        teams = Team.objects.filter(tournament=self.tournament)

        for team in teams:
            total = 0
            team_fixtures = Fixture.objects.filter(
                tournament=self.tournament,
                is_played=True
            ).filter(Q(home_team=team) | Q(away_team=team))

            for f in team_fixtures:
                opp_id = f.away_team_id if f.home_team_id == team.id else f.home_team_id
                total += points.get(opp_id, 0)

            buchholz[team.id] = total

        # Build standings
        standings = []
        for team in teams:
            gd = goals_for.get(team.id, 0) - goals_against.get(team.id, 0)
            standings.append({
                'team': team,
                'points': points.get(team.id, 0),
                'buchholz': buchholz.get(team.id, 0),
                'goal_diff': gd,
                'goals_for': goals_for.get(team.id, 0),
                'goals_against': goals_against.get(team.id, 0)
            })

        # Sort: Points desc → Buchholz desc → Goal Diff desc
        standings.sort(key=lambda x: (-x['points'], -x['buchholz'], -x['goal_diff']))
        return standings

    # ---------------------------
    # SWISS HELPERS
    # ---------------------------

    def _recommended_swiss_rounds(self, num_teams: int) -> int:
        """Calculate recommended number of Swiss rounds."""
        if num_teams <= 2:
            return 1
        max_possible = num_teams - 1
        if num_teams <= 6:
            return max_possible
        suggested = max(4, math.ceil(math.log2(num_teams)) + 2)
        return min(suggested, max_possible)

    # ---------------------------
    # GENERAL HELPERS
    # ---------------------------

    def _circle_round_robin(self, teams, double=False):
        """Standard circle method for round robin."""
        working = list(teams)
        if len(working) % 2 == 1:
            working.append(None)

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
            rotation = [rotation[0]] + [rotation[-1]] + rotation[1:-1]

        if double:
            second_leg = [
                [(away, home) for home, away in round_matches]
                for round_matches in rounds
            ]
            rounds += second_leg

        return rounds

    def _next_power_of_two(self, n: int) -> int:
        """Find the next power of 2 >= n."""
        if n <= 0:
            return 1
        power = 1
        while power < n:
            power *= 2
        return power

    def _prev_power_of_two(self, n: int) -> int:
        """Find the previous power of 2 <= n."""
        if n <= 1:
            return 1
        power = 1
        while power * 2 <= n:
            power *= 2
        return power