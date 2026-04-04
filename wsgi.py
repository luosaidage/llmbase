"""WSGI entry point for production deployment with background worker."""
import logging
from pathlib import Path
from tools.web import create_web_app
from tools.worker import start_worker_thread

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

base = Path(__file__).resolve().parent
app = create_web_app(base)

# Start autonomous worker (CBETA learning, auto-compile, etc.)
start_worker_thread(base)
