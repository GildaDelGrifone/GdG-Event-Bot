# Tests must never reach the real bucket: .env may hold R2 credentials, and every photo sent through
# bot.common.media.send_photo_resilient would upload to R2. Tests that need R2 set it with patched_config.
from core import config

config.R2_ACCOUNT_ID = config.R2_ACCESS_KEY_ID = config.R2_SECRET_ACCESS_KEY = None
