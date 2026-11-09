# Tests must never reach the real bucket: .env may hold R2 credentials, and every photo sent through
# bot.common.media.send_photo_resilient would upload to R2. Tests that need R2 set it with patched_config.
from core import config

config.R2_ACCOUNT_ID = config.R2_ACCESS_KEY_ID = config.R2_SECRET_ACCESS_KEY = None

# Nor the real data folder: a test that writes without TempDBMixin (e.g. a command saving a runtime setting) gets an
# empty throwaway database instead of data/bot_database.db, images saved by code under test (event photos, recap
# collages) land in a throwaway DATA_DIR, and importing main.py (logging.basicConfig with a file handler on
# LOGS_DIR) logs there instead of data/logs/bot.log. Tests that check files still point DATA_DIR at their own dir.
import atexit
import os
import shutil
import tempfile

_fallback_dir = tempfile.mkdtemp(prefix="gdg-tests-")
atexit.register(shutil.rmtree, _fallback_dir, True)
config.DB_PATH = os.path.join(_fallback_dir, "unused.db")
config.DATA_DIR = _fallback_dir
config.LOGS_DIR = os.path.join(_fallback_dir, "logs")
os.makedirs(config.LOGS_DIR, exist_ok=True)
