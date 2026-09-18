import re

import aiohttp
import discord
from discord.ext import commands
from discord import app_commands

import database as db
from cogs.permissions import event_admin_check, log_app_command_error

MAX_EMOJI_BYTES = 256 * 1024  # Discord's per-emoji size cap
EMOJI_MENTION_RE = re.compile(r"<(a?):(\w+):(\d+)>")
NAME_CLEAN_RE = re.compile(r"[^a-zA-Z0-9_]")


class EmojiCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _read_image(self, image: discord.Attachment | None, from_emoji: str | None):
        """Returns (bytes, error_message). Exactly one of image/from_emoji should be set."""
        if image is not None:
            if image.size > MAX_EMOJI_BYTES:
                return None, f"That image is too big ({image.size // 1024}KB) — Discord's emoji cap is 256KB."
            return await image.read(), None

        if from_emoji:
            m = EMOJI_MENTION_RE.search(from_emoji.strip())
            if not m:
                return None, "That doesn't look like a custom emoji — paste the emoji itself (e.g. from the emoji picker), not plain text."
            animated, _, emoji_id = m.groups()
            ext = "gif" if animated else "png"
            url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}"
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            return None, "Couldn't fetch that emoji's image from Discord."
                        data = await resp.read()
            except aiohttp.ClientError as e:
                return None, f"Network error fetching that emoji: {e}"
            if len(data) > MAX_EMOJI_BYTES:
                return None, "That emoji's image is too big for Discord's 256KB emoji cap."
            return data, None

        return None, "Provide either an image attachment or an existing emoji to copy."

    @app_commands.command(
        name="addemoji",
        description="Upload an image as one of the bot's own emojis (out of 2000), usable as :name: in giveaways/reminders.",
    )
    @app_commands.describe(
        name="Shortcut name — used as :name: in giveaway/reminder text",
        image="An image file to upload as the emoji (PNG/JPG/GIF, under 256KB)",
        from_emoji="Or paste an existing custom emoji to copy instead of uploading a file",
    )
    @event_admin_check()
    async def addemoji(
        self, interaction: discord.Interaction, name: str,
        image: discord.Attachment = None, from_emoji: str = None,
    ):
        clean_name = NAME_CLEAN_RE.sub("", name.strip().lower())
        if not clean_name:
            await interaction.response.send_message(
                "Give the shortcut a valid name (letters, numbers, underscores only).", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        data, error = await self._read_image(image, from_emoji)
        if error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return

        try:
            emoji = await self.bot.create_application_emoji(name=clean_name, image=data)
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"❌ Discord rejected that emoji ({e}). Common causes: name already taken, "
                f"bad image format, or you've hit the 2000-emoji cap.",
                ephemeral=True,
            )
            return

        db.add_bot_emoji(clean_name, emoji.id, emoji.animated)
        await interaction.followup.send(
            f"✅ Added {emoji} as `:{clean_name}:`. Use `:{clean_name}:` anywhere in a giveaway's "
            f"prize/body text or a reminder message and it'll be swapped in automatically.",
            ephemeral=True,
        )

    @app_commands.command(name="removeemoji", description="Delete one of the bot's uploaded emojis.")
    @app_commands.describe(name="The shortcut name to remove")
    @event_admin_check()
    async def removeemoji(self, interaction: discord.Interaction, name: str):
        row = db.get_bot_emoji(name)
        if not row:
            await interaction.response.send_message(f"No emoji found named `:{name.strip().lower()}:`.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            app_emojis = await self.bot.fetch_application_emojis()
            match = discord.utils.get(app_emojis, id=row["emoji_id"])
            if match:
                await match.delete()
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"⚠️ Couldn't delete it from Discord ({e}), but I'll still remove the `:{row['name']}:` shortcut.",
                ephemeral=True,
            )

        db.remove_bot_emoji(row["name"])
        await interaction.followup.send(f"🗑️ Removed `:{row['name']}:`.", ephemeral=True)

    @app_commands.command(name="listemojis", description="List the bot's registered emoji shortcuts.")
    async def listemojis(self, interaction: discord.Interaction):
        rows = db.list_bot_emojis()
        if not rows:
            await interaction.response.send_message("No emoji shortcuts registered yet.", ephemeral=True)
            return
        lines = [f"`:{r['name']}:` → {db.emoji_mention(r)}" for r in rows]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @removeemoji.autocomplete("name")
    async def removeemoji_autocomplete(self, interaction: discord.Interaction, current: str):
        rows = db.list_bot_emojis()
        return [
            app_commands.Choice(name=r["name"], value=r["name"])
            for r in rows if current.lower() in r["name"]
        ][:25]

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        msg = str(error) if isinstance(error, app_commands.CheckFailure) else "An unexpected error occurred."
        if not isinstance(error, app_commands.CheckFailure):
            log_app_command_error("Emoji", interaction, error)
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EmojiCog(bot))
