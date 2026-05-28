"""
EdgeParlay Data Pipeline
Pulls live odds from The Odds API across all sports
Stores snapshots in Supabase for analysis
"""
import os
import sys
import requests
import json
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client
from typing import Optional

load_dotenv('/home/claude/edgeparlay/.env')

ODDS_API_KEY = os.getenv('ODDS_API_KEY')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

BASE_URL = "https://api.the-odds-api.com/v4"

# Sports we track - mapped to Odds API sport keys
SPORTS = {
    "baseball_mlb": "MLB",
    "basketball_nba": "NBA",
    "soccer_epl": "EPL Soccer",
    "soccer_uefa_champs_league": "Champions League",
    "soccer_usa_mls": "MLS Soccer",
    "mma_mixed_martial_arts": "UFC/MMA",
    "tennis_atp_french_open": "Tennis ATP",
    "tennis_wta_french_open": "Tennis WTA",
}

# Bookmakers we care about in Kansas
BOOKMAKERS = ["fanduel", "draftkings", "betmgm", "caesars", "espnbet"]

# Markets to analyze
MARKETS = ["h2h", "spreads", "totals"]

def american_to_decimal(american: int) -> float:
    """Convert American odds to decimal"""
    if american > 0:
        return 1 + (american / 100)
    else:
        return 1 - (100 / american)

def decimal_to_implied(decimal: float) -> float:
    """Convert decimal odds to implied probability"""
    return 1 / decimal

def american_to_implied(american: int) -> float:
    """Convert American odds to implied probability (with vig removed)"""
    return decimal_to_implied(american_to_decimal(american))

def remove_vig(prob1: float, prob2: float) -> tuple:
    """Remove vig from two-sided market to get true probabilities"""
    total = prob1 + prob2
    return prob1 / total, prob2 / total

def get_available_sports() -> list:
    """Get all currently available sports from the API"""
    url = f"{BASE_URL}/sports"
    params = {"apiKey": ODDS_API_KEY}
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        sports = response.json()
        # Filter to only active sports
        active = [s for s in sports if s.get('active', False)]
        print(f"✅ Found {len(active)} active sports")
        return active
    except Exception as e:
        print(f"❌ Error fetching sports: {e}")
        return []

def get_odds_for_sport(sport_key: str) -> list:
    """Get odds for a specific sport"""
    url = f"{BASE_URL}/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "american",
        "bookmakers": ",".join(BOOKMAKERS)
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        
        # Check remaining requests
        remaining = response.headers.get('x-requests-remaining', 'unknown')
        used = response.headers.get('x-requests-used', 'unknown')
        
        if response.status_code == 200:
            events = response.json()
            print(f"  ✅ {SPORTS.get(sport_key, sport_key)}: {len(events)} events | API calls remaining: {remaining}")
            return events
        elif response.status_code == 404:
            print(f"  ℹ️  {sport_key}: No events currently available (off-season)")
            return []
        else:
            print(f"  ❌ {sport_key}: API error {response.status_code}")
            return []
    except Exception as e:
        print(f"  ❌ Error fetching {sport_key}: {e}")
        return []

def process_event(sport_key: str, event: dict) -> list:
    """Process a single event and extract all betting opportunities"""
    opportunities = []
    
    event_id = event.get('id', '')
    event_name = f"{event.get('home_team', '')} vs {event.get('away_team', '')}"
    commence_time = event.get('commence_time', '')
    sport_name = SPORTS.get(sport_key, sport_key)
    
    bookmakers = event.get('bookmakers', [])
    
    for bookmaker in bookmakers:
        book_key = bookmaker.get('key', '')
        book_name = bookmaker.get('title', '')
        
        if book_key not in BOOKMAKERS:
            continue
            
        markets = bookmaker.get('markets', [])
        
        for market in markets:
            market_key = market.get('key', '')
            outcomes = market.get('outcomes', [])
            
            if len(outcomes) < 2:
                continue
            
            # For h2h markets, calculate no-vig probabilities
            if market_key == 'h2h' and len(outcomes) >= 2:
                odds_list = []
                for outcome in outcomes:
                    price = outcome.get('price', 0)
                    if price != 0:
                        implied = american_to_implied(price)
                        odds_list.append({
                            'name': outcome.get('name', ''),
                            'odds': price,
                            'implied': implied
                        })
                
                if len(odds_list) >= 2:
                    # Remove vig for two-sided market
                    total_implied = sum(o['implied'] for o in odds_list)
                    
                    for odd in odds_list:
                        true_prob = odd['implied'] / total_implied
                        decimal_odds = american_to_decimal(odd['odds'])
                        
                        opportunities.append({
                            'sport': sport_name,
                            'event_id': event_id,
                            'event_name': event_name,
                            'commence_time': commence_time,
                            'market': f"{market_key}_{market.get('key', '')}",
                            'selection': odd['name'],
                            'bookmaker': book_name,
                            'odds_american': odd['odds'],
                            'odds_decimal': round(decimal_odds, 4),
                            'implied_probability': round(odd['implied'], 4),
                            'true_probability': round(true_prob, 4),
                            'snapshot_time': datetime.now(timezone.utc).isoformat()
                        })
            
            # For spreads and totals
            elif market_key in ['spreads', 'totals']:
                for outcome in outcomes:
                    price = outcome.get('price', 0)
                    if price == 0:
                        continue
                    
                    implied = american_to_implied(price)
                    decimal_odds = american_to_decimal(price)
                    point = outcome.get('point', '')
                    selection_name = f"{outcome.get('name', '')} {point}" if point else outcome.get('name', '')
                    
                    opportunities.append({
                        'sport': sport_name,
                        'event_id': event_id,
                        'event_name': event_name,
                        'commence_time': commence_time,
                        'market': market_key,
                        'selection': selection_name,
                        'bookmaker': book_name,
                        'odds_american': price,
                        'odds_decimal': round(decimal_odds, 4),
                        'implied_probability': round(implied, 4),
                        'true_probability': round(implied, 4),
                        'snapshot_time': datetime.now(timezone.utc).isoformat()
                    })
    
    return opportunities

