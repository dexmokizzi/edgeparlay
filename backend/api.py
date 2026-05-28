"""
EdgeParlay FastAPI Backend
Serves the dashboard and provides API endpoints
"""
import os
import json
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="EdgeParlay API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.getenv('SUPABASE_URL', '')
SUPABASE_KEY = os.getenv('SUPABASE_KEY', '')

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the main dashboard"""
    html_path = os.path.join(os.path.dirname(__file__), 'dashboard.html')
    with open(html_path, 'r') as f:
        html = f.read()
    html = html.replace('__SUPABASE_URL__', SUPABASE_URL)
    html = html.replace('__SUPABASE_KEY__', SUPABASE_KEY)
    return HTMLResponse(content=html)

@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}

@app.get("/api/bankroll")
async def get_bankroll():
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{SUPABASE_URL}/rest/v1/bankroll?order=id.desc&limit=1",
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
            )
            data = r.json()
            return {"bankroll": data[0]["amount"] if data else 100}
    except Exception as e:
        return {"bankroll": 100, "error": str(e)}

@app.get("/api/parlays")
async def get_parlays(limit: int = 30):
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{SUPABASE_URL}/rest/v1/parlays?order=created_at.desc&limit={limit}",
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
            )
            return r.json()
    except Exception as e:
        return []

@app.get("/api/performance")
async def get_performance():
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{SUPABASE_URL}/rest/v1/model_performance?order=date.desc&limit=30",
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
            )
            return r.json()
    except Exception as e:
        return []
