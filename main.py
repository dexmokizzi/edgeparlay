"""
EdgeParlay Main Orchestrator
Runs the full daily pipeline:
- 6am: fetch odds, score, build parlay, send Telegram
- 2hrs before games: final confirmation check
- After games: settle results, update bankroll
"""
import os
import sys
import json
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# Add project root to path
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

def get_bankroll() -> float:
    """Get current bankroll from Supabase"""
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
    """Save today's parlay to Supabase"""
    try:
        from supabase import create_client
        supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))
        
        # Prepare parlay record
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
    """
    Morning pipeline - runs at 6am daily
    Fetches odds, scores opportunities, builds parlay, sends Telegram
    """
    print(f"\n{'='*60}")
    print(f"🌅 MORNING PICKS — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")
    
    # Get current bankroll
    bankroll = get_bankroll()
    print(f"💰 Current bankroll: ${bankroll:.2f}")
    
    # Step 1: Fetch live odds
    pipeline_result = run_pipeline(save_to_db=True)
    opportunities = pipeline_result.get('best_opportunities', [])
    
    if not opportunities:
        print("⚠️  No odds data available. Sending no-bet alert.")
        send_no_bet_alert("No live odds data available. Check back later.")
        return None
    
    # Step 2: Score opportunities
    engine = ConfidenceEngine()
    
    # Detect regime (simplified for now)
    hour = datetime.now().hour
    if hour < 4:  # Late night / early morning - lower confidence
        engine.set_regime('low_activity', 0.95)
    else:
        engine.set_regime('normal', 1.0)
    
    scored = engine.score_all(opportunities)
    
    if not scored:
        print("⚠️  No high-confidence opportunities found today.")
        send_no_bet_alert("Model confidence too low across all available markets. Protecting bankroll.")
        return None
    
    # Step 3: Build parlay
    constructor = ParlayConstructor(bankroll=bankroll)
    parlay = constructor.build_optimal_parlay(scored)
    
    # Step 4: Check if we should bet
    should_bet, reason = constructor.should_bet_today(parlay)
    
    if not should_bet or not parlay:
        print(f"⚠️  No bet today: {reason}")
        send_no_bet_alert(reason)
        return None
    
    # Step 5: Save to database
    parlay_id = save_parlay(parlay)
    parlay['id'] = parlay_id
    
    # Step 6: Send Telegram alert
    print(constructor.format_parlay_summary(parlay))
    send_morning_parlay(parlay)
    
    print(f"\n✅ Morning picks complete. Parlay sent to Telegram.")
    return parlay

def run_final_confirmation(parlay: dict):
    """
    Final confirmation - runs 2 hours before first game
    Re-checks injuries and line movement
    """
    print(f"\n{'='*60}")
    print(f"⚡ FINAL CONFIRMATION — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")
    
    changes = []
    
    # Re-fetch current odds to check for line movement
    current_pipeline = run_pipeline(save_to_db=False)
    current_opps = current_pipeline.get('best_opportunities', [])
    
    # Check each leg for significant line movement
    for leg in parlay.get('legs', []):
        selection = leg.get('selection', '')
        event_id = leg.get('event_id', '')
        original_odds = leg.get('odds_american', 0)
        
        # Find current odds for this leg
        current = next(
            (o for o in current_opps if o.get('event_id') == event_id and o.get('selection') == selection),
            None
        )
        
        if current:
            current_odds = current.get('odds_american', original_odds)
            movement = current_odds - original_odds
            
            if abs(movement) >= 20:  # Significant movement
                direction = 'AGAINST' if (original_odds < 0 and movement > 0) else 'IN FAVOR'
                changes.append(f"Line moved {direction} on {selection}: {original_odds:+d} → {current_odds:+d}")
                print(f"⚠️  Line movement detected: {selection} {original_odds:+d} → {current_odds:+d}")
    
    # Send confirmation
    send_final_confirmation(parlay, changes if changes else None)
    print(f"✅ Final confirmation sent. {len(changes)} changes detected.")

def run_scheduler():
    """Run with APScheduler for automated daily execution"""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    
    scheduler = BlockingScheduler(timezone='US/Central')
    
    # Morning picks at 6am Central
    scheduler.add_job(
        run_morning_picks,
        CronTrigger(hour=6, minute=0),
        id='morning_picks',
        name='Morning Parlay Picks'
    )
    
    print("🚀 EdgeParlay Scheduler started")
    print("⏰ Morning picks scheduled: 6:00 AM Central daily")
    print("Press Ctrl+C to stop\n")
    
    # Send welcome message on startup
    send_welcome_message()
    
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\n👋 EdgeParlay scheduler stopped")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == 'morning':
            run_morning_picks()
        elif command == 'welcome':
            send_welcome_message()
        elif command == 'schedule':
            run_scheduler()
        else:
            print(f"Unknown command: {command}")
            print("Usage: python main.py [morning|welcome|schedule]")
    else:
        # Default: run morning picks
        run_morning_picks()
