"""
Fill these in before running the bot.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Your bot's token, from the Discord Developer Portal.
# Put this in a `.env` file next to this script as:
#   DISCORD_TOKEN=your-token-here
TOKEN = os.getenv("DISCORD_TOKEN")

# Your Discord user ID. Owners can always use admin commands, even without
# the configured admin role.
OWNER_IDS = {
    1178457671758790767,  # TODO: replace/add your Discord user ID(s) here
}

DB_PATH = "eventbot.db"

# Default embed color used where nothing more specific is set (hex, no #).
DEFAULT_COLOR = "5865f2"
