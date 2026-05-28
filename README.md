# EdgeParlay 🎯

ML-powered sports betting intelligence system.
Finds daily high-confidence parlay opportunities across MLB, Tennis, Soccer, NBA, and UFC.

## Setup

### 1. Clone and install
```bash
git clone https://github.com/YOUR_USERNAME/edgeparlay.git
cd edgeparlay
pip install -r requirements.txt
```

### 2. Environment variables
Create a `.env` file:
```
ODDS_API_KEY=your_odds_api_key
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_anon_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
BANKROLL=100
BASE_STAKE=10
TARGET_ODDS_MIN=3.0
TARGET_ODDS_MAX=3.5
MIN_CONFIDENCE=0.65
```

### 3. Set up Supabase database
- Go to your Supabase project
- Open SQL Editor
- Run the contents of `scripts/setup_tables.sql`

### 4. Test locally
```bash
# Send welcome message to Telegram
python main.py welcome

# Run morning picks manually
python main.py morning

# Start the scheduler (runs daily at 6am Central)
python main.py schedule
```

### 5. Deploy to Railway
- Push to GitHub
- Connect Railway to your GitHub repo
- Add all environment variables in Railway dashboard
- Deploy — Railway runs `python main.py schedule` automatically

## Architecture

```
EdgeParlay
├── backend/
│   ├── pipeline.py          # Pulls live odds from The Odds API
│   ├── confidence_engine.py # Rules-based + ML hybrid scoring
│   ├── parlay_constructor.py # Builds optimal daily parlay
│   └── telegram_bot.py      # Sends alerts to your phone
├── scripts/
│   └── setup_tables.sql     # Supabase database schema
├── main.py                  # Daily orchestrator + scheduler
├── requirements.txt
└── railway.toml             # Railway deployment config
```

## Daily Flow

- **6:00 AM Central** — Model fetches odds, scores all opportunities, builds parlay, sends Telegram
- **2 hrs before games** — Final confirmation check (injuries, line movement)
- **After games** — Results logged, bankroll updated
- **Monthly** — Model retrained on rolling 90-day window

## Responsible Gambling

- 21+ only
- Kansas only
- Never bet more than you can afford to lose
- This is an ML research project, not financial advice
