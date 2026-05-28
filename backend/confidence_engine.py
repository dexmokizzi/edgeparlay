"""
EdgeParlay Confidence Engine v2
Upgraded with:
- Odds filter (rejects unplayable lines like -10000)
- Surface/tournament awareness (French Open clay)
- Stricter confidence thresholds
- Cross-sport regime detection
- Tournament variance penalties
- Danger flag system
"""
import os
import sys
import pickle
import numpy as np
from datetime import datetime, timezone
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'models', 'edgeparlay_model.pkl')

# Absolute odds limits
MAX_ODDS_AMERICAN = -110      # No slight favorites
MIN_ODDS_AMERICAN = -1500     # No unplayable lines

# Current clay tournaments (French Open is running now)
CLAY_TOURNAMENTS = [
    'french open', 'roland garros', 'madrid', 'barcelona',
    'rome', 'monte carlo', 'hamburg', 'geneva', 'lyon',
    'estoril', 'bucharest', 'marrakech', 'istanbul'
]

# Clay specialists - bonus on clay
CLAY_SPECIALISTS = [
    'rafael nadal', 'carlos alcaraz', 'casper ruud', 'jannik sinner',
    'stefanos tsitsipas', 'holger rune', 'nicolas jarry',
    'alejandro davidovich fokina', 'albert ramos-vinolas',
    'pablo carreno busta', 'pedro martinez', 'diego schwartzman',
    'flavio cobolli', 'matteo arnaldi', 'francisco cerundolo'
]

# Hard court specialists - penalty on clay
HARD_COURT_SPECIALISTS = [
    'daniil medvedev', 'andrey rublev', 'taylor fritz',
    'frances tiafoe', 'ben shelton', 'felix auger aliassime',
    'tommy paul', 'alex de minaur', 'grigor dimitrov'
]


