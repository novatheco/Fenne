import re

import discord
from discord.ext import commands
from discord import app_commands

import database as db
from cogs.permissions import event_admin_check, log_app_command_error


def build_leaderboard_embed(guild: discord.Guild, lb: dict) -> discord.Embed:
    if lb.get("mode") == "team":
        teams = db.list_teams(guild.id, lb["name"])
        desc = ""
        for i, team in enumerate(teams):
            member_ids = db.get_team_members(team["id"])
            member_names = []
            for uid in member_ids:
                member = guild.get_member(uid)
                member_names.append(member.display_name if member else f"Unknown (ID:{uid})")
            members_str = ", ".join(member_names) if member_names else "*no members*"
            desc += f"**{i + 1}. {team['team_name']}**\n> {lb['emoji']} {team['score']}\n> {members_str}\n"
        if not desc:
            desc = "No teams yet! Use `/team-create` to add one."
    else:
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

    # ---------------- individual leaderboards ----------------

    @app_commands.command(name="create-leaderboard", description="Creates a leaderboard")
    @app_commands.describe(
        channel="Channel", hex_color_code="Color (optional, defaults to #00ff00)",
        name="Name", image_url="Image URL (optional)", emoji="Emoji (optional, defaults to 🏆)",
        team_mode="If true, this leaderboard tracks teams (via /team-create) instead of individuals",
    )
    @event_admin_check()
    async def create_leaderboard(
        self, interaction: discord.Interaction, channel: discord.TextChannel, name: str,
        hex_color_code: str = "#00ff00", image_url: str = None, emoji: str = "🏆", team_mode: bool = False,
    ):
        if not re.match(r"^#[0-9a-fA-F]{6}$", hex_color_code):
            await interaction.response.send_message("❌ Invalid hex color code.", ephemeral=True)
            return
        if db.get_leaderboard(interaction.guild.id, name):
            await interaction.response.send_message("❌ Leaderboard already exists.", ephemeral=True)
            return

        mode = "team" if team_mode else "individual"
        db.create_leaderboard(interaction.guild.id, name, channel.id, hex_color_code.lstrip("#"), image_url, emoji, mode)
        lb = db.get_leaderboard(interaction.guild.id, name)
        msg = await channel.send(embed=build_leaderboard_embed(interaction.guild, lb))
        db.set_leaderboard_message(interaction.guild.id, name, msg.id)

        kind = "team-based" if team_mode else "individual"
        await interaction.response.send_message(f"✅ {kind.title()} leaderboard {name} created in {channel.mention}", ephemeral=True)

    @app_commands.command(name="leaderboard-snapshot", description="Post a static copy of a leaderboard that will NOT auto-update.")
    @app_commands.describe(name="Leaderboard name")
    async def leaderboard_snapshot(self, interaction: discord.Interaction, name: str):
        lb = db.get_leaderboard(interaction.guild.id, name)
        if not lb:
            await interaction.response.send_message("❌ Leaderboard not found.", ephemeral=True)
            return
        embed = build_leaderboard_embed(interaction.guild, lb)
        embed.set_footer(text="📌 Static snapshot — this copy won't update as scores change.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="trophy-add", description="Adds points to a user.")
    @app_commands.describe(name="Leaderboard name", user="User", amount="Points")
    @event_admin_check()
    async def trophy_add(self, interaction: discord.Interaction, name: str, user: discord.Member, amount: int):
        lb = db.get_leaderboard(interaction.guild.id, name)
        if not lb:
            await interaction.response.send_message("❌ Leaderboard not found.", ephemeral=True)
            return
        if lb.get("mode") == "team":
            await interaction.response.send_message(
                "This is a team leaderboard — use `/team-trophy-add` instead.", ephemeral=True
            )
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
        if lb.get("mode") == "team":
            await interaction.response.send_message(
                "This is a team leaderboard — use `/team-trophy-add` instead.", ephemeral=True
            )
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

    @app_commands.command(name="trophy-check", description="See how many trophies a user has on a specific leaderboard.")
    @app_commands.describe(name="Leaderboard name", user="User (defaults to you)")
    async def trophy_check(self, interaction: discord.Interaction, name: str, user: discord.Member = None):
        lb = db.get_leaderboard(interaction.guild.id, name)
        if not lb:
            await interaction.response.send_message("❌ Leaderboard not found.", ephemeral=True)
            return
        target = user or interaction.user

        if lb.get("mode") == "team":
            team = db.get_user_team(interaction.guild.id, name, target.id)
            if not team:
                await interaction.response.send_message(f"{target.display_name} isn't on a team for **{name}**.", ephemeral=True)
                return
            await interaction.response.send_message(
                f"{lb['emoji']} {target.display_name} is on **{team['team_name']}**, which has **{team['score']}** on **{name}**."
            )
            return

        score = db.get_user_score(interaction.guild.id, name, target.id)
        await interaction.response.send_message(f"{lb['emoji']} {target.display_name} has **{score}** on **{name}**.")

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

    # ---------------- team leaderboards ----------------

    @app_commands.command(name="team-create", description="Create a team on a team-mode leaderboard and add members.")
    @app_commands.describe(leaderboard="Leaderboard name", team_name="Team name", users="Comma/space separated user mentions")
    @event_admin_check()
    async def team_create(self, interaction: discord.Interaction, leaderboard: str, team_name: str, users: str = ""):
        lb = db.get_leaderboard(interaction.guild.id, leaderboard)
        if not lb:
            await interaction.response.send_message("❌ Leaderboard not found.", ephemeral=True)
            return
        if lb.get("mode") != "team":
            await interaction.response.send_message(
                "That leaderboard isn't in team mode. Create one with `/create-leaderboard team_mode:True`.", ephemeral=True
            )
            return
        if db.get_team(interaction.guild.id, leaderboard, team_name):
            await interaction.response.send_message(f"❌ Team `{team_name}` already exists on **{leaderboard}**.", ephemeral=True)
            return

        team_id = db.create_team(interaction.guild.id, leaderboard, team_name)

        mention_ids = re.findall(r"<@!?(\d+)>", users)
        added, skipped = [], []
        for uid in mention_ids:
            uid = int(uid)
            member = interaction.guild.get_member(uid)
            if not member:
                continue
            existing_team = db.get_user_team(interaction.guild.id, leaderboard, uid)
            if existing_team:
                skipped.append(f"{member.display_name} (already on {existing_team['team_name']})")
                continue
            db.add_team_member(team_id, uid)
            added.append(member.display_name)

        await self._refresh_message(interaction.guild, lb)

        msg = f"✅ Team **{team_name}** created on **{leaderboard}**."
        if added:
            msg += f"\nAdded: {', '.join(added)}"
        if skipped:
            msg += f"\nSkipped (already on another team): {', '.join(skipped)}"
        await interaction.response.send_message(msg, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="team-edit", description="Add or remove members from an existing team.")
    @app_commands.describe(
        leaderboard="Leaderboard name", team_name="Team name",
        add_users="Comma/space separated mentions to add", remove_users="Comma/space separated mentions to remove",
    )
    @event_admin_check()
    async def team_edit(
        self, interaction: discord.Interaction, leaderboard: str, team_name: str,
        add_users: str = "", remove_users: str = "",
    ):
        team = db.get_team(interaction.guild.id, leaderboard, team_name)
        if not team:
            await interaction.response.send_message(f"❌ No team `{team_name}` found on **{leaderboard}**.", ephemeral=True)
            return

        added, skipped, removed = [], [], []
        for uid in re.findall(r"<@!?(\d+)>", add_users):
            uid = int(uid)
            member = interaction.guild.get_member(uid)
            if not member:
                continue
            existing_team = db.get_user_team(interaction.guild.id, leaderboard, uid)
            if existing_team:
                skipped.append(f"{member.display_name} (already on {existing_team['team_name']})")
                continue
            db.add_team_member(team["id"], uid)
            added.append(member.display_name)

        for uid in re.findall(r"<@!?(\d+)>", remove_users):
            uid = int(uid)
            member = interaction.guild.get_member(uid)
            db.remove_team_member(team["id"], uid)
            removed.append(member.display_name if member else str(uid))

        lb = db.get_leaderboard(interaction.guild.id, leaderboard)
        await self._refresh_message(interaction.guild, lb)

        parts = [f"✅ Updated team **{team_name}**."]
        if added:
            parts.append(f"Added: {', '.join(added)}")
        if removed:
            parts.append(f"Removed: {', '.join(removed)}")
        if skipped:
            parts.append(f"Skipped (already on another team): {', '.join(skipped)}")
        await interaction.response.send_message("\n".join(parts), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="team-disband", description="Delete a team and remove all its members.")
    @app_commands.describe(leaderboard="Leaderboard name", team_name="Team name")
    @event_admin_check()
    async def team_disband(self, interaction: discord.Interaction, leaderboard: str, team_name: str):
        team = db.get_team(interaction.guild.id, leaderboard, team_name)
        if not team:
            await interaction.response.send_message(f"❌ No team `{team_name}` found on **{leaderboard}**.", ephemeral=True)
            return
        db.disband_team(team["id"])
        lb = db.get_leaderboard(interaction.guild.id, leaderboard)
        await self._refresh_message(interaction.guild, lb)
        await interaction.response.send_message(f"🗑️ Team **{team_name}** disbanded.", ephemeral=True)

    @app_commands.command(name="team-trophy-add", description="Add (or subtract) points from a team's shared score.")
    @app_commands.describe(leaderboard="Leaderboard name", team_name="Team name", amount="Points")
    @event_admin_check()
    async def team_trophy_add(self, interaction: discord.Interaction, leaderboard: str, team_name: str, amount: int):
        team = db.get_team(interaction.guild.id, leaderboard, team_name)
        if not team:
            await interaction.response.send_message(f"❌ No team `{team_name}` found on **{leaderboard}**.", ephemeral=True)
            return
        db.adjust_team_score(team["id"], amount)
        lb = db.get_leaderboard(interaction.guild.id, leaderboard)
        await self._refresh_message(interaction.guild, lb)
        sign = "+" if amount >= 0 else ""
        await interaction.response.send_message(f"✅ Team **{team_name}**: {sign}{amount} on **{leaderboard}**.", ephemeral=True)

    # ---------------- autocomplete ----------------

    @trophy_add.autocomplete("name")
    @trophy_multi_add.autocomplete("name")
    @trophy_check.autocomplete("name")
    @delete_leaderboard.autocomplete("name")
    @leaderboard_snapshot.autocomplete("name")
    @team_create.autocomplete("leaderboard")
    @team_edit.autocomplete("leaderboard")
    @team_disband.autocomplete("leaderboard")
    @team_trophy_add.autocomplete("leaderboard")
    async def name_autocomplete(self, interaction: discord.Interaction, current: str):
        names = db.list_leaderboards(interaction.guild.id)
        return [app_commands.Choice(name=n, value=n) for n in names if current.lower() in n.lower()][:25]

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        msg = str(error) if isinstance(error, app_commands.CheckFailure) else "An unexpected error occurred."
        if not isinstance(error, app_commands.CheckFailure):
            log_app_command_error("Leaderboard", interaction, error)
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(LeaderboardCog(bot))
