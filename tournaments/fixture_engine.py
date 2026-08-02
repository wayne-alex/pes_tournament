# fixture_engine.py
import random
import math
from datetime import date, timedelta
from typing import List, Dict, Optional, Tuple, Set, Any
from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class Team:
    """Pure representation of a team."""
    id: Any  # Can be int, str, or any identifier
    name: str
    seed: Optional[float] = None  # For seeding if needed


@dataclass
class Fixture:
    """Pure representation of a fixture."""
    home_team_id: Any
    away_team_id: Optional[Any]  # None = bye
    round: int
    match_date: date
    group_name: Optional[str] = None
    is_playoff: bool = False
    is_knockout: bool = False
    tie_id: Optional[int] = None  # For 2-leg playoff ties


@dataclass
class TournamentStructure:
    """Complete tournament structure returned by the generator."""
    format: str
    rounds: List[List[Fixture]]  # Each round is a list of fixtures
    total_rounds: int
    teams: List[Team]

    # Swiss-specific
    swiss_rounds_total: Optional[int] = None

    # Split-specific
    direct_qualifiers: Optional[List[Team]] = None
    playoff_teams: Optional[List[Team]] = None
    eliminated_teams: Optional[List[Team]] = None

    # Playoff-specific
    playoff_pairs: Optional[List[Tuple[Team, Team]]] = None

    # Knockout-specific
    knockout_bracket: Optional[List[Tuple[Team, Team]]] = None


