import re

import discord
from discord.ext import commands
from discord import app_commands

import database as db
from cogs.permissions import event_admin_check


def build_leaderboard_embed(guild: discord.Guild, lb: dict) -> discord.Embed:
    scores = db.get_scores(guild.id, lb["name"])
    desc = ""
    for i, row in enumerate(scores[:10]):
        member = guild.get_member(row["user_id"])
        username = member.display_name if member else f"Unknown (ID:{row['user_id']})"
        desc += f"**{i + 1}. {username}**\n> {lb['emoji']} {row['score']}\n"
    if not desc:
        desc = "No one is on the leaderboard yet!"

    embed = discord.Embed(title=lb["name"], description=desc, color=discord.Color(int(lb["color"] or "5865f2", 16)))
    if lb.get("image_url"):
        embed.set_thumbnail(url=lb["image_url"])
    return embed


class LeaderboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _refresh_message(self, guild: discord.Guild, lb: dict):
        if not lb.get("channel_id") or not lb.get("message_id"):
            return
        channel = guild.get_channel(lb["channel_id"])
        if not channel:
            return
        try:
            msg = await channel.fetch_message(lb["message_id"])
            await msg.edit(embed=build_leaderboard_embed(guild, lb))
        except (discord.NotFound, discord.HTTPException):
            pass

    @app_commands.command(name="create-leaderboard", description="Creates a leaderboard")
    @app_commands.describe(
        channel="Channel", hex_color_code="Color (optional, defaults to #00ff00)",
        name="Name", image_url="Image URL (optional)", emoji="Emoji (optional, defaults to 🏆)",
    )
    @event_admin_check()
    async def create_leaderboard(
        self, interaction: discord.Interaction, channel: discord.TextChannel, name: str,
        hex_color_code: str = "#00ff00", image_url: str = None, emoji: str = "🏆",
    ):
        if not re.match(r"^#[0-9a-fA-F]{6}$", hex_color_code):
            await interaction.response.send_message("❌ Invalid hex color code.", ephemeral=True)
            return
        if db.get_leaderboard(interaction.guild.id, name):
            await interaction.response.send_message("❌ Leaderboard already exists.", ephemeral=True)
            return

        db.create_leaderboard(interaction.guild.id, name, channel.id, hex_color_code.lstrip("#"), image_url, emoji)
        lb = db.get_leaderboard(interaction.guild.id, name)
        msg = await channel.send(embed=build_leaderboard_embed(interaction.guild, lb))
        db.set_leaderboard_message(interaction.guild.id, name, msg.id)

        await interaction.response.send_message(f"✅ Leaderboard {name} created in {channel.mention}", ephemeral=True)

    @app_commands.command(name="trophy-add", description="Adds points to a user.")
    @app_commands.describe(name="Leaderboard name", user="User", amount="Points")
    @event_admin_check()
    async def trophy_add(self, interaction: discord.Interaction, name: str, user: discord.Member, amount: int):
        lb = db.get_leaderboard(interaction.guild.id, name)
        if not lb:
            await interaction.response.send_message("❌ Leaderboard not found.", ephemeral=True)
            return
        db.adjust_score(interaction.guild.id, name, user.id, amount)
        await self._refresh_message(interaction.guild, lb)
        await interaction.response.send_message(f"✅ Added {amount} points to `{user.display_name}` on {name}.", ephemeral=True)

    @app_commands.command(name="trophy-multi-add", description="Adds points to multiple users.")
    @app_commands.describe(name="Leaderboard name", users="Comma separated user mentions", amount="Points")
    @event_admin_check()
    async def trophy_multi_add(self, interaction: discord.Interaction, name: str, users: str, amount: int):
        lb = db.get_leaderboard(interaction.guild.id, name)
        if not lb:
            await interaction.response.send_message("❌ Leaderboard not found.", ephemeral=True)
            return

        mention_ids = re.findall(r"<@!?(\d+)>", users)
        updated_names = []
        for user_id in mention_ids:
            member = interaction.guild.get_member(int(user_id))
            if member:
                db.adjust_score(interaction.guild.id, name, member.id, amount)
                updated_names.append(member.display_name)

        await self._refresh_message(interaction.guild, lb)

        if not updated_names:
            await interaction.response.send_message("❌ No valid users found.", ephemeral=True)
            return

        mentions_str = ", ".join(f"`{n}`" for n in updated_names)
        await interaction.response.send_message(
            f"✅ Added {amount} points to: {mentions_str}", allowed_mentions=discord.AllowedMentions.none(), ephemeral=True
        )

    @app_commands.command(name="delete-leaderboard", description="Deletes a leaderboard")
    @app_commands.describe(name="Leaderboard name")
    @event_admin_check()
    async def delete_leaderboard(self, interaction: discord.Interaction, name: str):
        lb = db.get_leaderboard(interaction.guild.id, name)
        if not lb:
            await interaction.response.send_message("❌ Leaderboard not found.", ephemeral=True)
            return
        db.delete_leaderboard(interaction.guild.id, name)
        await interaction.response.send_message(f"🗑️ Leaderboard {name} deleted.", ephemeral=True)

    @app_commands.command(name="all-leaderboards", description="Lists all leaderboards.")
    async def all_leaderboards(self, interaction: discord.Interaction):
        names = db.list_leaderboards(interaction.guild.id)
        if not names:
            await interaction.response.send_message("No leaderboards found.", ephemeral=True)
            return
        desc = "\n".join(f"- {n}" for n in names)
        embed = discord.Embed(title="Leaderboards", description=desc, color=discord.Color.green())
        await interaction.response.send_message(embed=embed)

    @trophy_add.autocomplete("name")
    @trophy_multi_add.autocomplete("name")
    @delete_leaderboard.autocomplete("name")
    async def name_autocomplete(self, interaction: discord.Interaction, current: str):
        names = db.list_leaderboards(interaction.guild.id)
        return [app_commands.Choice(name=n, value=n) for n in names if current.lower() in n.lower()][:25]

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        msg = str(error) if isinstance(error, app_commands.CheckFailure) else "An unexpected error occurred."
        if not isinstance(error, app_commands.CheckFailure):
            print(f"Leaderboard cog error: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(LeaderboardCog(bot))
