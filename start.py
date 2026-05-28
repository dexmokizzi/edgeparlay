"""
EdgeParlay startup script
Runs model training + web server + scheduler together
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import ensure_model_exists, run_scheduler
from backend.api import app
import uvicorn

# Step 1: ensure model exists
ensure_model_exists()

# Step 2: start scheduler in background thread
scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
scheduler_thread.start()

# Step 3: start web server (main thread)
port = int(os.getenv('PORT', 8000))
print(f"🌐 EdgeParlay Dashboard → http://0.0.0.0:{port}")
uvicorn.run(app, host="0.0.0.0", port=port)
