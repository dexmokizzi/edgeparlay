import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import ensure_model_exists, run_scheduler
from backend.api import app
import uvicorn

ensure_model_exists()

scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
scheduler_thread.start()

port = int(os.getenv('PORT', 8000))
print(f"🌐 EdgeParlay Dashboard → http://0.0.0.0:{port}")
uvicorn.run(app, host="0.0.0.0", port=port)