"""
EdgeParlay Constructor
Builds optimal daily parlay from scored opportunities
Handles correlation filtering, EV optimization, dynamic bet type selection
"""
import os
import numpy as np
from datetime import datetime, timezone
from typing import Optional
from dotenv import load_dotenv

load_dotenv('/home/claude/edgeparlay/.env')

TARGET_ODDS_MIN = float(os.getenv('TARGET_ODDS_MIN', 3.0))
TARGET_ODDS_MAX = float(os.getenv('TARGET_ODDS_MAX', 3.5))
MIN_CONFIDENCE = float(os.getenv('MIN_CONFIDENCE', 0.65))

def american_to_decimal(american: int) -> float:
    if american > 0:
        return 1 + (american / 100)
    return 1 - (100 / american)

def combine_decimal_odds(legs: list) -> float:
    combined = 1.0
    for leg in legs:
        combined *= leg.get('odds_decimal', 1.0)
    return round(combined, 4)

def calculate_parlay_probability(legs: list) -> float:
    prob = 1.0
    for leg in legs:
        prob *= leg.get('combined_confidence', 0.65)
    return round(prob, 4)

def calculate_ev(combined_odds: float, parlay_prob: float, stake: float) -> float:
    profit_if_win = stake * (combined_odds - 1)
    ev = (parlay_prob * profit_if_win) - ((1 - parlay_prob) * stake)
    return round(ev, 4)

def kelly_stake(bankroll: float, parlay_prob: float, combined_odds: float, fraction: float = 0.25) -> float:
    """Quarter Kelly criterion for position sizing"""
    if combined_odds <= 1:
        return 0
    b = combined_odds - 1
    p = parlay_prob
    q = 1 - p
    kelly = (b * p - q) / b
    quarter_kelly = kelly * fraction
    max_stake = bankroll * 0.20
    recommended = min(bankroll * max(0, quarter_kelly), max_stake)
    return round(max(float(os.getenv('BASE_STAKE', 10)), recommended), 2)

def are_correlated(leg1: dict, leg2: dict) -> bool:
    """Check if two legs are correlated (same event or sport)"""
    if leg1.get('event_id') == leg2.get('event_id'):
        return True
    if leg1.get('sport') == leg2.get('sport') and leg1.get('event_name') == leg2.get('event_name'):
        return True
    same_sport_same_team = (
        leg1.get('sport') == leg2.get('sport') and
        leg1.get('selection', '').split()[0] == leg2.get('selection', '').split()[0]
    )
    if same_sport_same_team:
        return True
    return False

def check_correlations(legs: list) -> bool:
    """Ensure no two legs in the parlay are correlated"""
    for i in range(len(legs)):
        for j in range(i + 1, len(legs)):
            if are_correlated(legs[i], legs[j]):
                return False
    return True