class RulesScorer:
    """
    Transparent rules-based scorer
    Based on documented historical win rates
    Includes surface, tournament, and danger flag logic
    """

    SPORT_BASE_RATES = {
        'MLB': {
            'heavy_favorite': 0.69,
            'moderate_favorite': 0.61,
            'slight_favorite': 0.54,
        },
        'NBA': {
            'heavy_favorite': 0.76,
            'moderate_favorite': 0.64,
            'slight_favorite': 0.56,
        },
        'EPL Soccer': {
            'heavy_favorite': 0.66,
            'moderate_favorite': 0.56,
            'slight_favorite': 0.48,
        },
        'Champions League': {
            'heavy_favorite': 0.68,
            'moderate_favorite': 0.58,
            'slight_favorite': 0.50,
        },
        'MLS Soccer': {
            'heavy_favorite': 0.61,
            'moderate_favorite': 0.53,
            'slight_favorite': 0.47,
        },
        'UFC/MMA': {
            'heavy_favorite': 0.73,
            'moderate_favorite': 0.60,
            'slight_favorite': 0.52,
        },
        'Tennis ATP': {
            'heavy_favorite': 0.81,
            'moderate_favorite': 0.68,
            'slight_favorite': 0.57,
        },
        'Tennis WTA': {
            'heavy_favorite': 0.78,
            'moderate_favorite': 0.66,
            'slight_favorite': 0.55,
        },
    }

    def is_valid_odds(self, odds: int) -> bool:
        if odds >= 0:
            return False
        if odds < MIN_ODDS_AMERICAN:
            return False
        if odds > MAX_ODDS_AMERICAN:
            return False
        return True

    def get_tier(self, odds: int) -> str:
        if odds <= -300:
            return 'heavy_favorite'
        elif odds <= -200:
            return 'moderate_favorite'
        elif odds <= -110:
            return 'slight_favorite'
        return 'underdog'

    def get_tournament_context(self, event_name: str) -> dict:
        e = event_name.lower() if event_name else ''
        is_clay = any(t in e for t in CLAY_TOURNAMENTS)
        is_grass = any(t in e for t in ['wimbledon', 'queens', 'halle', 'eastbourne', 'newport'])
        is_slam = any(t in e for t in ['french open', 'roland garros', 'wimbledon', 'us open', 'australian open'])
        return {
            'surface': 'clay' if is_clay else ('grass' if is_grass else 'hard'),
            'is_clay': is_clay,
            'is_grass': is_grass,
            'is_grand_slam': is_slam
        }

    def get_surface_adj(self, player: str, surface: str) -> float:
        p = player.lower() if player else ''
        if surface == 'clay':
            if any(s in p for s in CLAY_SPECIALISTS):
                return +0.04
            if any(s in p for s in HARD_COURT_SPECIALISTS):
                return -0.05
        return 0.0

    def score(self, opp: dict) -> dict:
        sport = opp.get('sport', 'Unknown')
        odds = opp.get('odds_american', 0)
        true_prob = opp.get('true_probability', 0.5)
        implied_prob = opp.get('implied_probability', 0.5)
        event_name = opp.get('event_name', '')
        selection = opp.get('selection', '')

        # Hard reject invalid odds
        if not self.is_valid_odds(odds):
            return {
                'rules_confidence': 0.0,
                'tier': 'rejected',
                'reasoning': f'Odds {odds} rejected (valid range: {MIN_ODDS_AMERICAN} to {MAX_ODDS_AMERICAN})',
                'mispricing_gap': 0,
                'value_bet': False,
                'danger_flags': ['invalid_odds']
            }

        tier = self.get_tier(odds)
        if tier == 'underdog':
            return {
                'rules_confidence': 0.0,
                'tier': 'underdog',
                'reasoning': 'Underdog excluded',
                'mispricing_gap': 0,
                'value_bet': False,
                'danger_flags': ['underdog']
            }

        sport_rates = self.SPORT_BASE_RATES.get(sport, {
            'heavy_favorite': 0.63,
            'moderate_favorite': 0.55,
            'slight_favorite': 0.50,
        })
        base = sport_rates.get(tier, 0.55)
        mispricing = true_prob - implied_prob
        adjusted = base + (mispricing * 0.4)
        danger_flags = []
        reasoning = [f"{sport} {tier.replace('_',' ')}: {base:.0%}"]

        if 'Tennis' in sport:
            ctx = self.get_tournament_context(event_name)
            surface_adj = self.get_surface_adj(selection, ctx['surface'])
            adjusted += surface_adj
            if surface_adj != 0:
                reasoning.append(f"Surface adj: {surface_adj:+.0%}")
            if ctx['is_grand_slam']:
                adjusted -= 0.03
                danger_flags.append('grand_slam_variance')
                reasoning.append("Grand slam -3%")

        elif 'UFC' in sport:
            if tier != 'heavy_favorite':
                adjusted -= 0.10
                danger_flags.append('ufc_variance')
                reasoning.append("UFC moderate fav -10%")

        elif 'Soccer' in sport:
            if tier == 'slight_favorite':
                adjusted -= 0.08
                danger_flags.append('draw_risk')
                reasoning.append("Draw risk -8%")
            elif tier == 'moderate_favorite':
                adjusted -= 0.03
                reasoning.append("Draw risk -3%")

        elif 'MLB' in sport:
            danger_flags.append('verify_pitcher')
            reasoning.append("Verify starter")

        value_bet = mispricing > 0.05
        if value_bet:
            reasoning.append(f"Value: +{mispricing:.1%}")

        final = max(0.35, min(0.87, adjusted))

        return {
            'rules_confidence': round(final, 4),
            'tier': tier,
            'reasoning': ' | '.join(reasoning),
            'mispricing_gap': round(mispricing, 4),
            'value_bet': value_bet,
            'danger_flags': danger_flags,
        }


class MLScorer:
    """LightGBM scorer with Platt calibration"""

    FEATURE_COLS = [
        'odds_decimal', 'true_probability', 'implied_probability',
        'mispricing_gap', 'is_tennis', 'is_mlb', 'is_nba',
        'is_soccer', 'is_ufc', 'is_heavy_favorite', 'is_moderate_favorite',
        'is_total_market', 'odds_american_abs', 'favorite_tier'
    ]

    def __init__(self):
        self.model = None
        self.is_trained = False
        self._load()

    def _load(self):
        try:
            if os.path.exists(MODEL_PATH):
                with open(MODEL_PATH, 'rb') as f:
                    data = pickle.load(f)
                self.model = data['model']
                self.is_trained = True
                print("✅ ML model loaded")
        except Exception as e:
            print(f"⚠️  ML model not loaded: {e}")

    def score(self, opp: dict, rules: dict) -> float:
        if not self.is_trained:
            return rules.get('rules_confidence', 0.50)
        try:
            sport = opp.get('sport', '')
            odds = opp.get('odds_american', -110)
            market = opp.get('market', 'h2h')
            tier = rules.get('tier', 'slight_favorite')
            tier_map = {'heavy_favorite': 3, 'moderate_favorite': 2, 'slight_favorite': 1, 'underdog': 0}
            features = np.array([
                opp.get('odds_decimal', 1.9),
                opp.get('true_probability', 0.5),
                opp.get('implied_probability', 0.5),
                rules.get('mispricing_gap', 0),
                1 if 'Tennis' in sport else 0,
                1 if 'MLB' in sport else 0,
                1 if 'NBA' in sport else 0,
                1 if 'Soccer' in sport else 0,
                1 if 'UFC' in sport else 0,
                1 if tier == 'heavy_favorite' else 0,
                1 if tier == 'moderate_favorite' else 0,
                1 if 'total' in market.lower() else 0,
                abs(odds),
                tier_map.get(tier, 1)
            ])
            prob = self.model.predict_proba(features.reshape(1, -1))[0][1]
            return round(float(prob), 4)
        except Exception:
            return rules.get('rules_confidence', 0.50)


