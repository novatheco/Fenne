import discord
from discord.ext import commands
from discord import app_commands

import config
import database as db
from cogs.permissions import event_admin_check, log_app_command_error

STAR_EMOJI = "⭐"


def build_starboard_embed(message: discord.Message) -> discord.Embed:
    embed = discord.Embed(
        description=message.content or None,
        color=discord.Color(config.EMBED_COLOR_HEX),
        timestamp=message.created_at,
    )
    embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
    for att in message.attachments:
        if att.content_type and att.content_type.startswith("image/"):
            embed.set_image(url=att.url)
            break
    embed.add_field(name="Source", value=f"[Jump!]({message.jump_url})", inline=False)
    embed.set_footer(text=f"ID: {message.id}")
    return embed


class StarboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        await self._handle(payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        await self._handle(payload)

    async def _handle(self, payload: discord.RawReactionActionEvent):
        if not payload.guild_id or str(payload.emoji) != STAR_EMOJI:
            return
        settings = db.get_starboard_settings(payload.guild_id)
        star_channel_id = settings["channel_id"]
        if not star_channel_id or payload.channel_id == star_channel_id:
            return
        if db.is_starboard_ignored(payload.guild_id, payload.channel_id):
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        star_channel = guild.get_channel(star_channel_id)
        source_channel = guild.get_channel(payload.channel_id) or guild.get_thread(payload.channel_id)
        if not star_channel or not source_channel:
            return
        try:
            message = await source_channel.fetch_message(payload.message_id)
        except discord.HTTPException:
            return

        count = 0
        for r in message.reactions:
            if str(r.emoji) == STAR_EMOJI:
                count = r.count
                break

        existing_id = db.get_starboard_message(payload.guild_id, message.id)
        existing = None
        if existing_id:
            try:
                existing = await star_channel.fetch_message(existing_id)
            except discord.HTTPException:
                existing = None

        if count >= settings["threshold"]:
            content = f"{STAR_EMOJI} **{count}** {source_channel.mention}"
            embed = build_starboard_embed(message)
            try:
                if existing:
                    await existing.edit(content=content, embed=embed)
                else:
                    sent = await star_channel.send(content, embed=embed)
                    db.set_starboard_message(payload.guild_id, message.id, sent.id)
            except discord.HTTPException:
                pass
        else:
            if existing:
                try:
                    await existing.delete()
                except discord.HTTPException:
                    pass
            if existing_id:
                db.delete_starboard_message(payload.guild_id, message.id)

    @app_commands.command(name="starboard-channel", description="Set the channel where starred messages are posted.")
    @app_commands.describe(channel="The starboard channel")
    @event_admin_check()
    async def starboard_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        db.set_starboard_channel(interaction.guild.id, channel.id)
        await interaction.response.send_message(f"✅ Starboard channel set to {channel.mention}.", ephemeral=True)

    @app_commands.command(name="starboard-threshold", description="Set how many ⭐ reactions a message needs to hit the starboard.")
    @app_commands.describe(count="Number of stars required (1-1000)")
    @event_admin_check()
    async def starboard_threshold(self, interaction: discord.Interaction, count: app_commands.Range[int, 1, 1000]):
        db.set_starboard_threshold(interaction.guild.id, count)
        await interaction.response.send_message(f"✅ Messages now need **{count}** ⭐ to hit the starboard.", ephemeral=True)

    @app_commands.command(name="starboard-ignore", description="Ignore stars in a channel.")
    @app_commands.describe(channel="The channel to ignore")
    @event_admin_check()
    async def starboard_ignore(self, interaction: discord.Interaction, channel: discord.TextChannel):
        db.add_starboard_ignored_channel(interaction.guild.id, channel.id)
        await interaction.response.send_message(f"✅ Stars in {channel.mention} are now ignored.", ephemeral=True)

    @app_commands.command(name="starboard-unignore", description="Stop ignoring stars in a channel.")
    @app_commands.describe(channel="The channel to stop ignoring")
    @event_admin_check()
    async def starboard_unignore(self, interaction: discord.Interaction, channel: discord.TextChannel):
        removed = db.remove_starboard_ignored_channel(interaction.guild.id, channel.id)
        msg = f"✅ {channel.mention} is no longer ignored." if removed else f"{channel.mention} wasn't ignored."
        await interaction.response.send_message(msg, ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        msg = str(error) if isinstance(error, app_commands.CheckFailure) else "An unexpected error occurred."
        if not isinstance(error, app_commands.CheckFailure):
            log_app_command_error("Starboard", interaction, error)
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(StarboardCog(bot))
