import asyncio
import time

import discord
from discord.ext import commands
from discord import app_commands

import database as db
from cogs.permissions import staff_check, log_app_command_error
from utils import parse_duration, format_duration


class ReminderLoopMessageModal(discord.ui.Modal, title="Reminder Message"):
    def __init__(self, cog: "ReminderCog", channel: discord.TextChannel, role: discord.Role, interval_seconds: int, created_by: int):
        super().__init__()
        self.cog = cog
        self.channel = channel
        self.role = role
        self.interval_seconds = interval_seconds
        self.created_by = created_by
        self.message_text = discord.ui.TextInput(
            label="Message", style=discord.TextStyle.paragraph, max_length=1900,
            placeholder="Reminder to do your daily checklist!\n;daily | ;swap | ;hunt | ;quest",
        )
        self.add_item(self.message_text)

    async def on_submit(self, interaction: discord.Interaction):
        next_run = time.time() + self.interval_seconds
        loop_id = db.create_reminder_loop(
            interaction.guild.id, self.channel.id, self.role.id, self.interval_seconds,
            self.message_text.value.strip(), self.created_by, next_run,
        )
        self.cog.start_loop_task(loop_id)
        await interaction.response.send_message(
            f"✅ Reminder loop **#{loop_id}** created in {self.channel.mention}, pinging {self.role.mention} "
            f"every **{format_duration(self.interval_seconds)}**. Use `/remind-loop-stop {loop_id}` to cancel it.",
            ephemeral=True,
        )


class ReminderCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.loop_tasks: dict[int, asyncio.Task] = {}
        self.reminder_tasks: dict[int, asyncio.Task] = {}

    async def cog_load(self):
        for loop in db.list_active_reminder_loops():
            self.start_loop_task(loop["id"])
        for reminder in db.get_pending_reminders():
            self.start_reminder_task(reminder["id"], reminder["remind_at"])

    # ---------------- repeating staff reminders ----------------

    def start_loop_task(self, loop_id: int):
        task = asyncio.create_task(self._loop_runner(loop_id))
        self.loop_tasks[loop_id] = task

    async def _loop_runner(self, loop_id: int):
        while True:
            row = db.get_reminder_loop(loop_id)
            if not row or not row["active"]:
                self.loop_tasks.pop(loop_id, None)
                return

            delay = max(0, row["next_run"] - time.time())
            await asyncio.sleep(delay)

            row = db.get_reminder_loop(loop_id)
            if not row or not row["active"]:
                self.loop_tasks.pop(loop_id, None)
                return

            guild = self.bot.get_guild(row["guild_id"])
            channel = guild.get_channel(row["channel_id"]) if guild else None
            role = guild.get_role(row["role_id"]) if guild else None
            if channel and role:
                try:
                    await channel.send(
                        f"{role.mention} {db.apply_emoji_shortcuts(row['message'])}",
                        allowed_mentions=discord.AllowedMentions(roles=True),
                    )
                except discord.HTTPException as e:
                    print(f"[ReminderLoop #{loop_id}] failed to send: {e}")

            db.set_reminder_loop_next_run(loop_id, time.time() + row["interval_seconds"])

    @app_commands.command(name="remind-loop", description="Set up a recurring reminder that pings a role on a schedule.")
    @app_commands.describe(interval="How often it repeats, e.g. 1h, 30m, 1d", role="Role to ping", channel="Channel to post the reminder in")
    @staff_check()
    async def remind_loop(self, interaction: discord.Interaction, interval: str, role: discord.Role, channel: discord.TextChannel):
        seconds = parse_duration(interval)
        if not seconds:
            await interaction.response.send_message(
                "Couldn't parse that interval. Try things like `1h`, `30m`, `1d`.", ephemeral=True
            )
            return
        await interaction.response.send_modal(
            ReminderLoopMessageModal(self, channel, role, seconds, interaction.user.id)
        )

    @app_commands.command(name="remind-loop-list", description="List active recurring reminders in this server.")
    @staff_check()
    async def remind_loop_list(self, interaction: discord.Interaction):
        loops = db.list_active_reminder_loops(interaction.guild.id)
        if not loops:
            await interaction.response.send_message("No active reminder loops.", ephemeral=True)
            return
        lines = []
        for loop in loops:
            channel = interaction.guild.get_channel(loop["channel_id"])
            role = interaction.guild.get_role(loop["role_id"])
            preview = loop["message"][:60] + ("…" if len(loop["message"]) > 60 else "")
            lines.append(
                f"**#{loop['id']}** — every {format_duration(loop['interval_seconds'])} in "
                f"{channel.mention if channel else '?'} pinging {role.mention if role else '?'}\n> {preview}"
            )
        await interaction.response.send_message("\n".join(lines), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="remind-loop-stop", description="Stop a recurring reminder loop.")
    @app_commands.describe(loop_id="The reminder loop's ID, from /remind-loop-list")
    @staff_check()
    async def remind_loop_stop(self, interaction: discord.Interaction, loop_id: int):
        row = db.get_reminder_loop(loop_id)
        if not row or row["guild_id"] != interaction.guild.id:
            await interaction.response.send_message(f"No reminder loop found with ID `{loop_id}` in this server.", ephemeral=True)
            return
        stopped = db.deactivate_reminder_loop(loop_id)
        task = self.loop_tasks.pop(loop_id, None)
        if task:
            task.cancel()
        if stopped:
            await interaction.response.send_message(f"🛑 Reminder loop **#{loop_id}** stopped.", ephemeral=True)
        else:
            await interaction.response.send_message(f"Reminder loop **#{loop_id}** was already stopped.", ephemeral=True)

    # ---------------- personal one-time reminders ----------------

    def start_reminder_task(self, reminder_id: int, remind_at: float):
        task = asyncio.create_task(self._reminder_runner(reminder_id, remind_at))
        self.reminder_tasks[reminder_id] = task

    async def _reminder_runner(self, reminder_id: int, remind_at: float):
        delay = max(0, remind_at - time.time())
        await asyncio.sleep(delay)

        pending = {r["id"]: r for r in db.get_pending_reminders()}
        row = pending.get(reminder_id)
        self.reminder_tasks.pop(reminder_id, None)
        if not row:
            return  # already delivered or removed

        user = self.bot.get_user(row["user_id"]) or await self._safe_fetch_user(row["user_id"])
        if user:
            try:
                await user.send(f"⏰ Reminder: {db.apply_emoji_shortcuts(row['message'])}")
            except discord.HTTPException as e:
                print(f"[Reminder #{reminder_id}] could not DM user {row['user_id']}: {e}")
        db.mark_reminder_delivered(reminder_id)

    async def _safe_fetch_user(self, user_id: int):
        try:
            return await self.bot.fetch_user(user_id)
        except discord.HTTPException:
            return None

    @app_commands.command(name="remind-me", description="DM yourself a reminder after a delay.")
    @app_commands.describe(when="When to be reminded, e.g. 30m, 2h, 1d", message="What to remind you about")
    async def remind_me(self, interaction: discord.Interaction, when: str, message: str):
        seconds = parse_duration(when)
        if not seconds:
            await interaction.response.send_message(
                "Couldn't parse that. Try things like `30m`, `2h`, `1d`.", ephemeral=True
            )
            return
        remind_at = time.time() + seconds
        reminder_id = db.create_one_time_reminder(
            interaction.guild.id if interaction.guild else None, interaction.user.id, message, remind_at
        )
        self.start_reminder_task(reminder_id, remind_at)
        await interaction.response.send_message(
            f"✅ Got it — I'll DM you in **{format_duration(seconds)}**.", ephemeral=True
        )

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        msg = str(error) if isinstance(error, app_commands.CheckFailure) else "An unexpected error occurred."
        if not isinstance(error, app_commands.CheckFailure):
            log_app_command_error("Reminder", interaction, error)
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ReminderCog(bot))