class ParlayConstructor:

    def __init__(self, bankroll: float = 100.0):
        self.bankroll = bankroll
        self.base_stake = float(os.getenv('BASE_STAKE', 10))

    def build_optimal_parlay(self, scored_opportunities: list) -> Optional[dict]:
        """
        Build the optimal parlay for today
        Strategy: greedy approach starting from highest confidence
        Target: combined odds between 3.0 and 3.5
        """
        if not scored_opportunities:
            return None

        green_opps = [o for o in scored_opportunities if o.get('confidence_tier') == 'GREEN']
        amber_opps = [o for o in scored_opportunities if o.get('confidence_tier') == 'AMBER']
        all_opps = green_opps + amber_opps

        if not all_opps:
            return None

        value_anchor = all_opps[0]
        best_parlay = None
        best_ev = -999

        # Try building parlays of different sizes
        for target_legs in range(2, min(10, len(all_opps)) + 1):
            parlay_legs = [value_anchor]
            remaining = [o for o in all_opps[1:] if not are_correlated(o, value_anchor)]

            for candidate in remaining:
                if len(parlay_legs) >= target_legs:
                    break
                if check_correlations(parlay_legs + [candidate]):
                    parlay_legs.append(candidate)

            if len(parlay_legs) < 2:
                continue

            combined_odds = combine_decimal_odds(parlay_legs)
            parlay_prob = calculate_parlay_probability(parlay_legs)
            stake = self.base_stake
            ev = calculate_ev(combined_odds, parlay_prob, stake)

            # Check if odds are in target range
            in_target_range = TARGET_ODDS_MIN <= combined_odds <= TARGET_ODDS_MAX

            if in_target_range and ev > best_ev:
                best_ev = ev
                best_parlay = {
                    'legs': parlay_legs,
                    'combined_odds': combined_odds,
                    'parlay_probability': parlay_prob,
                    'ev': ev,
                    'stake': stake,
                    'potential_payout': round(stake * combined_odds, 2),
                    'num_legs': len(parlay_legs),
                    'bet_type': 'parlay',
                    'in_target_range': True
                }

        # If no parlay hits the target range, take best EV option
        if not best_parlay:
            # Try all 2-leg combinations
            for i in range(len(all_opps)):
                for j in range(i + 1, len(all_opps)):
                    legs = [all_opps[i], all_opps[j]]
                    if not check_correlations(legs):
                        continue
                    combined_odds = combine_decimal_odds(legs)
                    parlay_prob = calculate_parlay_probability(legs)
                    stake = self.base_stake
                    ev = calculate_ev(combined_odds, parlay_prob, stake)
                    if ev > best_ev:
                        best_ev = ev
                        best_parlay = {
                            'legs': legs,
                            'combined_odds': combined_odds,
                            'parlay_probability': parlay_prob,
                            'ev': ev,
                            'stake': stake,
                            'potential_payout': round(stake * combined_odds, 2),
                            'num_legs': 2,
                            'bet_type': 'parlay',
                            'in_target_range': False
                        }

        if not best_parlay:
            return None

        # Determine confidence tier for overall parlay
        avg_confidence = np.mean([l['combined_confidence'] for l in best_parlay['legs']])
        if avg_confidence >= 0.65:
            tier = 'GREEN'
        elif avg_confidence >= 0.58:
            tier = 'AMBER'
        else:
            return None

        # Find best platform (platform that appears most in legs)
        platform_counts = {}
        for leg in best_parlay['legs']:
            book = leg.get('bookmaker', 'FanDuel')
            platform_counts[book] = platform_counts.get(book, 0) + 1
        best_platform = max(platform_counts, key=platform_counts.get)

        # Check for value bets
        value_bets = [l for l in best_parlay['legs'] if l.get('is_value_bet', False)]

        return {
            **best_parlay,
            'date': datetime.now().strftime('%Y-%m-%d'),
            'confidence_tier': tier,
            'avg_confidence': round(float(avg_confidence), 4),
            'value_anchor': value_anchor['selection'],
            'platform': best_platform,
            'value_bets_count': len(value_bets),
            'stake': self.base_stake,
            'regime': scored_opportunities[0].get('regime', 'normal') if scored_opportunities else 'normal',
            'created_at': datetime.now(timezone.utc).isoformat()
        }

    def should_bet_today(self, parlay: Optional[dict]) -> tuple:
        """Determine if we should bet today and why"""
        if not parlay:
            return False, "No qualifying opportunities found today. Protecting bankroll."

        if parlay['confidence_tier'] == 'RED':
            return False, "Confidence too low. Skipping today to protect bankroll."

        if parlay['ev'] < 0:
            return False, f"Negative expected value ({parlay['ev']:.2f}). No bet today."

        if parlay['num_legs'] < 2:
            return False, "Could not build minimum 2-leg parlay. No bet today."

        return True, f"Strong {parlay['confidence_tier']} parlay identified. Bet recommended."

    def format_parlay_summary(self, parlay: dict) -> str:
        """Format parlay for display"""
        tier_emoji = '🟢' if parlay['confidence_tier'] == 'GREEN' else '🟡'
        lines = [
            f"\n{'='*60}",
            f"{tier_emoji} TODAY'S EDGEPARLAY — {parlay['confidence_tier']} CONFIDENCE",
            f"{'='*60}",
            f"Date: {parlay['date']}",
            f"Combined Odds: {parlay['combined_odds']:.2f}x",
            f"Parlay Probability: {parlay['parlay_probability']:.1%}",
            f"Expected Value: ${parlay['ev']:.2f}",
            f"Stake: ${parlay['stake']:.2f}",
            f"Potential Payout: ${parlay['potential_payout']:.2f}",
            f"Platform: {parlay['platform']}",
            f"Value Anchor: {parlay['value_anchor']}",
            f"\n{'─'*60}",
            f"LEGS ({parlay['num_legs']}):",
        ]
        for i, leg in enumerate(parlay['legs'], 1):
            value_tag = ' 💎' if leg.get('is_value_bet') else ''
            lines.append(
                f"  {i}. [{leg['confidence_tier']:6}] {leg['sport']:12} | "
                f"{leg['selection']:25} | {leg['odds_american']:+5d} | "
                f"{leg['combined_confidence']:.0%}{value_tag}"
            )
            lines.append(f"     📋 {leg.get('reasoning', 'Historical pattern match')[:70]}")
        lines.append(f"{'='*60}\n")
        return '\n'.join(lines)


