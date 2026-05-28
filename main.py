"""
EdgeParlay Main
Web server starts FIRST, then model trains in background
"""
import os
import sys
import json
import threading
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models', 'edgeparlay_model.pkl')
MODEL_READY = False

def ensure_model_exists():
    global MODEL_READY
    if os.path.exists(MODEL_PATH):
        print("✅ Trained model found")
        MODEL_READY = True
        return True
    print("⚠️  No trained model found. Training in background...")
    try:
        os.makedirs('models', exist_ok=True)
        os.makedirs('data/raw/tennis', exist_ok=True)
        os.makedirs('data/raw/ufc', exist_ok=True)
        os.makedirs('data/processed', exist_ok=True)
        from scripts.download_data import download_all
        download_all()
        from scripts.feature_engineering import build_training_dataset
        df = build_training_dataset()
        if df.empty:
            print("❌ No training data available")
            return False
        from scripts.train_model import train_model
        result = train_model(df)
        if result:
            print("✅ Model trained and saved successfully")
            MODEL_READY = True
            return True
        return False
    except Exception as e:
        print(f"❌ Training error: {e}")
        return False

def get_bankroll() -> float:
    try:
        from supabase import create_client
        supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))
        result = supabase.table('bankroll').select('amount').order('id', desc=True).limit(1).execute()
        if result.data:
            return float(result.data[0]['amount'])
    except:
        pass
    return float(os.getenv('BANKROLL', 100))

def save_parlay(parlay: dict) -> int:
    try:
        from supabase import create_client
        supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))
        record = {
            'date': parlay['date'],
            'legs': json.dumps(parlay['legs']),
            'combined_odds': parlay['combined_odds'],
            'confidence_tier': parlay['confidence_tier'],
            'overall_confidence': parlay['avg_confidence'],
            'stake': parlay['stake'],
            'potential_payout': parlay['potential_payout'],
            'bet_type': parlay['bet_type'],
            'platform': parlay['platform'],
            'status': 'pending',
            'regime': parlay.get('regime', 'normal')
        }
        result = supabase.table('parlays').insert(record).execute()
        if result.data:
            return result.data[0]['id']
    except Exception as e:
        print(f"⚠️ Could not save parlay: {e}")
    return -1

def run_morning_picks():
    print(f"\n{'='*60}")
    print(f"🌅 MORNING PICKS — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")
    try:
        from backend.pipeline import run_pipeline
        from backend.confidence_engine import ConfidenceEngine
        from backend.parlay_constructor import ParlayConstructor
        from backend.telegram_bot import send_morning_parlay, send_no_bet_alert

        bankroll = get_bankroll()
        pipeline_result = run_pipeline(save_to_db=True)
        opportunities = pipeline_result.get('best_opportunities', [])

        if not opportunities:
            send_no_bet_alert("No live odds data available.")
            return None

        engine = ConfidenceEngine()
        engine.set_regime('normal', 1.0)
        scored = engine.score_all(opportunities)

        if not scored:
            send_no_bet_alert("Model confidence too low. Protecting bankroll.")
            return None

        constructor = ParlayConstructor(bankroll=bankroll)
        parlay = constructor.build_optimal_parlay(scored)
        should_bet, reason = constructor.should_bet_today(parlay)

        if not should_bet or not parlay:
            send_no_bet_alert(reason)
            return None

        parlay['id'] = save_parlay(parlay)
        print(constructor.format_parlay_summary(parlay))
        send_morning_parlay(parlay)
        return parlay
    except Exception as e:
        print(f"❌ Morning picks error: {e}")
        return None

def run_scheduler():
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BlockingScheduler(timezone='US/Central')
    scheduler.add_job(
        run_morning_picks,
        CronTrigger(hour=6, minute=0),
        id='morning_picks',
        name='Morning Parlay Picks'
    )
    print("⏰ Scheduler: 6:00 AM Central daily")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else 'serve'

    if command == 'morning':
        ensure_model_exists()
        run_morning_picks()
    elif command == 'schedule':
        ensure_model_exists()
        run_scheduler()
    elif command == 'train':
        if os.path.exists(MODEL_PATH):
            os.remove(MODEL_PATH)
        ensure_model_exists()
    else:
        # DEFAULT: start web server FIRST, train model + scheduler in background
        print("🚀 EdgeParlay starting...")

        # Train model in background thread (non-blocking)
        training_thread = threading.Thread(target=ensure_model_exists, daemon=True)
        training_thread.start()

        # Scheduler in background thread
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()

        # Web server starts IMMEDIATELY in main thread
        from backend.api import app
        import uvicorn
        port = int(os.getenv('PORT', 8000))
        print(f"🌐 Dashboard → http://0.0.0.0:{port}")
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")