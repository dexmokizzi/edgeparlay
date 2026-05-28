"""
EdgeParlay ML Model Trainer
LightGBM with:
- Walk-forward backtesting
- Platt scaling calibration
- Brier score validation
- CLV analysis
- Model serialization for deployment
"""
import os
import sys
import pickle
import numpy as np
import pandas as pd
from datetime import datetime
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold
import lightgbm as lgb
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = '/home/claude/edgeparlay/data'
MODEL_DIR = '/home/claude/edgeparlay/models'
os.makedirs(MODEL_DIR, exist_ok=True)

FEATURE_COLS = [
    'odds_decimal', 'true_probability', 'implied_probability',
    'mispricing_gap', 'is_tennis', 'is_mlb', 'is_nba',
    'is_soccer', 'is_ufc', 'is_heavy_favorite', 'is_moderate_favorite',
    'is_total_market', 'odds_american_abs', 'favorite_tier'
]


def train_model(df: pd.DataFrame) -> dict:
    """
    Train LightGBM model with full validation pipeline
    Returns trained model + performance metrics
    """
    print("\n" + "="*60)
    print("🧠 EDGEPARLAY ML MODEL TRAINER")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    if df.empty:
        print("❌ No training data available")
        return {}

    print(f"\n📊 Training data: {len(df):,} samples")
    print(f"   Win rate: {df['outcome'].mean():.1%}")

    # Prepare features and labels
    X = df[FEATURE_COLS].values
    y = df['outcome'].values

    # ── Step 1: Walk-Forward Validation ──────────────────────────────────────
    print("\n🔄 Running walk-forward validation...")

    wf_results = []
    n_splits = 5
    split_size = len(df) // (n_splits + 1)

    for i in range(n_splits):
        train_end = (i + 1) * split_size
        test_start = train_end
        test_end = test_start + split_size

        X_train = X[:train_end]
        y_train = y[:train_end]
        X_test = X[test_start:test_end]
        y_test = y[test_start:test_end]

        if len(X_train) < 100 or len(X_test) < 50:
            continue

        # Train base model
        base = lgb.LGBMClassifier(
            max_depth=4,
            num_leaves=31,
            learning_rate=0.03,
            n_estimators=300,
            subsample=0.7,
            colsample_bytree=0.7,
            min_child_samples=50,
            reg_alpha=0.1,
            reg_lambda=0.1,
            random_state=42,
            verbose=-1
        )

        # Calibrate with Platt scaling
        calibrated = CalibratedClassifierCV(base, cv=3, method='sigmoid')
        calibrated.fit(X_train, y_train)

        # Evaluate
        probs = calibrated.predict_proba(X_test)[:, 1]
        brier = brier_score_loss(y_test, probs)
        auc = roc_auc_score(y_test, probs)
        win_rate = y_test.mean()

        # CLV simulation: did high-confidence picks beat the market?
        high_conf_mask = probs >= 0.65
        if high_conf_mask.sum() > 0:
            high_conf_win_rate = y_test[high_conf_mask].mean()
        else:
            high_conf_win_rate = 0

        wf_results.append({
            'fold': i + 1,
            'train_size': len(X_train),
            'test_size': len(X_test),
            'brier_score': brier,
            'auc': auc,
            'win_rate': win_rate,
            'high_conf_win_rate': high_conf_win_rate,
            'high_conf_picks': int(high_conf_mask.sum())
        })

        print(f"  Fold {i+1}: Brier={brier:.4f} | AUC={auc:.3f} | "
              f"Win Rate={win_rate:.1%} | High Conf Win={high_conf_win_rate:.1%} "
              f"({int(high_conf_mask.sum())} picks)")

    if wf_results:
        avg_brier = np.mean([r['brier_score'] for r in wf_results])
        avg_auc = np.mean([r['auc'] for r in wf_results])
        avg_hc_wr = np.mean([r['high_conf_win_rate'] for r in wf_results])

        print(f"\n  📊 Walk-Forward Summary:")
        print(f"     Avg Brier Score: {avg_brier:.4f} (lower = better, 0.25 = random)")
        print(f"     Avg AUC: {avg_auc:.3f} (higher = better, 0.5 = random)")
        print(f"     Avg High-Conf Win Rate: {avg_hc_wr:.1%}")

    # ── Step 2: Train Final Model on Full Dataset ─────────────────────────────
    print("\n🎯 Training final model on full dataset...")

    final_base = lgb.LGBMClassifier(
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

    final_model = CalibratedClassifierCV(final_base, cv=5, method='sigmoid')
    final_model.fit(X, y)

    # Final predictions for calibration check
    final_probs = final_model.predict_proba(X)[:, 1]
    final_brier = brier_score_loss(y, final_probs)

    print(f"  ✅ Final model Brier Score: {final_brier:.4f}")

    # ── Step 3: Calibration Curve ─────────────────────────────────────────────
    print("\n📈 Calibration analysis:")
    fraction_of_positives, mean_predicted_value = calibration_curve(
        y, final_probs, n_bins=10
    )

    calibration_data = []
    for i, (fop, mpv) in enumerate(zip(fraction_of_positives, mean_predicted_value)):
        gap = abs(fop - mpv)
        status = "✅" if gap < 0.05 else ("⚠️" if gap < 0.10 else "❌")
        print(f"  {status} Predicted: {mpv:.0%} → Actual: {fop:.0%} (gap: {gap:.1%})")
        calibration_data.append({'predicted': mpv, 'actual': fop, 'gap': gap})

    avg_calibration_gap = np.mean([d['gap'] for d in calibration_data])
    print(f"\n  Average calibration gap: {avg_calibration_gap:.1%}")

    # ── Step 4: Feature Importance ────────────────────────────────────────────
    print("\n🔍 Feature importance:")
    try:
        # Extract feature importance from the base model
        base_model = final_model.calibrated_classifiers_[0].estimator
        importances = base_model.feature_importances_

        feat_imp = sorted(
            zip(FEATURE_COLS, importances),
            key=lambda x: x[1],
            reverse=True
        )

        for feat, imp in feat_imp[:8]:
            bar = '█' * int(imp / max(importances) * 20)
            print(f"  {feat:25} {bar} {imp:.0f}")
    except Exception as e:
        print(f"  ⚠️  Could not extract feature importance: {e}")

    # ── Step 5: Sport-specific performance ───────────────────────────────────
    print("\n🏆 Performance by sport:")
    sport_cols = {
        'Tennis': 'is_tennis', 'MLB': 'is_mlb', 'NBA': 'is_nba',
        'Soccer': 'is_soccer', 'UFC': 'is_ufc'
    }

    for sport_name, sport_col in sport_cols.items():
        if sport_col in df.columns:
            mask = df[sport_col] == 1
            if mask.sum() > 50:
                sport_X = X[mask]
                sport_y = y[mask]
                sport_probs = final_probs[mask]
                sport_brier = brier_score_loss(sport_y, sport_probs)
                sport_win_rate = sport_y.mean()

                # High confidence picks for this sport
                hc_mask = sport_probs >= 0.65
                hc_wr = sport_y[hc_mask].mean() if hc_mask.sum() > 0 else 0

                print(f"  {sport_name:10} | {mask.sum():5,} samples | "
                      f"Win Rate: {sport_win_rate:.1%} | "
                      f"High Conf Win: {hc_wr:.1%} | Brier: {sport_brier:.4f}")

    # ── Step 6: Save Model ────────────────────────────────────────────────────
    model_path = f'{MODEL_DIR}/edgeparlay_model.pkl'
    metadata = {
        'trained_at': datetime.now().isoformat(),
        'training_samples': len(df),
        'feature_cols': FEATURE_COLS,
        'brier_score': final_brier,
        'avg_calibration_gap': avg_calibration_gap,
        'walk_forward_results': wf_results,
        'sport_distribution': df['sport'].value_counts().to_dict() if 'sport' in df.columns else {}
    }

    with open(model_path, 'wb') as f:
        pickle.dump({'model': final_model, 'metadata': metadata}, f)

    # Save metadata separately as JSON for easy reading
    import json
    metadata_copy = metadata.copy()
    metadata_copy['walk_forward_results'] = [
        {k: float(v) if isinstance(v, (np.floating, np.integer)) else v
         for k, v in r.items()} for r in wf_results
    ]
    metadata_copy['sport_distribution'] = {
        k: int(v) for k, v in metadata_copy.get('sport_distribution', {}).items()
    }

    with open(f'{MODEL_DIR}/model_metadata.json', 'w') as f:
        json.dump(metadata_copy, f, indent=2)

    print(f"\n✅ Model saved to {model_path}")

    return {
        'model': final_model,
        'metadata': metadata,
        'brier_score': final_brier,
        'walk_forward_results': wf_results
    }


def load_model():
    """Load the trained model"""
    model_path = f'{MODEL_DIR}/edgeparlay_model.pkl'
    if not os.path.exists(model_path):
        return None, None

    with open(model_path, 'rb') as f:
        data = pickle.load(f)

    return data['model'], data['metadata']


def run_full_training():
    """Run the complete training pipeline"""
    sys.path.insert(0, '/home/claude/edgeparlay')

    # Step 1: Download data
    print("📥 Step 1: Downloading historical data...")
    from scripts.download_data import download_all
    download_all()

    # Step 2: Feature engineering
    print("\n🔧 Step 2: Building training dataset...")
    from scripts.feature_engineering import build_training_dataset
    df = build_training_dataset()

    if df.empty:
        print("❌ No training data. Cannot train model.")
        return None

    # Step 3: Train model
    print("\n🧠 Step 3: Training model...")
    result = train_model(df)

    if result:
        print("\n" + "="*60)
        print("🎉 TRAINING COMPLETE")
        print("="*60)
        print(f"   Model trained on {result['metadata']['training_samples']:,} samples")
        print(f"   Brier Score: {result['brier_score']:.4f}")
        print(f"   Model saved and ready for deployment")
        print("="*60)

    return result


if __name__ == "__main__":
    run_full_training()
