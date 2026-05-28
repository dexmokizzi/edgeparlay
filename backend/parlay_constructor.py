"""
EdgeParlay Constructor v2
Upgraded with:
- Max 4 legs hard limit
- Max 2 legs per sport (cross-sport diversification)
- Min 55% combined parlay probability
- Straight bet option when parlay probability too low
- Better EV calculation with realistic assumptions
- CST timezone aware
"""
import os
import numpy as np
from datetime import datetime, timezone
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

TARGET_ODDS_MIN = float(os.getenv('TARGET_ODDS_MIN', 3.0))
TARGET_ODDS_MAX = float(os.getenv('TARGET_ODDS_MAX', 3.8))
MIN_PARLAY_PROBABILITY = 0.55  # Never bet a parlay with less than 55% chance
MAX_LEGS = 4                    # Hard cap - no more 6-leg disasters
MAX_LEGS_PER_SPORT = 2         # Max 2 legs from same sport


def american_to_decimal(american: int) -> float:
    if american > 0:
        return 1 + (american / 100)
    return 1 - (100 / american)


def combine_odds(legs: list) -> float:
    combined = 1.0
    for leg in legs:
        combined *= leg.get('odds_decimal', 1.0)
    return round(combined, 4)


def parlay_probability(legs: list) -> float:
    prob = 1.0
    for leg in legs:
        prob *= leg.get('combined_confidence', 0.65)
    return round(prob, 4)


def calculate_ev(combined_odds: float, prob: float, stake: float) -> float:
    profit = stake * (combined_odds - 1)
    ev = (prob * profit) - ((1 - prob) * stake)
    return round(ev, 4)


def sports_in_parlay(legs: list) -> dict:
    """Count legs per sport"""
    counts = {}
    for leg in legs:
        sport = leg.get('sport', 'Unknown')
        counts[sport] = counts.get(sport, 0) + 1
    return counts


def violates_sport_limit(legs: list, candidate: dict) -> bool:
    """Check if adding candidate would exceed max legs per sport"""
    sport = candidate.get('sport', 'Unknown')
    current_count = sum(1 for l in legs if l.get('sport') == sport)
    return current_count >= MAX_LEGS_PER_SPORT


def are_correlated(leg1: dict, leg2: dict) -> bool:
    """Check if two legs are from same event"""
    if leg1.get('event_id') and leg1.get('event_id') == leg2.get('event_id'):
        return True
    if leg1.get('event_name') and leg1.get('event_name') == leg2.get('event_name'):
        return True
    return False


def check_all_correlations(legs: list) -> bool:
    """Ensure no two legs are correlated"""
    for i in range(len(legs)):
        for j in range(i + 1, len(legs)):
            if are_correlated(legs[i], legs[j]):
                return False
    return True


