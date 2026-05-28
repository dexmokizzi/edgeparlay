-- EdgeParlay Database Schema
-- Run this in Supabase SQL Editor (SQL tab in dashboard)

-- Bankroll table
CREATE TABLE IF NOT EXISTS bankroll (
    id SERIAL PRIMARY KEY,
    amount DECIMAL(10,2) NOT NULL DEFAULT 100.00,
    base_stake DECIMAL(10,2) NOT NULL DEFAULT 10.00,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert initial bankroll
INSERT INTO bankroll (amount, base_stake) VALUES (100.00, 10.00);

-- Daily parlays table
CREATE TABLE IF NOT EXISTS parlays (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    legs JSONB NOT NULL,
    combined_odds DECIMAL(8,4),
    confidence_tier VARCHAR(10),
    overall_confidence DECIMAL(5,4),
    stake DECIMAL(10,2),
    potential_payout DECIMAL(10,2),
    bet_type VARCHAR(20),
    platform VARCHAR(50),
    status VARCHAR(20) DEFAULT 'pending',
    result VARCHAR(10),
    pnl DECIMAL(10,2),
    clv DECIMAL(8,4),
    regime VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    confirmed_at TIMESTAMP WITH TIME ZONE,
    settled_at TIMESTAMP WITH TIME ZONE
);

-- Individual legs table
CREATE TABLE IF NOT EXISTS legs (
    id SERIAL PRIMARY KEY,
    parlay_id INTEGER REFERENCES parlays(id),
    sport VARCHAR(50),
    event VARCHAR(200),
    market VARCHAR(100),
    selection VARCHAR(200),
    odds_american INTEGER,
    odds_decimal DECIMAL(8,4),
    true_probability DECIMAL(5,4),
    book_implied_probability DECIMAL(5,4),
    mispricing_gap DECIMAL(5,4),
    confidence DECIMAL(5,4),
    platform VARCHAR(50),
    opening_odds INTEGER,
    closing_odds INTEGER,
    clv DECIMAL(8,4),
    result VARCHAR(10),
    danger_flags JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Market odds snapshots
CREATE TABLE IF NOT EXISTS odds_snapshots (
    id SERIAL PRIMARY KEY,
    sport VARCHAR(50),
    event_id VARCHAR(200),
    event_name VARCHAR(200),
    commence_time TIMESTAMP WITH TIME ZONE,
    market VARCHAR(100),
    selection VARCHAR(200),
    bookmaker VARCHAR(50),
    odds_american INTEGER,
    odds_decimal DECIMAL(8,4),
    implied_probability DECIMAL(5,4),
    snapshot_time TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Model performance tracking
CREATE TABLE IF NOT EXISTS model_performance (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    total_picks INTEGER DEFAULT 0,
    winning_picks INTEGER DEFAULT 0,
    win_rate DECIMAL(5,4),
    avg_clv DECIMAL(8,4),
    brier_score DECIMAL(8,6),
    roi DECIMAL(8,4),
    bankroll_start DECIMAL(10,2),
    bankroll_end DECIMAL(10,2),
    regime VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Regime detection log
CREATE TABLE IF NOT EXISTS regimes (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    regime VARCHAR(50),
    confidence_multiplier DECIMAL(4,2),
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Bankroll history for charting
CREATE TABLE IF NOT EXISTS bankroll_history (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    change DECIMAL(10,2),
    streak INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Initial bankroll history entry
INSERT INTO bankroll_history (date, amount, change, streak)
VALUES (CURRENT_DATE, 100.00, 0, 0);
