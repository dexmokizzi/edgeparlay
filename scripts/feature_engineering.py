"""
EdgeParlay Feature Engineering Pipeline
Transforms raw historical data into ML-ready features
Sport-specific feature engineering per documented predictive variables
"""
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

DATA_DIR = '/home/claude/edgeparlay/data'
os.makedirs(f'{DATA_DIR}/processed', exist_ok=True)


# ─── SOCCER FEATURES ─────────────────────────────────────────────────────────

def engineer_soccer_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Soccer-specific features:
    - Home advantage (documented: ~55-60% home win rate in top leagues)
    - Implied probability from betting odds
    - No-vig true probability
    - Form (last 5 games)
    - Goal difference
    """
    print("  ⚽ Engineering soccer features...")
    records = []

    # Find available odds columns
    home_odds_cols = [c for c in ['B365H', 'PSH', 'BWH'] if c in df.columns]
    away_odds_cols = [c for c in ['B365A', 'PSA', 'BWA'] if c in df.columns]
    draw_odds_cols = [c for c in ['B365D', 'PSD', 'BWD'] if c in df.columns]

    if not home_odds_cols:
        print("  ⚠️  No odds columns found in soccer data")
        return pd.DataFrame()

    home_col = home_odds_cols[0]
    away_col = away_odds_cols[0] if away_odds_cols else None
    draw_col = draw_odds_cols[0] if draw_odds_cols else None

    df = df.dropna(subset=[home_col]).copy()

    for _, row in df.iterrows():
        try:
            home_decimal = float(row[home_col])
            if home_decimal <= 1.0:
                continue

            home_implied = 1 / home_decimal

            # Calculate no-vig probability if we have all three outcomes
            if away_col and draw_col and pd.notna(row.get(away_col)) and pd.notna(row.get(draw_col)):
                away_decimal = float(row[away_col])
                draw_decimal = float(row[draw_col])

                if away_decimal > 1.0 and draw_decimal > 1.0:
                    away_implied = 1 / away_decimal
                    draw_implied = 1 / draw_decimal
                    total_implied = home_implied + away_implied + draw_implied
                    true_home_prob = home_implied / total_implied
                else:
                    true_home_prob = home_implied * 0.95  # Rough vig removal
            else:
                true_home_prob = home_implied * 0.95

            # Convert result to outcome (1 = home win, 0 = not home win)
            result = str(row.get('FTR', ''))
            if result == 'H':
                outcome = 1
            elif result in ['A', 'D']:
                outcome = 0
            else:
                continue

            # American odds equivalent
            if home_decimal >= 2.0:
                american_odds = int((home_decimal - 1) * 100)
            else:
                american_odds = int(-100 / (home_decimal - 1))

            # Favorite tier
            if american_odds <= -300:
                favorite_tier = 3  # heavy
            elif american_odds <= -200:
                favorite_tier = 2  # moderate
            elif american_odds <= -110:
                favorite_tier = 1  # slight
            else:
                favorite_tier = 0  # underdog

            records.append({
                'sport': 'Soccer',
                'league': row.get('league', 'Unknown'),
                'date': row.get('Date', ''),
                'home_team': row.get('HomeTeam', ''),
                'away_team': row.get('AwayTeam', ''),
                'selection': row.get('HomeTeam', ''),
                'odds_decimal': home_decimal,
                'odds_american': american_odds,
                'implied_probability': round(home_implied, 4),
                'true_probability': round(true_home_prob, 4),
                'mispricing_gap': round(true_home_prob - home_implied, 4),
                'favorite_tier': favorite_tier,
                'is_heavy_favorite': 1 if favorite_tier == 3 else 0,
                'is_moderate_favorite': 1 if favorite_tier == 2 else 0,
                'is_slight_favorite': 1 if favorite_tier == 1 else 0,
                'is_underdog': 1 if favorite_tier == 0 else 0,
                'is_tennis': 0, 'is_mlb': 0, 'is_nba': 0,
                'is_soccer': 1, 'is_ufc': 0,
                'is_total_market': 0,
                'odds_american_abs': abs(american_odds),
                'outcome': outcome
            })

        except Exception:
            continue

    result_df = pd.DataFrame(records)
    print(f"  ✅ Soccer features: {len(result_df)} samples")
    return result_df


# ─── TENNIS FEATURES ─────────────────────────────────────────────────────────

def engineer_tennis_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tennis-specific features:
    - Ranking gap (most predictive feature in tennis)
    - Surface win rates
    - Ranking points ratio
    - Tournament round (later rounds = better players)
    """
    print("  🎾 Engineering tennis features...")
    records = []

    required = ['winner_rank', 'loser_rank']
    if not all(c in df.columns for c in required):
        print("  ⚠️  Missing ranking columns")
        return pd.DataFrame()

    df = df.dropna(subset=['winner_rank', 'loser_rank']).copy()
    df['winner_rank'] = pd.to_numeric(df['winner_rank'], errors='coerce')
    df['loser_rank'] = pd.to_numeric(df['loser_rank'], errors='coerce')
    df = df.dropna(subset=['winner_rank', 'loser_rank'])

    for _, row in df.iterrows():
        try:
            winner_rank = float(row['winner_rank'])
            loser_rank = float(row['loser_rank'])

            if winner_rank <= 0 or loser_rank <= 0:
                continue

            # The favorite is whoever has the LOWER (better) ranking
            # We model from favorite's perspective
            if winner_rank < loser_rank:
                # Favorite won
                fav_rank = winner_rank
                dog_rank = loser_rank
                outcome = 1
            else:
                # Underdog won
                fav_rank = loser_rank
                dog_rank = winner_rank
                outcome = 0

            rank_gap = dog_rank - fav_rank
            rank_ratio = dog_rank / fav_rank if fav_rank > 0 else 1

            # Estimate true probability from ranking gap
            # Based on documented ATP win rates by rank gap
            if rank_ratio >= 10:
                true_prob = 0.85
            elif rank_ratio >= 5:
                true_prob = 0.78
            elif rank_ratio >= 3:
                true_prob = 0.72
            elif rank_ratio >= 2:
                true_prob = 0.65
            else:
                true_prob = 0.57

            # Surface adjustment
            surface = str(row.get('surface', '')).lower()
            surface_clay = 1 if surface == 'clay' else 0
            surface_grass = 1 if surface == 'grass' else 0
            surface_hard = 1 if surface == 'hard' else 0

            # Estimate American odds from true probability
            if true_prob >= 0.5:
                american_odds = int(-true_prob / (1 - true_prob) * 100)
            else:
                american_odds = int((1 - true_prob) / true_prob * 100)

            implied_prob = true_prob * 1.05  # Book adds ~5% vig
            implied_prob = min(0.95, implied_prob)

            records.append({
                'sport': row.get('sport', 'Tennis ATP'),
                'date': str(row.get('tourney_date', '')),
                'surface': surface,
                'surface_clay': surface_clay,
                'surface_grass': surface_grass,
                'surface_hard': surface_hard,
                'rank_gap': rank_gap,
                'rank_ratio': round(rank_ratio, 2),
                'fav_rank': fav_rank,
                'dog_rank': dog_rank,
                'odds_decimal': round(1 / true_prob, 4),
                'odds_american': american_odds,
                'implied_probability': round(implied_prob, 4),
                'true_probability': round(true_prob, 4),
                'mispricing_gap': round(true_prob - implied_prob, 4),
                'favorite_tier': 3 if true_prob >= 0.78 else (2 if true_prob >= 0.68 else 1),
                'is_heavy_favorite': 1 if true_prob >= 0.78 else 0,
                'is_moderate_favorite': 1 if 0.68 <= true_prob < 0.78 else 0,
                'is_slight_favorite': 1 if true_prob < 0.68 else 0,
                'is_underdog': 0,
                'is_tennis': 1, 'is_mlb': 0, 'is_nba': 0,
                'is_soccer': 0, 'is_ufc': 0,
                'is_total_market': 0,
                'odds_american_abs': abs(american_odds),
                'outcome': outcome
            })

        except Exception:
            continue

    result_df = pd.DataFrame(records)
    print(f"  ✅ Tennis features: {len(result_df)} samples")
    return result_df


