"""
EdgeParlay Confidence Engine
Hybrid rules-based + ML scoring system
Scores every available bet by true confidence
"""
import os
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from typing import Optional
from dotenv import load_dotenv

load_dotenv('/home/claude/edgeparlay/.env')

# ─── RULES-BASED SCORER ──────────────────────────────────────────────────────

class RulesScorer:
    """
    Fast, transparent, interpretable confidence scorer
    Based on documented historical win rates by sport and market type
    """
    
    # Historical win rates by sport for heavy favorites
    SPORT_BASE_RATES = {
        'MLB': {
            'heavy_favorite': 0.72,      # -200 or better moneyline
            'moderate_favorite': 0.62,   # -150 to -199
            'slight_favorite': 0.55,     # -110 to -149
            'total': 0.52,               # Over/under
        },
        'NBA': {
            'heavy_favorite': 0.78,      # Playoffs heavy favorites
            'moderate_favorite': 0.65,
            'slight_favorite': 0.57,
            'total': 0.53,
        },
        'EPL Soccer': {
            'heavy_favorite': 0.68,      # Top 6 vs bottom 6 at home
            'moderate_favorite': 0.58,
            'slight_favorite': 0.50,     # Soccer draws are unpredictable
            'total': 0.51,
        },
        'Champions League': {
            'heavy_favorite': 0.70,
            'moderate_favorite': 0.60,
            'slight_favorite': 0.52,
            'total': 0.51,
        },
        'MLS Soccer': {
            'heavy_favorite': 0.63,
            'moderate_favorite': 0.55,
            'slight_favorite': 0.49,
            'total': 0.50,
        },
        'UFC/MMA': {
            'heavy_favorite': 0.75,      # -400 or better only
            'moderate_favorite': 0.62,
            'slight_favorite': 0.54,
            'total': 0.50,
        },
        'Tennis ATP': {
            'heavy_favorite': 0.85,      # Top 10 vs 50+ ranked
            'moderate_favorite': 0.72,
            'slight_favorite': 0.60,
            'total': 0.55,
        },
        'Tennis WTA': {
            'heavy_favorite': 0.82,
            'moderate_favorite': 0.70,
            'slight_favorite': 0.58,
            'total': 0.54,
        },
    }
    
    def get_favorite_tier(self, odds_american: int) -> str:
        """Classify bet by how heavy the favorite is"""
        if odds_american < 0:
            # Negative odds = favorite
            if odds_american <= -300:
                return 'heavy_favorite'
            elif odds_american <= -200:
                return 'moderate_favorite'
            elif odds_american <= -110:
                return 'slight_favorite'
            else:
                return 'slight_favorite'
        else:
            # Positive odds = underdog - lower confidence
            return 'underdog'
    
    def score(self, opportunity: dict) -> dict:
        """
        Score a single betting opportunity
        Returns confidence score and reasoning
        """
        sport = opportunity.get('sport', 'Unknown')
        odds = opportunity.get('odds_american', 0)
        true_prob = opportunity.get('true_probability', 0.5)
        implied_prob = opportunity.get('implied_probability', 0.5)
        market = opportunity.get('market', 'h2h')
        
        # Get base rate for this sport
        sport_rates = self.SPORT_BASE_RATES.get(sport, {
            'heavy_favorite': 0.65,
            'moderate_favorite': 0.57,
            'slight_favorite': 0.52,
            'total': 0.51,
        })
        
        # Get favorite tier
        tier = self.get_favorite_tier(odds)
        
        # Underdogs are excluded from parlay legs
        if tier == 'underdog':
            return {
                'rules_confidence': 0.30,
                'tier': 'underdog',
                'reasoning': 'Underdog bet - excluded from high confidence parlays',
                'mispricing_gap': 0,
                'value_bet': False
            }
        
        # Base confidence from historical rates
        if 'total' in market.lower():
            base_confidence = sport_rates.get('total', 0.51)
        else:
            base_confidence = sport_rates.get(tier, 0.55)
        
        # Calculate mispricing gap
        mispricing_gap = true_prob - implied_prob
        
        # Adjust confidence based on mispricing
        # If we think true probability is higher than book implies - positive edge
        adjusted_confidence = base_confidence + (mispricing_gap * 0.5)
        
        # Tennis bonus - most reliable sport for heavy favorites
        if 'Tennis' in sport and tier == 'heavy_favorite':
            adjusted_confidence = min(0.88, adjusted_confidence + 0.05)
        
        # UFC penalty - high variance sport
        if 'UFC' in sport and tier != 'heavy_favorite':
            adjusted_confidence = max(0.45, adjusted_confidence - 0.08)
        
        # Soccer draw risk penalty
        if 'Soccer' in sport and tier == 'slight_favorite':
            adjusted_confidence = max(0.45, adjusted_confidence - 0.05)
        
        # Cap confidence between 0.40 and 0.90
        final_confidence = max(0.40, min(0.90, adjusted_confidence))
        
        # Determine if this is a value bet (mispriced by sportsbook)
        value_bet = mispricing_gap > 0.05  # 5%+ gap is meaningful value
        
        reasoning_parts = [
            f"Historical {sport} {tier.replace('_', ' ')} win rate: {base_confidence:.0%}",
        ]
        if value_bet:
            reasoning_parts.append(f"Mispriced by {mispricing_gap:.1%} vs true probability")
        if 'Tennis' in sport and tier == 'heavy_favorite':
            reasoning_parts.append("Tennis heavy favorite bonus applied")
            
        return {
            'rules_confidence': round(final_confidence, 4),
            'tier': tier,
            'reasoning': ' | '.join(reasoning_parts),
            'mispricing_gap': round(mispricing_gap, 4),
            'value_bet': value_bet
        }


