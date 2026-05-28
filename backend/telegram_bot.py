"""
EdgeParlay Telegram Bot
Sends daily parlay alerts and confirmations
"""
import os
import asyncio
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv('/home/claude/edgeparlay/.env')

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def send_message(text: str) -> bool:
    """Send a message via Telegram Bot API"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print(f"✅ Telegram message sent")
            return True
        else:
            print(f"❌ Telegram error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Telegram exception: {e}")
        return False

def send_morning_parlay(parlay: dict) -> bool:
    """Send morning parlay recommendation"""
    tier_emoji = '🟢' if parlay['confidence_tier'] == 'GREEN' else '🟡'
    
    legs_text = ""
    for i, leg in enumerate(parlay['legs'], 1):
        value_tag = ' 💎' if leg.get('is_value_bet') else ''
        legs_text += f"\n{i}. <b>{leg['selection']}</b>{value_tag}"
        legs_text += f"\n   {leg['sport']} | {leg['odds_american']:+d} | {leg['combined_confidence']:.0%} confidence"

    message = f"""
{tier_emoji} <b>EDGEPARLAY — MORNING BRIEF</b>
📅 {parlay['date']}
━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>TODAY'S PARLAY</b>
🎯 Combined Odds: <b>{parlay['combined_odds']:.2f}x</b>
📊 Win Probability: <b>{parlay['parlay_probability']:.1%}</b>
💰 Stake: <b>${parlay['stake']:.2f}</b>
💵 Potential Payout: <b>${parlay['potential_payout']:.2f}</b>
🏦 Platform: <b>{parlay['platform']}</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>LEGS ({parlay['num_legs']}):</b>
{legs_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━
⏰ <b>Final confirmation in 2 hours before games</b>
🎯 Value Anchor: {parlay['value_anchor']}
⚠️ Bet responsibly. 21+ only. Kansas only.
"""
    return send_message(message)

def send_no_bet_alert(reason: str) -> bool:
    """Send no-bet notification"""
    message = f"""
🔴 <b>EDGEPARLAY — NO BET TODAY</b>
📅 {datetime.now().strftime('%Y-%m-%d')}
━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>Reason:</b> {reason}

Protecting your bankroll is as important as finding good bets.
The model will look again tomorrow.

💰 Bankroll preserved. Stay disciplined.
"""
    return send_message(message)

def send_final_confirmation(parlay: dict, changes: list = None) -> bool:
    """Send 2-hour final confirmation"""
    if changes:
        changes_text = "\n⚠️ <b>CHANGES FROM MORNING PICK:</b>\n"
        for change in changes:
            changes_text += f"• {change}\n"
    else:
        changes_text = "\n✅ <b>No changes from morning pick</b>"

    message = f"""
✅ <b>EDGEPARLAY — FINAL CONFIRMATION</b>
📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}
━━━━━━━━━━━━━━━━━━━━━━━━━━

All legs re-checked. Injuries scanned. Lines verified.
{changes_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 Combined Odds: <b>{parlay['combined_odds']:.2f}x</b>
💰 Stake: <b>${parlay['stake']:.2f}</b>
💵 Potential: <b>${parlay['potential_payout']:.2f}</b>
🏦 Platform: <b>{parlay['platform']}</b>

<b>👉 PLACE YOUR BET NOW ON {parlay['platform'].upper()}</b>
"""
    return send_message(message)

def send_result(parlay: dict, won: bool, pnl: float, new_bankroll: float, streak: int) -> bool:
    """Send result notification after games settle"""
    result_emoji = '🎉' if won else '😔'
    pnl_text = f"+${pnl:.2f}" if pnl > 0 else f"-${abs(pnl):.2f}"
    streak_text = f"🔥 {streak} day win streak!" if streak >= 2 and won else ""

    # Streak protection warning
    protection_text = ""
    if won and streak >= 3:
        protection_text = f"\n\n⚠️ <b>STREAK PROTECTION ACTIVATED</b>\n3+ wins in a row. Consider banking 50% of bankroll (${new_bankroll * 0.5:.2f}) and rolling only ${new_bankroll * 0.5:.2f} tomorrow."

    message = f"""
{result_emoji} <b>EDGEPARLAY — RESULT</b>
📅 {datetime.now().strftime('%Y-%m-%d')}
━━━━━━━━━━━━━━━━━━━━━━━━━━

Result: <b>{'WON ✅' if won else 'LOST ❌'}</b>
P&L: <b>{pnl_text}</b>
New Bankroll: <b>${new_bankroll:.2f}</b>
{streak_text}{protection_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━
See you tomorrow. Stay disciplined. 🎯
"""
    return send_message(message)

def send_welcome_message() -> bool:
    """Send welcome/test message"""
    message = f"""
🚀 <b>EDGEPARLAY IS LIVE</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━

Your ML-powered sports betting intelligence system is now active.

<b>What happens next:</b>
⏰ Every morning at 6am — model scans all sports
📊 Best parlay sent to this chat
⏰ 2 hours before games — final confirmation
📈 Results tracked automatically

<b>Starting bankroll:</b> $100.00
<b>Daily base stake:</b> $10.00
<b>Target odds:</b> 3.0x - 3.5x

<b>Sports covered:</b>
⚾ MLB (daily)
🎾 Tennis (daily)
⚽ Soccer (daily)
🏀 NBA
🥊 UFC/MMA

━━━━━━━━━━━━━━━━━━━━━━━━━━
Built with ❤️ for Ademola
⚠️ 21+ only. Gamble responsibly. Kansas only.
"""
    return send_message(message)

if __name__ == "__main__":
    print("Testing Telegram connection...")
    result = send_welcome_message()
    if result:
        print("✅ Telegram is working! Check your Telegram app.")
    else:
        print("❌ Telegram failed. Check bot token and chat ID.")
