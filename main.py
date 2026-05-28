"""
EdgeParlay Main Orchestrator
On startup: checks for trained model, trains if missing
Then runs daily scheduler
"""
import os
import sys
import json
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.pipeline import run_pipeline
from backend.confidence_engine import ConfidenceEngine
from backend.parlay_constructor import ParlayConstructor
from backend.telegram_bot import (
    send_morning_parlay,
    send_no_bet_alert,
    send_final_confirmation,
    send_welcome_message
)

MODEL_PATH = os.path.join(os.path.dirname(__file__), 'models', 'edgeparlay_model.pkl')
DATA_PATH = os.path.join(os.path.dirname(__file__), 'data', 'processed', 'training_data.csv')

def ensure_model_exists():
    """Train model on startup if it doesn't exist"""
    if os.path.exists(MODEL_PATH):
        print("✅ Trained model found")
        return True

    print("⚠️  No trained model found. Training now...")
    print("   This takes 2-3 minutes on first startup...")

    try:
        os.makedirs('models', exist_ok=True)
        os.makedirs('data/raw/tennis', exist_ok=True)
        os.makedirs('data/raw/ufc', exist_ok=True)
        os.makedirs('data/processed', exist_ok=True)

        # Download data
        from scripts.download_data import download_all
        download_all()

        # Build features
        from scripts.feature_engineering import build_training_dataset
        df = build_training_dataset()

        if df.empty:
            print("❌ No training data available")
            return False

        # Train model
        from scripts.train_model import train_model
        result = train_model(df)

        if result:
            print("✅ Model trained and saved successfully")
            return True
        else:
            print("❌ Model training failed")
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
    except Exception as e:
        print(f"⚠️ Could not fetch bankroll: {e}")
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
            parlay_id = result.data[0]['id']
            print(f"✅ Parlay saved to database (ID: {parlay_id})")
            return parlay_id
    except Exception as e:
        print(f"⚠️ Could not save parlay: {e}")
    return -1

def run_morning_picks():
    print(f"\n{'='*60}")
    print(f"🌅 MORNING PICKS — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    bankroll = get_bankroll()
    print(f"💰 Current bankroll: ${bankroll:.2f}")

    pipeline_result = run_pipeline(save_to_db=True)
    opportunities = pipeline_result.get('best_opportunities', [])

    if not opportunities:
        print("⚠️  No odds data available.")
        send_no_bet_alert("No live odds data available. Check back later.")
        return None

    engine = ConfidenceEngine()
    engine.set_regime('normal', 1.0)
    scored = engine.score_all(opportunities)

    if not scored:
        print("⚠️  No high-confidence opportunities found today.")
        send_no_bet_alert("Model confidence too low across all available markets. Protecting bankroll.")
        return None

    constructor = ParlayConstructor(bankroll=bankroll)
    parlay = constructor.build_optimal_parlay(scored)
    should_bet, reason = constructor.should_bet_today(parlay)

    if not should_bet or not parlay:
        print(f"⚠️  No bet today: {reason}")
        send_no_bet_alert(reason)
        return None

    parlay_id = save_parlay(parlay)
    parlay['id'] = parlay_id

    print(constructor.format_parlay_summary(parlay))
    send_morning_parlay(parlay)

    print(f"\n✅ Morning picks complete. Parlay sent to Telegram.")
    return parlay

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

    print("🚀 EdgeParlay Scheduler started")
    print("⏰ Morning picks scheduled: 6:00 AM Central daily")
    print("Press Ctrl+C to stop\n")

    send_welcome_message()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\n👋 EdgeParlay scheduler stopped")

if __name__ == "__main__":
    import sys

    # Always ensure model exists on startup
    ensure_model_exists()

    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == 'morning':
            run_morning_picks()
        elif command == 'welcome':
            send_welcome_message()
        elif command == 'schedule':
            run_scheduler()
        elif command == 'train':
            # Force retrain
            if os.path.exists(MODEL_PATH):
                os.remove(MODEL_PATH)
            ensure_model_exists()
        else:
            print(f"Unknown command: {command}")
    else:
        run_scheduler()


def run_web_server():
    """Run the FastAPI dashboard server"""
    import uvicorn
    from backend.api import app
    port = int(os.getenv('PORT', 8000))
    print(f"🌐 Dashboard starting on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)


def run_all():
    """Run both scheduler and web server in parallel threads"""
    import threading

    # Start scheduler in background thread
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    # Run web server in main thread
    run_web_server()