if __name__ == "__main__":
    from backend.confidence_engine import ConfidenceEngine

    engine = ConfidenceEngine()
    constructor = ParlayConstructor(bankroll=100)

    test_opportunities = [
        {'sport': 'Tennis ATP', 'event_name': 'Sinner vs Qualifier', 'event_id': 'ten1',
         'selection': 'Jannik Sinner', 'odds_american': -500, 'odds_decimal': 1.20,
         'true_probability': 0.85, 'implied_probability': 0.833, 'market': 'h2h', 'bookmaker': 'FanDuel'},
        {'sport': 'MLB', 'event_name': 'Yankees vs Oakland', 'event_id': 'mlb1',
         'selection': 'New York Yankees', 'odds_american': -220, 'odds_decimal': 1.45,
         'true_probability': 0.72, 'implied_probability': 0.69, 'market': 'h2h', 'bookmaker': 'FanDuel'},
        {'sport': 'EPL Soccer', 'event_name': 'Man City vs Luton', 'event_id': 'soc1',
         'selection': 'Manchester City', 'odds_american': -350, 'odds_decimal': 1.29,
         'true_probability': 0.78, 'implied_probability': 0.778, 'market': 'h2h', 'bookmaker': 'DraftKings'},
        {'sport': 'UFC/MMA', 'event_name': 'Makhachev vs Contender', 'event_id': 'ufc1',
         'selection': 'Islam Makhachev', 'odds_american': -450, 'odds_decimal': 1.22,
         'true_probability': 0.82, 'implied_probability': 0.818, 'market': 'h2h', 'bookmaker': 'BetMGM'},
        {'sport': 'NBA', 'event_name': 'Thunder vs Opponent', 'event_id': 'nba1',
         'selection': 'OKC Thunder', 'odds_american': -280, 'odds_decimal': 1.36,
         'true_probability': 0.74, 'implied_probability': 0.737, 'market': 'h2h', 'bookmaker': 'FanDuel'},
    ]

    scored = engine.score_all(test_opportunities)
    parlay = constructor.build_optimal_parlay(scored)

    if parlay:
        print(constructor.format_parlay_summary(parlay))
        should_bet, reason = constructor.should_bet_today(parlay)
        print(f"💰 BET TODAY: {'YES' if should_bet else 'NO'}")
        print(f"   Reason: {reason}")
    else:
        print("❌ No parlay could be built today")