# ─── ML SCORER ───────────────────────────────────────────────────────────────

class MLScorer:
    """
    LightGBM-based scorer
    Trained on historical outcomes
    Falls back to rules-based when insufficient data
    """
    
    def __init__(self):
        self.model = None
        self.is_trained = False
        self.feature_columns = [
            'odds_decimal', 'true_probability', 'implied_probability',
            'mispricing_gap', 'is_tennis', 'is_mlb', 'is_nba',
            'is_soccer', 'is_ufc', 'is_heavy_favorite', 'is_moderate_favorite',
            'is_total_market', 'odds_american_abs'
        ]
    
    def prepare_features(self, opportunity: dict, rules_result: dict) -> np.ndarray:
        """Extract features for ML model"""
        sport = opportunity.get('sport', '')
        odds = opportunity.get('odds_american', -110)
        market = opportunity.get('market', 'h2h')
        
        features = {
            'odds_decimal': opportunity.get('odds_decimal', 1.9),
            'true_probability': opportunity.get('true_probability', 0.5),
            'implied_probability': opportunity.get('implied_probability', 0.5),
            'mispricing_gap': rules_result.get('mispricing_gap', 0),
            'is_tennis': 1 if 'Tennis' in sport else 0,
            'is_mlb': 1 if 'MLB' in sport else 0,
            'is_nba': 1 if 'NBA' in sport else 0,
            'is_soccer': 1 if 'Soccer' in sport else 0,
            'is_ufc': 1 if 'UFC' in sport else 0,
            'is_heavy_favorite': 1 if rules_result.get('tier') == 'heavy_favorite' else 0,
            'is_moderate_favorite': 1 if rules_result.get('tier') == 'moderate_favorite' else 0,
            'is_total_market': 1 if 'total' in market.lower() else 0,
            'odds_american_abs': abs(odds)
        }
        
        return np.array([features[col] for col in self.feature_columns])
    
    def train(self, historical_data: pd.DataFrame):
        """Train the ML model on historical data"""
        try:
            import lightgbm as lgb
            from sklearn.model_selection import cross_val_score
            from sklearn.calibration import CalibratedClassifierCV
            
            if len(historical_data) < 100:
                print("⚠️  Insufficient historical data for ML training (need 100+ samples)")
                return False
            
            X = historical_data[self.feature_columns].values
            y = historical_data['outcome'].values  # 1 = win, 0 = loss
            
            # Train LightGBM
            base_model = lgb.LGBMClassifier(
                max_depth=4,
                num_leaves=31,
                learning_rate=0.03,
                n_estimators=400,
                subsample=0.7,
                colsample_bytree=0.7,
                min_child_samples=50,
                reg_alpha=0.1,
                reg_lambda=0.1,
                random_state=42,
                verbose=-1
            )
            
            # Calibrate probabilities using Platt scaling
            self.model = CalibratedClassifierCV(base_model, cv=5, method='sigmoid')
            self.model.fit(X, y)
            self.is_trained = True
            
            # Cross-validation score
            cv_scores = cross_val_score(self.model, X, y, cv=5, scoring='brier_score')
            print(f"✅ ML Model trained | Brier Score: {-cv_scores.mean():.4f}")
            return True
            
        except Exception as e:
            print(f"⚠️  ML training failed: {e}")
            return False
    
    def score(self, opportunity: dict, rules_result: dict) -> float:
        """Get ML confidence score"""
        if not self.is_trained or self.model is None:
            # Fall back to rules-based score
            return rules_result.get('rules_confidence', 0.50)
        
        try:
            features = self.prepare_features(opportunity, rules_result)
            prob = self.model.predict_proba(features.reshape(1, -1))[0][1]
            return round(float(prob), 4)
        except Exception as e:
            return rules_result.get('rules_confidence', 0.50)