class ParlayConstructor:

    def __init__(self, bankroll: float = 100.0):
        self.bankroll = bankroll
        self.base_stake = float(os.getenv('BASE_STAKE', 10))

    def build_optimal_parlay(self, scored: list) -> Optional[dict]:
        """
        Build the optimal parlay with strict rules:
        1. Max 4 legs
        2. Max 2 legs per sport
        3. Min 55% combined probability
        4. Target 3.0-3.8 combined odds
        5. Only GREEN tier legs preferred, AMBER as fallback
        """
        if not scored:
            return None

        # Prefer GREEN legs, fall back to AMBER if needed
        green = [o for o in scored if o.get('confidence_tier') == 'GREEN']
        amber = [o for o in scored if o.get('confidence_tier') == 'AMBER']
        all_opps = green + amber

        if not all_opps:
            return None

        # Try to build parlay with 2, 3, then 4 legs max
        best_parlay = None
        best_score = -999

        for target_n in range(2, MAX_LEGS + 1):
            # Greedy construction: start with highest confidence
            parlay_legs = []

            for candidate in all_opps:
                if len(parlay_legs) >= target_n:
                    break

                # Skip if violates sport limit
                if violates_sport_limit(parlay_legs, candidate):
                    continue

                # Skip if correlated with existing legs
                if not check_all_correlations(parlay_legs + [candidate]):
                    continue

                parlay_legs.append(candidate)

            if len(parlay_legs) < 2:
                continue

            # Calculate parlay stats
            combined = combine_odds(parlay_legs)
            prob = parlay_probability(parlay_legs)
            ev = calculate_ev(combined, prob, self.base_stake)
            payout = round(self.base_stake * combined, 2)

            # Score this parlay: EV * probability (reward both edge AND hit rate)
            score = ev * prob

            # Check minimum probability requirement
            if prob < MIN_PARLAY_PROBABILITY:
                continue

            # Check odds range
            in_range = TARGET_ODDS_MIN <= combined <= TARGET_ODDS_MAX

            if in_range and score > best_score:
                best_score = score
                best_parlay = {
                    'legs': parlay_legs,
                    'combined_odds': combined,
                    'parlay_probability': prob,
                    'ev': ev,
                    'stake': self.base_stake,
                    'potential_payout': payout,
                    'num_legs': len(parlay_legs),
                    'bet_type': 'parlay',
                    'in_target_range': True
                }

        # If no parlay meets all criteria, consider straight bet on best pick
        if not best_parlay:
            best_parlay = self._build_straight_bet(all_opps)

        if not best_parlay:
            return None

        # Final metadata
        legs = best_parlay['legs']
        avg_conf = np.mean([l['combined_confidence'] for l in legs])

        if avg_conf >= 0.67:
            tier = 'GREEN'
        elif avg_conf >= 0.60:
            tier = 'AMBER'
        else:
            return None  # Not confident enough

        # Best platform
        platform_counts = {}
        for leg in legs:
            book = leg.get('bookmaker', 'FanDuel')
            platform_counts[book] = platform_counts.get(book, 0) + 1
        platform = max(platform_counts, key=platform_counts.get)

        value_bets = [l for l in legs if l.get('is_value_bet', False)]
        sports_used = list(sports_in_parlay(legs).keys())
        danger_count = sum(len(l.get('danger_flags', [])) for l in legs)

        return {
            **best_parlay,
            'date': datetime.now().strftime('%Y-%m-%d'),
            'confidence_tier': tier,
            'avg_confidence': round(float(avg_conf), 4),
            'value_anchor': legs[0]['selection'],
            'platform': platform,
            'value_bets_count': len(value_bets),
            'sports_covered': sports_used,
            'danger_flag_count': danger_count,
            'stake': self.base_stake,
            'regime': scored[0].get('regime', 'normal') if scored else 'normal',
            'created_at': datetime.now(timezone.utc).isoformat()
        }

    def _build_straight_bet(self, all_opps: list) -> Optional[dict]:
        """Fall back to single straight bet on highest confidence pick"""
        if not all_opps:
            return None

        # Only consider GREEN tier for straight bets
        green_opps = [o for o in all_opps if o.get('confidence_tier') == 'GREEN']
        if not green_opps:
            return None

        best = green_opps[0]
        odds = best.get('odds_decimal', 1.5)
        prob = best.get('combined_confidence', 0.65)
        ev = calculate_ev(odds, prob, self.base_stake)

        if ev <= 0:
            return None

        return {
            'legs': [best],
            'combined_odds': odds,
            'parlay_probability': prob,
            'ev': ev,
            'stake': self.base_stake,
            'potential_payout': round(self.base_stake * odds, 2),
            'num_legs': 1,
            'bet_type': 'straight',
            'in_target_range': False
        }

    def should_bet_today(self, parlay: Optional[dict]) -> tuple:
        if not parlay:
            return False, "No qualifying opportunities found. Protecting bankroll."

        if parlay['confidence_tier'] == 'RED':
            return False, "Confidence too low. Skipping today."

        if parlay['ev'] < 0:
            return False, f"Negative EV (${parlay['ev']:.2f}). No bet today."

        if parlay['num_legs'] < 1:
            return False, "Could not build any qualifying bet."

        # Additional check: parlay probability must be above threshold
        if parlay.get('parlay_probability', 0) < MIN_PARLAY_PROBABILITY:
            return False, f"Parlay probability {parlay['parlay_probability']:.1%} below minimum {MIN_PARLAY_PROBABILITY:.0%}. No bet."

        bet_type = parlay.get('bet_type', 'parlay')
        return True, f"{parlay['confidence_tier']} {bet_type} identified. Bet recommended."

    def format_parlay_summary(self, parlay: dict) -> str:
        tier_emoji = '🟢' if parlay['confidence_tier'] == 'GREEN' else '🟡'
        bet_type = parlay.get('bet_type', 'parlay').upper()
        sports = ', '.join(parlay.get('sports_covered', []))
        lines = [
            f"\n{'='*60}",
            f"{tier_emoji} TODAY'S EDGE{bet_type} — {parlay['confidence_tier']}",
            f"{'='*60}",
            f"Date:              {parlay['date']}",
            f"Bet type:          {bet_type}",
            f"Combined odds:     {parlay['combined_odds']:.2f}x",
            f"Win probability:   {parlay['parlay_probability']:.1%}",
            f"Expected value:    ${parlay['ev']:.2f}",
            f"Stake:             ${parlay['stake']:.2f}",
            f"Potential payout:  ${parlay['potential_payout']:.2f}",
            f"Platform:          {parlay['platform']}",
            f"Sports covered:    {sports}",
            f"Value anchor:      {parlay['value_anchor']}",
            f"\n{'─'*60}",
            f"LEGS ({parlay['num_legs']}):",
        ]

        for i, leg in enumerate(parlay['legs'], 1):
            value_tag = ' 💎' if leg.get('is_value_bet') else ''
            flags = leg.get('danger_flags', [])
            flag_str = ' ⚠️ ' + ','.join(flags) if flags else ''
            lines.append(
                f"  {i}. [{leg.get('confidence_tier','?'):6}] "
                f"{leg.get('sport','?'):12} | "
                f"{leg.get('selection','?'):25} | "
                f"{leg.get('odds_american',0):+5d} | "
                f"{leg.get('combined_confidence',0):.0%}"
                f"{value_tag}{flag_str}"
            )
            lines.append(f"     📋 {leg.get('reasoning','')[:75]}")

        if parlay.get('danger_flag_count', 0) > 0:
            lines.append(f"\n  ⚠️  {parlay['danger_flag_count']} danger flag(s) detected — review before placing")

        lines.append(f"{'='*60}\n")
        return '\n'.join(lines)