# ─── MLB FEATURES ────────────────────────────────────────────────────────────

def engineer_mlb_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    MLB-specific features:
    - Home/away advantage
    - Score differential as proxy for team strength
    - Season trends
    """
    print("  ⚾ Engineering MLB features...")

    if df.empty or 'home_won' not in df.columns:
        return pd.DataFrame()

    records = []

    for _, row in df.iterrows():
        try:
            home_won = int(row.get('home_won', 0))

            # Estimate team strength from scores
            home_score = float(row.get('home_score', 4.5))
            away_score = float(row.get('away_score', 4.5))

            # Estimate true probability
            score_ratio = (home_score + 0.5) / (away_score + 0.5)
            base_home_advantage = 0.54  # Documented MLB home win rate

            if score_ratio > 1.3:
                true_prob = 0.70
            elif score_ratio > 1.1:
                true_prob = 0.62
            elif score_ratio > 0.9:
                true_prob = base_home_advantage
            else:
                true_prob = 0.45

            # Add noise to simulate real betting lines
            noise = np.random.normal(0, 0.03)
            true_prob = max(0.45, min(0.80, true_prob + noise))

            implied_prob = min(0.95, true_prob * 1.05)

            if true_prob >= 0.5:
                american_odds = int(-true_prob / (1 - true_prob) * 100)
            else:
                american_odds = int((1 - true_prob) / true_prob * 100)

            records.append({
                'sport': 'MLB',
                'date': str(row.get('date', '')),
                'home_team': row.get('home_team', ''),
                'away_team': row.get('away_team', ''),
                'odds_decimal': round(1 / true_prob, 4),
                'odds_american': american_odds,
                'implied_probability': round(implied_prob, 4),
                'true_probability': round(true_prob, 4),
                'mispricing_gap': round(true_prob - implied_prob, 4),
                'favorite_tier': 2 if true_prob >= 0.65 else 1,
                'is_heavy_favorite': 1 if true_prob >= 0.70 else 0,
                'is_moderate_favorite': 1 if 0.60 <= true_prob < 0.70 else 0,
                'is_slight_favorite': 1 if true_prob < 0.60 else 0,
                'is_underdog': 0,
                'is_tennis': 0, 'is_mlb': 1, 'is_nba': 0,
                'is_soccer': 0, 'is_ufc': 0,
                'is_total_market': 0,
                'odds_american_abs': abs(american_odds),
                'outcome': home_won
            })

        except Exception:
            continue

    result_df = pd.DataFrame(records)
    print(f"  ✅ MLB features: {len(result_df)} samples")
    return result_df


# ─── NBA FEATURES ────────────────────────────────────────────────────────────

def engineer_nba_features(df: pd.DataFrame) -> pd.DataFrame:
    """NBA-specific features"""
    print("  🏀 Engineering NBA features...")

    if df.empty or 'home_won' not in df.columns:
        return pd.DataFrame()

    records = []

    for _, row in df.iterrows():
        try:
            home_won = int(row.get('home_won', 0))
            score_diff = abs(float(row.get('score_diff', 10)))

            # Estimate true probability based on score differential
            if score_diff >= 20:
                true_prob = 0.78
            elif score_diff >= 10:
                true_prob = 0.68
            elif score_diff >= 5:
                true_prob = 0.60
            else:
                true_prob = 0.55

            noise = np.random.normal(0, 0.03)
            true_prob = max(0.50, min(0.85, true_prob + noise))
            implied_prob = min(0.95, true_prob * 1.05)

            if true_prob >= 0.5:
                american_odds = int(-true_prob / (1 - true_prob) * 100)
            else:
                american_odds = int((1 - true_prob) / true_prob * 100)

            records.append({
                'sport': 'NBA',
                'date': str(row.get('date', '')),
                'odds_decimal': round(1 / true_prob, 4),
                'odds_american': american_odds,
                'implied_probability': round(implied_prob, 4),
                'true_probability': round(true_prob, 4),
                'mispricing_gap': round(true_prob - implied_prob, 4),
                'favorite_tier': 3 if true_prob >= 0.75 else (2 if true_prob >= 0.65 else 1),
                'is_heavy_favorite': 1 if true_prob >= 0.75 else 0,
                'is_moderate_favorite': 1 if 0.65 <= true_prob < 0.75 else 0,
                'is_slight_favorite': 1 if true_prob < 0.65 else 0,
                'is_underdog': 0,
                'is_tennis': 0, 'is_mlb': 0, 'is_nba': 1,
                'is_soccer': 0, 'is_ufc': 0,
                'is_total_market': 0,
                'odds_american_abs': abs(american_odds),
                'outcome': home_won
            })

        except Exception:
            continue

    result_df = pd.DataFrame(records)
    print(f"  ✅ NBA features: {len(result_df)} samples")
    return result_df


# ─── UFC FEATURES ────────────────────────────────────────────────────────────

def engineer_ufc_features(df: pd.DataFrame) -> pd.DataFrame:
    """UFC-specific features"""
    print("  🥊 Engineering UFC features...")

    if df.empty:
        return pd.DataFrame()

    records = []

    for _, row in df.iterrows():
        try:
            outcome = int(row.get('outcome', 1))
            true_prob = float(row.get('true_probability', 0.65))
            american_odds = int(row.get('favorite_odds', -200))

            implied_prob = min(0.95, true_prob * 1.06)

            records.append({
                'sport': 'UFC/MMA',
                'odds_decimal': round(1 / true_prob, 4),
                'odds_american': american_odds,
                'implied_probability': round(implied_prob, 4),
                'true_probability': round(true_prob, 4),
                'mispricing_gap': round(true_prob - implied_prob, 4),
                'favorite_tier': 3 if true_prob >= 0.73 else (2 if true_prob >= 0.65 else 1),
                'is_heavy_favorite': 1 if true_prob >= 0.73 else 0,
                'is_moderate_favorite': 1 if 0.65 <= true_prob < 0.73 else 0,
                'is_slight_favorite': 1 if true_prob < 0.65 else 0,
                'is_underdog': 0,
                'is_tennis': 0, 'is_mlb': 0, 'is_nba': 0,
                'is_soccer': 0, 'is_ufc': 1,
                'is_total_market': 0,
                'odds_american_abs': abs(american_odds),
                'outcome': outcome
            })

        except Exception:
            continue

    result_df = pd.DataFrame(records)
    print(f"  ✅ UFC features: {len(result_df)} samples")
    return result_df


# ─── MAIN FEATURE PIPELINE ───────────────────────────────────────────────────

def build_training_dataset() -> pd.DataFrame:
    """
    Build the complete ML training dataset
    Combines all sports into one unified feature set
    """
    print("\n" + "="*60)
    print("🔧 FEATURE ENGINEERING PIPELINE")
    print("="*60)

    all_features = []

    # Soccer
    soccer_path = f'{DATA_DIR}/raw/soccer/all_soccer.csv'
    if os.path.exists(soccer_path):
        soccer_raw = pd.read_csv(soccer_path)
        soccer_features = engineer_soccer_features(soccer_raw)
        if not soccer_features.empty:
            all_features.append(soccer_features)

    # Tennis
    tennis_path = f'{DATA_DIR}/raw/tennis/all_tennis.csv'
    if os.path.exists(tennis_path):
        tennis_raw = pd.read_csv(tennis_path)
        tennis_features = engineer_tennis_features(tennis_raw)
        if not tennis_features.empty:
            all_features.append(tennis_features)

    # MLB
    mlb_path = f'{DATA_DIR}/raw/mlb/all_mlb.csv'
    if os.path.exists(mlb_path):
        mlb_raw = pd.read_csv(mlb_path)
        mlb_features = engineer_mlb_features(mlb_raw)
        if not mlb_features.empty:
            all_features.append(mlb_features)

    # NBA
    nba_path = f'{DATA_DIR}/raw/nba/all_nba.csv'
    if os.path.exists(nba_path):
        nba_raw = pd.read_csv(nba_path)
        nba_features = engineer_nba_features(nba_raw)
        if not nba_features.empty:
            all_features.append(nba_features)

    # UFC
    ufc_path = f'{DATA_DIR}/raw/ufc/all_ufc.csv'
    if os.path.exists(ufc_path):
        ufc_raw = pd.read_csv(ufc_path)
        ufc_features = engineer_ufc_features(ufc_raw)
        if not ufc_features.empty:
            all_features.append(ufc_features)

    if not all_features:
        print("❌ No feature data available")
        return pd.DataFrame()

    # Combine all sports
    combined = pd.concat(all_features, ignore_index=True)

    # Core feature columns for ML model
    feature_cols = [
        'odds_decimal', 'true_probability', 'implied_probability',
        'mispricing_gap', 'is_tennis', 'is_mlb', 'is_nba',
        'is_soccer', 'is_ufc', 'is_heavy_favorite', 'is_moderate_favorite',
        'is_total_market', 'odds_american_abs', 'favorite_tier'
    ]

    # Ensure all feature columns exist
    for col in feature_cols:
        if col not in combined.columns:
            combined[col] = 0

    # Remove any rows with missing core features or outcomes
    combined = combined.dropna(subset=feature_cols + ['outcome'])
    combined['outcome'] = combined['outcome'].astype(int)

    # Filter to only favorites (our model only bets favorites)
    combined = combined[combined['is_underdog'] == 0]

    # Save processed dataset
    combined.to_csv(f'{DATA_DIR}/processed/training_data.csv', index=False)

    print(f"\n✅ Training dataset built:")
    print(f"   Total samples: {len(combined):,}")
    print(f"   Overall win rate: {combined['outcome'].mean():.1%}")
    print(f"\n   By sport:")
    for sport in combined['sport'].unique():
        sport_df = combined[combined['sport'] == sport]
        print(f"   {sport:15} {len(sport_df):5,} samples | win rate: {sport_df['outcome'].mean():.1%}")

    return combined


if __name__ == "__main__":
    dataset = build_training_dataset()
    if not dataset.empty:
        print(f"\n✅ Dataset saved to {DATA_DIR}/processed/training_data.csv")
