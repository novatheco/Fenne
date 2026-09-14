import asyncio
import logging

import discord
from discord.ext import commands

import config
import database as db

logging.basicConfig(level=logging.INFO)

INTENTS = discord.Intents.default()
INTENTS.members = True          # needed for invite tracking / role checks
INTENTS.message_content = True  # needed for exact-match autoresponses
INTENTS.guilds = True

COGS = [
    "cogs.settings_cog",
    "cogs.giveaway_cog",
    "cogs.invites_cog",
    "cogs.embeds_cog",
    "cogs.autoresponse_cog",
    "cogs.leaderboard_cog",
]


class EventBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=INTENTS)

    async def setup_hook(self):
        db.init_db()
        for cog in COGS:
            await self.load_extension(cog)
        synced = await self.tree.sync()
        print(f"Synced {len(synced)} slash commands.")

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")


async def main():
    if not config.TOKEN:
        raise SystemExit("No DISCORD_TOKEN found. Put it in a .env file next to main.py.")
    bot = EventBot()
    async with bot:
        await bot.start(config.TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