def save_to_supabase(opportunities: list, supabase_client) -> bool:
    """Save odds snapshots to Supabase"""
    if not opportunities:
        return True
    
    try:
        # Batch insert in chunks of 100
        chunk_size = 100
        total_saved = 0
        
        for i in range(0, len(opportunities), chunk_size):
            chunk = opportunities[i:i + chunk_size]
            result = supabase_client.table('odds_snapshots').insert(chunk).execute()
            total_saved += len(chunk)
        
        print(f"  ✅ Saved {total_saved} odds snapshots to database")
        return True
    except Exception as e:
        print(f"  ❌ Error saving to Supabase: {e}")
        return False

def find_best_odds_per_outcome(opportunities: list) -> list:
    """Find the best available odds for each outcome across all bookmakers"""
    best_odds = {}
    
    for opp in opportunities:
        key = f"{opp['event_id']}_{opp['market']}_{opp['selection']}"
        
        if key not in best_odds:
            best_odds[key] = opp
        else:
            # Keep the best (highest) odds
            if opp['odds_american'] > best_odds[key]['odds_american']:
                best_odds[key] = opp
    
    return list(best_odds.values())

def run_pipeline(save_to_db: bool = True) -> dict:
    """
    Main pipeline function
    Returns all available opportunities across all sports
    """
    print("\n" + "="*60)
    print("🚀 EDGEPARLAY DATA PIPELINE STARTING")
    print(f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    # Connect to Supabase
    supabase_client = None
    if save_to_db:
        try:
            supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
            print("✅ Connected to Supabase")
        except Exception as e:
            print(f"⚠️  Supabase connection failed: {e}")
            print("   Continuing without database save...")
            save_to_db = False
    
    all_opportunities = []
    sports_processed = 0
    
    # Process each sport
    print("\n📡 Fetching live odds...")
    for sport_key, sport_name in SPORTS.items():
        events = get_odds_for_sport(sport_key)
        
        if not events:
            continue
            
        sport_opportunities = []
        for event in events:
            opps = process_event(sport_key, event)
            sport_opportunities.extend(opps)
        
        if sport_opportunities:
            all_opportunities.extend(sport_opportunities)
            sports_processed += 1
            
            # Save to database
            if save_to_db and supabase_client:
                save_to_supabase(sport_opportunities, supabase_client)
    
    # Find best odds per outcome
    best_opportunities = find_best_odds_per_outcome(all_opportunities)
    
    print("\n" + "="*60)
    print(f"✅ PIPELINE COMPLETE")
    print(f"   Sports with data: {sports_processed}")
    print(f"   Total opportunities: {len(all_opportunities)}")
    print(f"   Unique best-odds opportunities: {len(best_opportunities)}")
    print("="*60 + "\n")
    
    return {
        'all_opportunities': all_opportunities,
        'best_opportunities': best_opportunities,
        'sports_processed': sports_processed,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }

if __name__ == "__main__":
    result = run_pipeline(save_to_db=False)  # Test without DB first
    
    if result['best_opportunities']:
        print("\n📊 SAMPLE OPPORTUNITIES:")
        print("-"*60)
        for opp in result['best_opportunities'][:10]:
            print(f"  {opp['sport']:15} | {opp['event_name'][:30]:30} | {opp['selection']:20} | {opp['odds_american']:+5d} | {opp['true_probability']:.1%}")
        print(f"\n  ... and {len(result['best_opportunities']) - 10} more opportunities")
    else:
        print("\n⚠️  No opportunities found. Check API key or try again during active sports hours.")