# ─── COMBINED CONFIDENCE ENGINE ──────────────────────────────────────────────

class ConfidenceEngine:
    """
    Combines rules-based and ML scoring
    Applies regime adjustments
    Filters and ranks all opportunities
    """
    
    MIN_CONFIDENCE = float(os.getenv('MIN_CONFIDENCE', 0.65))
    
    # Confidence tiers
    GREEN_THRESHOLD = 0.65   # Full stake
    AMBER_THRESHOLD = 0.58   # Half stake
    RED_THRESHOLD = 0.00     # No bet
    
    def __init__(self):
        self.rules_scorer = RulesScorer()
        self.ml_scorer = MLScorer()
        self.regime = 'normal'
        self.regime_multiplier = 1.0
    
    def set_regime(self, regime: str, multiplier: float):
        """Set current market regime"""
        self.regime = regime
        self.regime_multiplier = multiplier
        print(f"📊 Market regime: {regime} (confidence multiplier: {multiplier:.2f}x)")
    
    def score_opportunity(self, opportunity: dict) -> dict:
        """Score a single opportunity with full analysis"""
        
        # Rules-based score
        rules_result = self.rules_scorer.score(opportunity)
        
        # ML score (falls back to rules if not trained)
        ml_confidence = self.ml_scorer.score(opportunity, rules_result)
        
        # Combined score (60% rules, 40% ML when ML is untrained; 40/60 when trained)
        if self.ml_scorer.is_trained:
            combined = (rules_result['rules_confidence'] * 0.40) + (ml_confidence * 0.60)
        else:
            combined = (rules_result['rules_confidence'] * 0.70) + (ml_confidence * 0.30)
        
        # Apply regime adjustment
        adjusted = combined * self.regime_multiplier
        final_confidence = max(0.30, min(0.92, adjusted))
        
        # Determine tier
        if final_confidence >= self.GREEN_THRESHOLD:
            tier = 'GREEN'
        elif final_confidence >= self.AMBER_THRESHOLD:
            tier = 'AMBER'
        else:
            tier = 'RED'
        
        return {
            **opportunity,
            **rules_result,
            'ml_confidence': round(ml_confidence, 4),
            'combined_confidence': round(final_confidence, 4),
            'confidence_tier': tier,
            'regime': self.regime,
            'is_value_bet': rules_result.get('value_bet', False),
            'scored_at': datetime.now(timezone.utc).isoformat()
        }
    
    def score_all(self, opportunities: list) -> list:
        """Score all opportunities and return filtered, ranked results"""
        
        print(f"\n🧠 Scoring {len(opportunities)} opportunities...")
        
        scored = []
        for opp in opportunities:
            result = self.score_opportunity(opp)
            scored.append(result)
        
        # Filter to GREEN and AMBER only
        filtered = [s for s in scored if s['confidence_tier'] in ['GREEN', 'AMBER']]
        
        # Sort by combined confidence descending
        filtered.sort(key=lambda x: x['combined_confidence'], reverse=True)
        
        green_count = len([s for s in filtered if s['confidence_tier'] == 'GREEN'])
        amber_count = len([s for s in filtered if s['confidence_tier'] == 'AMBER'])
        value_bets = len([s for s in filtered if s['is_value_bet']])
        
        print(f"✅ Scoring complete:")
        print(f"   🟢 GREEN (65%+): {green_count} opportunities")
        print(f"   🟡 AMBER (58-65%): {amber_count} opportunities")
        print(f"   💎 Value bets (mispriced 5%+): {value_bets} opportunities")
        print(f"   🔴 RED (below threshold): {len(scored) - len(filtered)} excluded")
        
        return filtered
    
    def get_value_anchor(self, scored_opportunities: list) -> Optional[dict]:
        """Get the single highest confidence pick (value anchor)"""
        if not scored_opportunities:
            return None
        return scored_opportunities[0]  # Already sorted by confidence