class SwissPairingEngine:
    """
    Pure Swiss pairing engine with no database dependencies.
    Works entirely with Team objects and Fixture data.
    """

    def __init__(self, teams: List[Dict], config: Dict):
        """
        Initialize the engine.

        Args:
            teams: List of team dicts with at least {'id': ..., 'name': ...}
            config: Configuration dict with keys like:
                - start_date: '2024-01-01'
                - end_date: '2024-01-31'
                - num_rounds: 5 (optional, auto-calculated if not provided)
                - direct_percent: 25
                - playoff_percent: 50
                - playoff_legs: 2
                - format: 'swiss_plus'
        """
        self.teams = [Team(**t) if isinstance(t, dict) else t for t in teams]
        self.config = config
        self.start_date = date.fromisoformat(config.get("start_date"))
        self.end_date = date.fromisoformat(config.get("end_date"))
        self.team_count = len(self.teams)

        # State for Swiss pairing
        self.fixtures: List[Fixture] = []
        self.played_pairs: Set[frozenset] = set()
        self.bye_teams: Set[Any] = set()
        self.current_round = 0

        # Results storage (external system will provide these)
        self.results: Dict[Tuple[int, int], Dict] = {}  # (round, fixture_index) -> result

        # Tournament structure
        self.structure = TournamentStructure(
            format=config.get("format", "swiss"),
            rounds=[],
            total_rounds=0,
            teams=self.teams
        )

    # ============================================================
    # MAIN GENERATION METHODS
    # ============================================================

    def generate_swiss_round_one(self) -> TournamentStructure:
        """Generate Round 1 of Swiss tournament."""
        if self.team_count < 2:
            raise ValueError("Need at least 2 teams for Swiss")

        # Calculate number of Swiss rounds
        num_rounds = self.config.get("num_rounds") or self._recommended_swiss_rounds()
        self.structure.swiss_rounds_total = num_rounds

        # Shuffle teams
        shuffled_teams = self._shuffle_teams()

        # Pair for round 1
        pairs, bye_team = self._pair_teams(
            shuffled_teams,
            played_pairs=set(),
            byes_taken=set()
        )

        # Create fixtures
        match_date = self._date_for_round(1, num_rounds)
        fixtures = self._create_fixtures(pairs, 1, match_date, bye_team)

        # Store state
        self.fixtures = fixtures
        self._update_state(fixtures)

        # Build structure
        self.structure.rounds = [fixtures]
        self.structure.total_rounds = num_rounds

        return self.structure

    def generate_next_swiss_round(self, round_num: int, results: List[Dict]) -> TournamentStructure:
        """
        Generate the next Swiss round based on results from previous rounds.

        Args:
            round_num: The round number to generate (e.g., 2, 3, 4...)
            results: List of result dicts for ALL completed fixtures so far:
                [
                    {'fixture': fixture, 'home_score': 2, 'away_score': 1},
                    ...
                ]
        """
        # Store results
        self._store_results(results)

        # Check if Swiss phase is complete
        if self.structure.swiss_rounds_total and round_num > self.structure.swiss_rounds_total:
            raise ValueError(f"Swiss phase only runs {self.structure.swiss_rounds_total} rounds")

        # Get standings
        standings = self._calculate_standings()
        ordered_teams = [team for team, _ in standings]

        # Get played pairs and byes
        played_pairs = self._get_played_pairs()
        byes_taken = self._get_bye_teams()

        # Pair teams
        pairs, bye_team = self._pair_teams(
            ordered_teams,
            played_pairs=played_pairs,
            byes_taken=byes_taken
        )

        # Create fixtures
        match_date = self._date_for_round(
            round_num,
            self.structure.swiss_rounds_total or round_num
        )
        fixtures = self._create_fixtures(pairs, round_num, match_date, bye_team)

        # Update state
        self.fixtures.extend(fixtures)
        self._update_state(fixtures)

        # Add to structure
        self.structure.rounds.append(fixtures)
        self.structure.total_rounds = max(self.structure.total_rounds, round_num)

        return self.structure

    def generate_swiss_split(self, results: List[Dict]) -> TournamentStructure:
        """
        Rank all teams and split into Direct / Playoff / Eliminated.
        Call this after all Swiss rounds are complete.
        """
        # Store all results
        self._store_results(results)

        # Calculate standings with Buchholz
        standings = self._calculate_standings_with_buchholz()

        # Calculate split
        total = len(standings)
        direct_count, playoff_count, eliminated_count = self._calculate_split(total)

        # Split the teams
        direct_teams = [s['team'] for s in standings[:direct_count]]
        playoff_teams = [s['team'] for s in standings[direct_count:direct_count + playoff_count]]
        eliminated_teams = [s['team'] for s in standings[direct_count + playoff_count:]]

        # Store in structure
        self.structure.direct_qualifiers = direct_teams
        self.structure.playoff_teams = playoff_teams
        self.structure.eliminated_teams = eliminated_teams

        return self.structure

    def generate_playoff_fixtures(self, results: Optional[List[Dict]] = None) -> TournamentStructure:
        """
        Generate playoff fixtures (1st vs last, 2nd vs 2nd-last, etc.)
        Call this after split is complete.
        """
        if not self.structure.playoff_teams or len(self.structure.playoff_teams) < 2:
            raise ValueError("Need at least 2 playoff teams")

        playoff_teams = self.structure.playoff_teams
        if len(playoff_teams) % 2 != 0:
            raise ValueError("Playoff teams must be even")

        # Get standings for seeding
        standings = self._calculate_standings_with_buchholz()
        playoff_standings = [s for s in standings if s['team'] in playoff_teams]

        # Pair: 1st vs last, 2nd vs 2nd-last, etc.
        pairs = []
        tie_id = 1
        for i in range(len(playoff_standings) // 2):
            home = playoff_standings[i]['team']
            away = playoff_standings[-(i + 1)]['team']
            pairs.append((home, away, tie_id))
            tie_id += 1

        self.structure.playoff_pairs = [(h, a) for h, a, _ in pairs]

        # Generate fixtures for the playoff round(s)
        legs = self.config.get("playoff_legs", 2)
        next_round = self._get_next_round_number()

        fixtures = []
        for leg in range(1, legs + 1):
            round_num = next_round + leg - 1
            match_date = self._date_for_round(round_num, legs)

            for home, away, tie_id in pairs:
                # Swap home/away for second leg
                if leg == 2:
                    home, away = away, home

                fixture = Fixture(
                    home_team_id=home.id,
                    away_team_id=away.id,
                    round=round_num,
                    match_date=match_date,
                    is_playoff=True,
                    tie_id=tie_id
                )
                fixtures.append(fixture)

        # Add to structure
        self.structure.rounds.append(fixtures)
        self.fixtures.extend(fixtures)

        return self.structure

    def generate_knockout(self, playoff_winners: List[Team]) -> TournamentStructure:
        """
        Generate knockout bracket from direct qualifiers and playoff winners.
        """
        if not self.structure.direct_qualifiers:
            raise ValueError("No direct qualifiers found")

        # Combine direct qualifiers + playoff winners
        all_teams = self.structure.direct_qualifiers + playoff_winners

        # Sort by seed (Swiss ranking)
        standings = self._calculate_standings_with_buchholz()
        ranked_teams = []
        for s in standings:
            if s['team'] in all_teams:
                ranked_teams.append(s['team'])

        # Generate seeded knockout bracket
        bracket = self._generate_seeded_bracket(ranked_teams)
        self.structure.knockout_bracket = bracket

        # Create fixtures
        next_round = self._get_next_round_number()
        match_date = self._date_for_round(next_round, 1)

        fixtures = []
        for home, away in bracket:
            if home and away:
                fixture = Fixture(
                    home_team_id=home.id,
                    away_team_id=away.id,
                    round=next_round,
                    match_date=match_date,
                    is_knockout=True
                )
                fixtures.append(fixture)

        self.structure.rounds.append(fixtures)
        self.fixtures.extend(fixtures)

        return self.structure

    # ============================================================
    # CORE PAIRING LOGIC
    # ============================================================

    def _pair_teams(self, ordered_teams: List[Team],
                    played_pairs: Set[frozenset],
                    byes_taken: Set[Any]) -> Tuple[List[Tuple[Team, Team]], Optional[Team]]:
        """
        Pair teams using Swiss system.
        Returns: (pairs, bye_team)
        """
        teams = list(ordered_teams)
        bye_team = None

        # Handle odd number of teams
        if len(teams) % 2 == 1:
            # Prefer a team that hasn't had a bye yet
            for team in reversed(teams):
                if team.id not in byes_taken:
                    bye_team = team
                    break
            if bye_team is None:
                bye_team = teams[-1]  # Last resort: lowest ranked team gets bye
            teams.remove(bye_team)

        # Pair teams
        pairs = []
        unpaired = teams[:]

        while unpaired:
            current = unpaired.pop(0)
            opponent = self._find_opponent(current, unpaired, played_pairs)
            unpaired.remove(opponent)
            pairs.append((current, opponent))

        return pairs, bye_team

    def _find_opponent(self, team: Team, candidates: List[Team],
                       played_pairs: Set[frozenset]) -> Team:
        """
        Find the best opponent for a team.
        Prefer opponents they haven't played.
        """
        for opponent in candidates:
            pair_key = frozenset({team.id, opponent.id})
            if pair_key not in played_pairs:
                return opponent

        # Everyone left has played this team - fallback to closest ranked
        return candidates[0]

    def _generate_seeded_bracket(self, seeded_teams: List[Team]) -> List[Tuple[Team, Team]]:
        """
        Generate a seeded knockout bracket.
        1st plays lowest seed, 2nd plays 2nd lowest, etc.
        """
        size = self._next_power_of_two(len(seeded_teams))
        teams = seeded_teams + [None] * (size - len(seeded_teams))

        matchups = []
        n = len(teams)
        for i in range(n // 2):
            home = teams[i]
            away = teams[n - 1 - i]
            matchups.append((home, away))

        return matchups

    # ============================================================
    # STANDINGS & RANKING
    # ============================================================

    def _calculate_standings(self) -> List[Tuple[Team, int]]:
        """
        Calculate simple standings (points only).
        Returns: [(team, points), ...] sorted by points descending.
        """
        points = self._calculate_points()
        ranked = sorted(
            [(team, points.get(team.id, 0)) for team in self.teams],
            key=lambda x: x[1],
            reverse=True
        )
        return ranked

    def _calculate_standings_with_buchholz(self) -> List[Dict]:
        """
        Calculate standings with Buchholz tiebreaker.
        Returns: [{'team': Team, 'points': int, 'buchholz': int, 'goal_diff': int}, ...]
        """
        # Calculate points and goals
        points = defaultdict(int)
        goals_for = defaultdict(int)
        goals_against = defaultdict(int)

        for fixture in self.fixtures:
            result = self._get_fixture_result(fixture)
            if not result:
                continue

            home_id = fixture.home_team_id
            away_id = fixture.away_team_id

            if home_id is None or away_id is None:
                continue

            gf = result['home_score']
            ga = result['away_score']

            if gf > ga:
                points[home_id] += 3
            elif gf < ga:
                points[away_id] += 3
            else:
                points[home_id] += 1
                points[away_id] += 1

            goals_for[home_id] += gf
            goals_for[away_id] += ga
            goals_against[home_id] += ga
            goals_against[away_id] += gf

        # Calculate Buchholz
        buchholz = defaultdict(int)
        for team in self.teams:
            total = 0
            for fixture in self.fixtures:
                if fixture.home_team_id == team.id:
                    opp_id = fixture.away_team_id
                elif fixture.away_team_id == team.id:
                    opp_id = fixture.home_team_id
                else:
                    continue

                if opp_id is not None:
                    total += points.get(opp_id, 0)

            buchholz[team.id] = total

        # Build standings
        standings = []
        for team in self.teams:
            team_id = team.id
            gd = goals_for.get(team_id, 0) - goals_against.get(team_id, 0)
            standings.append({
                'team': team,
                'points': points.get(team_id, 0),
                'buchholz': buchholz.get(team_id, 0),
                'goal_diff': gd,
                'goals_for': goals_for.get(team_id, 0),
                'goals_against': goals_against.get(team_id, 0)
            })

        # Sort: Points desc → Buchholz desc → Goal Diff desc
        standings.sort(
            key=lambda x: (-x['points'], -x['buchholz'], -x['goal_diff'])
        )

        return standings

    def _calculate_points(self) -> Dict[Any, int]:
        """Calculate points for all teams."""
        points = defaultdict(int)

        for fixture in self.fixtures:
            result = self._get_fixture_result(fixture)
            if not result:
                continue

            home_id = fixture.home_team_id
            away_id = fixture.away_team_id

            if home_id is None or away_id is None:
                continue

            if result['home_score'] > result['away_score']:
                points[home_id] += 3
            elif result['home_score'] < result['away_score']:
                points[away_id] += 3
            else:
                points[home_id] += 1
                points[away_id] += 1

        return points

    # ============================================================
    # SPLIT LOGIC
    # ============================================================

    def _calculate_split(self, total_teams: int) -> Tuple[int, int, int]:
        """
        Calculate split based on percentages.
        Returns: (direct_count, playoff_count, eliminated_count)
        """
        direct_pct = self.config.get("direct_percent", 25)
        playoff_pct = self.config.get("playoff_percent", 50)

        # Raw counts - round properly
        direct_raw = int(round(total_teams * direct_pct / 100))
        playoff_raw = int(round(total_teams * playoff_pct / 100))

        # Ensure minimums
        direct_raw = max(1, direct_raw)
        playoff_raw = max(0, playoff_raw)

        # Round direct to nearest power of 2 (rounding down)
        direct_count = self._prev_power_of_two(direct_raw) if direct_raw > 1 else 1

        # Make playoff even
        playoff_count = playoff_raw if playoff_raw % 2 == 0 else playoff_raw - 1

        # Ensure playoff is at least 2 if there are enough teams
        if playoff_count < 2 and total_teams - direct_count >= 2:
            playoff_count = 2

        # Ensure direct + playoff doesn't exceed total
        if direct_count + playoff_count > total_teams:
            playoff_count = total_teams - direct_count
            if playoff_count % 2 != 0:
                playoff_count -= 1
            if playoff_count < 0:
                playoff_count = 0

        # Calculate eliminated
        eliminated_count = total_teams - direct_count - playoff_count

        return direct_count, playoff_count, eliminated_count

    # ============================================================
    # FIXTURE HELPERS
    # ============================================================

    def _create_fixtures(self, pairs: List[Tuple[Team, Team]],
                         round_num: int,
                         match_date: date,
                         bye_team: Optional[Team] = None) -> List[Fixture]:
        """Create fixture objects from pairs."""
        fixtures = []

        for home, away in pairs:
            fixtures.append(Fixture(
                home_team_id=home.id,
                away_team_id=away.id,
                round=round_num,
                match_date=match_date
            ))

        if bye_team:
            fixtures.append(Fixture(
                home_team_id=bye_team.id,
                away_team_id=None,  # Bye
                round=round_num,
                match_date=match_date
            ))

        return fixtures

    def _update_state(self, fixtures: List[Fixture]):
        """Update internal state with new fixtures."""
        for fixture in fixtures:
            if fixture.home_team_id is not None and fixture.away_team_id is not None:
                self.played_pairs.add(frozenset({fixture.home_team_id, fixture.away_team_id}))

            if fixture.away_team_id is None:  # Bye
                self.bye_teams.add(fixture.home_team_id)

        if fixtures:
            self.current_round = max(fixture.round for fixture in fixtures)

    def _get_played_pairs(self) -> Set[frozenset]:
        """Get all played pairs."""
        return self.played_pairs.copy()

    def _get_bye_teams(self) -> Set[Any]:
        """Get teams that have had a bye."""
        return self.bye_teams.copy()

    def _get_next_round_number(self) -> int:
        """Get the next available round number."""
        if not self.fixtures:
            return 1
        return max(f.round for f in self.fixtures) + 1

    def _get_fixture_result(self, fixture: Fixture) -> Optional[Dict]:
        """Get result for a fixture from stored results."""
        # Find result by matching home and away teams and round
        for key, result in self.results.items():
            # key is (round, fixture_id) but we need to match by teams
            pass

        # Alternative: store results with fixture reference
        return self.results.get((fixture.round, fixture.home_team_id, fixture.away_team_id))

    def _store_results(self, results: List[Dict]):
        """Store results for fixtures."""
        for result in results:
            fixture = result.get('fixture')
            if fixture:
                key = (fixture.round, fixture.home_team_id, fixture.away_team_id)
                self.results[key] = {
                    'home_score': result.get('home_score', 0),
                    'away_score': result.get('away_score', 0)
                }

    # ============================================================
    # DATE HELPERS
    # ============================================================

    def _date_for_round(self, round_num: int, total_rounds: int) -> date:
        """Calculate date for a round."""
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

    # ============================================================
    # MATH HELPERS - ALL FUNCTIONS INCLUDED
    # ============================================================

    def _recommended_swiss_rounds(self) -> int:
        """Calculate recommended number of Swiss rounds."""
        n = self.team_count

        if n <= 2:
            return 1

        max_possible = n - 1  # Full round robin

        if n <= 6:
            return max_possible

        # UEFA-style: log2(n) + 2, but don't exceed full round robin
        suggested = max(4, math.ceil(math.log2(n)) + 2)
        return min(suggested, max_possible)

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

    def _shuffle_teams(self) -> List[Team]:
        """Shuffle teams."""
        teams = self.teams.copy()
        random.shuffle(teams)
        return teams

    # ============================================================
    # UTILITY METHODS
    # ============================================================

    def get_round_fixtures(self, round_num: int) -> List[Fixture]:
        """Get fixtures for a specific round."""
        return [f for f in self.fixtures if f.round == round_num]

    def get_team_fixtures(self, team_id: Any) -> List[Fixture]:
        """Get all fixtures for a specific team."""
        return [
            f for f in self.fixtures
            if f.home_team_id == team_id or f.away_team_id == team_id
        ]

    def get_fixture_count(self) -> int:
        """Get total number of fixtures generated."""
        return len(self.fixtures)

    def get_round_count(self) -> int:
        """Get the number of rounds generated."""
        if not self.fixtures:
            return 0
        return max(f.round for f in self.fixtures)