class RegimeDetector:
    def detect(self, opportunities: list) -> dict:
        month = datetime.now().month
        if month in [1, 2]:
            return {'regime': 'early_season', 'multiplier': 0.93, 'note': 'Early season variance'}
        if month in [5, 6, 7, 8, 9]:
            return {'regime': 'peak_season', 'multiplier': 1.0, 'note': 'Peak season'}
        if month in [10, 11, 12]:
            return {'regime': 'late_season', 'multiplier': 0.95, 'note': 'Late season'}
        return {'regime': 'normal', 'multiplier': 1.0, 'note': 'Normal'}


class ConfidenceEngine:
    """
    Main engine combining rules-based + ML
    Stricter thresholds, danger flags, regime awareness
    """

    GREEN_THRESHOLD = 0.67
    AMBER_THRESHOLD = 0.60

    def __init__(self):
        self.rules = RulesScorer()
        self.ml = MLScorer()
        self.regime_detector = RegimeDetector()
        self.regime = 'normal'
        self.regime_multiplier = 1.0

    def set_regime(self, regime: str, multiplier: float):
        self.regime = regime
        self.regime_multiplier = multiplier

    def score_opportunity(self, opp: dict) -> dict:
        rules_result = self.rules.score(opp)

        if rules_result.get('tier') in ['rejected', 'underdog']:
            return {
                **opp, **rules_result,
                'ml_confidence': 0.0,
                'combined_confidence': 0.0,
                'confidence_tier': 'RED',
                'regime': self.regime,
                'is_value_bet': False,
                'scored_at': datetime.now(timezone.utc).isoformat()
            }

        ml_conf = self.ml.score(opp, rules_result)

        if self.ml.is_trained:
            combined = (rules_result['rules_confidence'] * 0.35) + (ml_conf * 0.65)
        else:
            combined = (rules_result['rules_confidence'] * 0.75) + (ml_conf * 0.25)

        adjusted = combined * self.regime_multiplier

        danger_flags = rules_result.get('danger_flags', [])
        if 'grand_slam_variance' in danger_flags:
            adjusted -= 0.02
        if 'ufc_variance' in danger_flags:
            adjusted -= 0.03

        final = max(0.30, min(0.87, adjusted))

        if final >= self.GREEN_THRESHOLD:
            tier = 'GREEN'
        elif final >= self.AMBER_THRESHOLD:
            tier = 'AMBER'
        else:
            tier = 'RED'

        return {
            **opp, **rules_result,
            'ml_confidence': round(ml_conf, 4),
            'combined_confidence': round(final, 4),
            'confidence_tier': tier,
            'regime': self.regime,
            'is_value_bet': rules_result.get('value_bet', False),
            'danger_flags': danger_flags,
            'scored_at': datetime.now(timezone.utc).isoformat()
        }

    def score_all(self, opportunities: list) -> list:
        print(f"\n🧠 Scoring {len(opportunities)} opportunities...")

        regime_info = self.regime_detector.detect(opportunities)
        self.regime = regime_info['regime']
        self.regime_multiplier = regime_info['multiplier']
        print(f"📊 Regime: {regime_info['regime']} — {regime_info['note']}")

        scored = [self.score_opportunity(opp) for opp in opportunities]
        filtered = [s for s in scored if s['confidence_tier'] in ['GREEN', 'AMBER']]
        filtered.sort(key=lambda x: x['combined_confidence'], reverse=True)

        green = len([s for s in filtered if s['confidence_tier'] == 'GREEN'])
        amber = len([s for s in filtered if s['confidence_tier'] == 'AMBER'])
        rejected = len([s for s in scored if s.get('tier') in ['rejected', 'underdog']])
        values = len([s for s in filtered if s['is_value_bet']])

        print(f"   🟢 GREEN (67%+): {green}")
        print(f"   🟡 AMBER (60-67%): {amber}")
        print(f"   💎 Value bets: {values}")
        print(f"   🔴 Rejected (invalid/underdog): {rejected}")
        print(f"   ⛔ Below threshold: {len(scored) - len(filtered) - rejected}")

        return filtered

    def get_value_anchor(self, scored: list) -> Optional[dict]:
        return scored[0] if scored else None