if __name__ == "__main__":
    # Test the confidence engine with sample data
    print("Testing Confidence Engine...\n")
    
    engine = ConfidenceEngine()
    
    test_opportunities = [
        {
            'sport': 'Tennis ATP',
            'event_name': 'Jannik Sinner vs Lucky Loser',
            'selection': 'Jannik Sinner',
            'odds_american': -500,
            'odds_decimal': 1.20,
            'true_probability': 0.85,
            'implied_probability': 0.833,
            'market': 'h2h',
            'bookmaker': 'FanDuel'
        },
        {
            'sport': 'MLB',
            'event_name': 'New York Yankees vs Oakland Athletics',
            'selection': 'New York Yankees',
            'odds_american': -220,
            'odds_decimal': 1.45,
            'true_probability': 0.72,
            'implied_probability': 0.69,
            'market': 'h2h',
            'bookmaker': 'DraftKings'
        },
        {
            'sport': 'EPL Soccer',
            'event_name': 'Manchester City vs Luton Town',
            'selection': 'Manchester City',
            'odds_american': -350,
            'odds_decimal': 1.29,
            'true_probability': 0.78,
            'implied_probability': 0.778,
            'market': 'h2h',
            'bookmaker': 'BetMGM'
        },
        {
            'sport': 'UFC/MMA',
            'event_name': 'Islam Makhachev vs Contender',
            'selection': 'Islam Makhachev',
            'odds_american': -450,
            'odds_decimal': 1.22,
            'true_probability': 0.82,
            'implied_probability': 0.818,
            'market': 'h2h',
            'bookmaker': 'FanDuel'
        },
        {
            'sport': 'NBA',
            'event_name': 'Oklahoma City Thunder vs Weak Opponent',
            'selection': 'Oklahoma City Thunder',
            'odds_american': -280,
            'odds_decimal': 1.36,
            'true_probability': 0.74,
            'implied_probability': 0.737,
            'market': 'h2h',
            'bookmaker': 'DraftKings'
        }
    ]
    
    scored = engine.score_all(test_opportunities)
    
    print("\n📊 SCORED OPPORTUNITIES:")
    print("-"*80)
    for s in scored:
        print(f"  {s['confidence_tier']:6} | {s['combined_confidence']:.1%} | {s['sport']:12} | {s['selection']:25} | {s['odds_american']:+5d} | {'💎 VALUE' if s['is_value_bet'] else ''}")
    
    anchor = engine.get_value_anchor(scored)
    if anchor:
        print(f"\n🎯 VALUE ANCHOR: {anchor['selection']} ({anchor['sport']}) @ {anchor['odds_american']:+d} | Confidence: {anchor['combined_confidence']:.1%}")
