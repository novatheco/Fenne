"""World Boss spawn alerts for discord.py 2.x.

Keep ``worldboss_gifs.json`` beside this file. Set the channel and role IDs,
then load the extension with ``await bot.load_extension("worldboss_pings")``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path

import discord
from discord.ext import commands

log = logging.getLogger(__name__)

# Replace these with IDs from your server.
WORLD_BOSS_CHANNEL_ID = 0
WORLD_BOSS_ROLE_ID = 0

# Add the game bot's user ID(s) here. If left empty, any bot with the matching
# World Boss embed title can trigger a ping.
SOURCE_BOT_IDS: set[int] = set()

GIFS_PATH = Path(__file__).with_name("worldboss_gifs.json")
COOLDOWN_SECONDS = 5 * 60
WORLD_BOSS_TITLE = re.compile(r"\ba world boss has spawned!", re.IGNORECASE)
BOSS_LINE = re.compile(
    r"(?:world\s+boss\s+challenge|boss)\s*:\s*(.+)$", re.IGNORECASE
)
BATTLE_BEGINS_LINE = re.compile(r"battle\s+begins\s+(.+)$", re.IGNORECASE)
CUSTOM_EMOJI = re.compile(r"<a?:[^:>]+:\d+>")


class WorldBossPings(commands.Cog):
    """Detect World Boss spawn embeds and ping the configured server role."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._worldboss_gifs = self._load_worldboss_gifs()
        self._handled_messages: set[int] = set()
        self._last_ping_at: dict[int, float] = {}
        self._lock = asyncio.Lock()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        await self._handle_message(message)

    @commands.Cog.listener()
    async def on_message_edit(
        self, before: discord.Message, after: discord.Message
    ) -> None:
        if before.embeds != after.embeds or before.content != after.content:
            await self._handle_message(after)

    async def _handle_message(self, message: discord.Message) -> None:
        if (
            message.guild is None
            or message.author.id == self.bot.user.id
            or not message.author.bot
            or (SOURCE_BOT_IDS and message.author.id not in SOURCE_BOT_IDS)
            or message.id in self._handled_messages
            or not any(WORLD_BOSS_TITLE.search(embed.title or "") for embed in message.embeds)
        ):
            return

        async with self._lock:
            if message.id in self._handled_messages:
                return

            guild = message.guild
            channel = guild.get_channel(WORLD_BOSS_CHANNEL_ID)
            role = guild.get_role(WORLD_BOSS_ROLE_ID)
            if not isinstance(channel, discord.TextChannel):
                log.warning(
                    "World Boss ping channel %s is missing in guild %s",
                    WORLD_BOSS_CHANNEL_ID,
                    guild.id,
                )
                return
            if role is None:
                log.warning(
                    "World Boss ping role %s is missing in guild %s",
                    WORLD_BOSS_ROLE_ID,
                    guild.id,
                )
                return

            now = time.time()
            last_ping = self._last_ping_at.get(guild.id, 0)
            if now - last_ping < COOLDOWN_SECONDS:
                self._handled_messages.add(message.id)
                return

            text = self._message_text(message)
            boss_name = self._extract_line(BOSS_LINE, text) or "Unknown"
            battle_begins = self._extract_line(BATTLE_BEGINS_LINE, text) or "Unknown"
            boss_emoji = (
                "✨"
                if re.search(r"\bshiny\b", boss_name, re.IGNORECASE)
                else "🟣"
            )
            embed = discord.Embed(
                title="🌎 A World Boss has spawned!",
                description=(
                    "Register now with `;wb` - Good luck!\n\n"
                    "Type `;wb f` to begin your battle."
                ),
                color=0x8E44AD,
            )
            embed.add_field(name="BOSS:", value=f"{boss_emoji} {boss_name}", inline=False)
            embed.add_field(name="Battle Begins", value=battle_begins, inline=False)
            gif_url = self._worldboss_gif(boss_name)
            if gif_url:
                embed.set_image(url=gif_url)

            try:
                await channel.send(
                    content=role.mention,
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(
                        roles=[role], users=False, everyone=False
                    ),
                )
            except discord.HTTPException:
                log.exception("Failed to send World Boss ping in guild %s", guild.id)
                return

            self._last_ping_at[guild.id] = now
            self._handled_messages.add(message.id)
            if len(self._handled_messages) > 500:
                self._handled_messages.clear()
            log.info("Sent World Boss ping for source message %s", message.id)

    @staticmethod
    def _load_worldboss_gifs() -> dict[str, dict[str, str]]:
        try:
            with GIFS_PATH.open(encoding="utf-8") as gif_file:
                gifs = json.load(gif_file)
        except FileNotFoundError:
            log.warning("World Boss GIF file not found: %s", GIFS_PATH)
            return {}
        except (OSError, json.JSONDecodeError):
            log.exception("Could not load World Boss GIF file: %s", GIFS_PATH)
            raise

        if not isinstance(gifs, dict):
            raise ValueError(f"World Boss GIF file must contain a JSON object: {GIFS_PATH}")
        return gifs

    def _worldboss_gif(self, boss_name: str) -> str | None:
        key = self._worldboss_gif_key(boss_name)
        entry = self._worldboss_gifs.get(key, {})
        variant = "shiny" if re.search(r"\bshiny\b", boss_name, re.IGNORECASE) else "normal"
        return entry.get(variant)

    @staticmethod
    def _worldboss_gif_key(boss_name: str) -> str:
        key = re.sub(r"^shiny\s+", "", boss_name, flags=re.IGNORECASE)
        key = re.sub(r"^gigantamax[-\s]+", "", key, flags=re.IGNORECASE)
        key = re.sub(r"\s+eternamax$", "", key, flags=re.IGNORECASE)
        key = re.sub(r"^eternamax[-\s]+", "", key, flags=re.IGNORECASE)
        key = re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")
        return "eternatus-eternamax" if key == "eternatus" else key

    @staticmethod
    def _message_text(message: discord.Message) -> str:
        parts = [message.content]
        for embed in message.embeds:
            parts.extend((embed.title or "", embed.description or ""))
            for field in embed.fields:
                parts.extend((field.name, field.value))
        return "\n".join(parts)

    @staticmethod
    def _extract_line(pattern: re.Pattern[str], text: str) -> str | None:
        for line in text.splitlines():
            clean_line = CUSTOM_EMOJI.sub("", line).strip()
            match = pattern.search(clean_line)
            if match:
                return match.group(1).strip()
        return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WorldBossPings(bot))
