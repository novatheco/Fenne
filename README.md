# EventBot

A standalone Discord bot with: leaderboards, a giveaway maker, an invite tracker,
multi-button server-info embed panels, and exact-match autoresponses.

## Setup

1. Create a new application + bot at https://discord.com/developers/applications
   and copy its token.
2. In the **Bot** tab of that application, enable these under "Privileged Gateway Intents":
   - **Server Members Intent** (needed for role checks + invite tracking)
   - **Message Content Intent** (needed for exact-match autoresponses)
3. Copy `.env.example` to `.env` and paste your token in:
   ```
   DISCORD_TOKEN=your-bot-token-here
   ```
4. Edit `config.py` and add your Discord user ID(s) to `OWNER_IDS`.
5. Invite the bot to your server with these permissions: **Manage Server** (for the
   invite tracker to read invites), **Manage Roles** is *not* required, plus the usual
   Send Messages / Embed Links / Create Public Threads / Use Application Commands.
6. Install dependencies and run:
   ```
   pip install -r requirements.txt
   python main.py
   ```

Slash commands are guild-scoped by Discord automatically once synced — this can take
up to an hour to show up globally the first time, though it's usually instant.

## First-time setup in your server

Run `/set-admin-role @YourStaffRole` once — this decides who can use the admin commands
below. The server owner and anyone with the `Administrator` permission can always use
them regardless.

## Commands

### Leaderboards
Matches your old bot's leaderboard cog (found in its `main.py`) command-for-command, just
backed by SQLite instead of `leaderboards.json`/`scores.json`:
- `/create-leaderboard channel name [hex_color_code] [image_url] [emoji] [team_mode]` — set
  `team_mode:True` to make it a team leaderboard instead of an individual one (both are supported
  side by side — nothing about individual leaderboards changed)
- `/trophy-add name user amount` — individual leaderboards only
- `/trophy-multi-add name users amount` — `users` is a string of @mentions, individual only
- `/trophy-check name [user]` — see a user's trophy count (or their team's score) on one leaderboard
- `/leaderboard-snapshot name` — posts a **static** copy of the current standings in the channel;
  unlike the main leaderboard message, this one does NOT get edited as scores change
- `/delete-leaderboard name`
- `/all-leaderboards`

**Team leaderboards** (only on leaderboards created with `team_mode:True`):
- `/team-create leaderboard team_name [users]` — creates a team, optionally adding members
  (a user can only be on one team per leaderboard)
- `/team-edit leaderboard team_name [add_users] [remove_users]`
- `/team-disband leaderboard team_name`
- `/team-trophy-add leaderboard team_name amount` — adds/subtracts from the team's single shared score

### Emoji Shortcuts
These are real **application emojis** — owned by the bot itself (up to 2000 total), not just a
text link to an emoji living in some other server. That matters: a plain `<:name:id>` string only
renders if the bot shares that emoji's original server, which is why the old approach silently
broke in places like reminder DMs. Uploaded emojis work anywhere the bot sends a message.

- `/addemoji name image:<file>` — upload an image (PNG/JPG/GIF, under 256KB) as a new emoji
- `/addemoji name from_emoji:<existing emoji>` — or copy an existing custom emoji instead of
  uploading a file (paste the emoji itself into the field)
- `/addemoji name image_url:<link>` — or point at a direct image URL (e.g. a Discord CDN emoji link)
- `/removeemoji name` — deletes it from the bot's application and the shortcut list
- `/listemojis`

Once registered, write `:name:` anywhere in a giveaway's prize/body/title text, a reminder message,
or an AFK reason and it's swapped in automatically. A set of emojis already uploaded to this bot's
application (`edit`, `cancel`, `start`, `party`, `host`, `prize`, `winner`, `blacklist`, `musthave`,
`extraentries`, `bypass`, `reason`, `afktime`, `mail`, and a few spares) are pre-registered on first
run — see `_KNOWN_EMOJIS` in `database.py` if you need to add/adjust the mapping.

### AFK
- `/afk [reason]` — sets you AFK (default reason "AFK"). Clears automatically the next time you
  send a message, with a "welcome back" notice. Anyone who @mentions you while you're AFK gets an
  embed showing your reason and how long you've been away.

### Reminders
- `/set-staff-role @role` — sets who (besides the admin role) can use the staff reminder tools below
- `/remind-loop interval role channel` — staff-only. Opens a form for the plain-text message, then
  posts it (pinging `role`) in `channel` on repeat forever, e.g. every `1h`, `30m`, `1d`, until stopped.
  Survives bot restarts.
- `/remind-loop-list` / `/remind-loop-stop loop_id` — manage active loops (staff-only)
- `/remind-me when message` — anyone can use this; DMs you privately after the delay (e.g. `30m`, `2h`).
  Also survives restarts.


### Giveaways
- `/default-template name` — creates a new template, or **edits an existing one** (running it again
  on a name that already exists pre-fills the forms with the current values). Two chained forms
  (Discord caps popups at 5 fields each) collect: top message, icon, blacklisted roles, must-have
  roles / extra-entry roles, requirements-bypass roles. Roles can be pasted as mentions, IDs, or names.
  - **Blacklisted roles**: can't enter
  - **Must-have roles**: must hold at least one of these to enter
  - **Requirements Bypass roles**: holding one of these skips both the blacklist AND must-have checks
  - **Extra-entry roles**: +1 weighted ticket each in the winner draw
- `/giveaway-ping-role role` — set the single role pinged whenever a new giveaway starts
- `/ga template prize winners duration [channel]` — e.g. `/ga template:general prize:"Nitro" winners:1
  duration:1d channel:#giveaways`. Opens a form for the giveaway body text, then shows a preview with
  **Edit** / **Start** / **Cancel** buttons. Hitting Start posts the giveaway in the chosen channel
  (defaults to the channel you ran the command in) with a join button, pings the configured
  giveaway-ping role, and opens a thread pinging the host. Host-role or admin-role required.
- Duration accepts things like `30m`, `1h`, `2d`, `1d12h`.
- Winners are picked automatically when the timer ends and are announced **in the original
  channel** with a "Giveaway Ended!" embed (the thread just gets a pointer back to it); members
  with an extra-entry role get extra weighted tickets in the draw.
- `/giveaway-reroll giveaway_id` — rerolls a single time, picking new winner(s) from everyone who
  entered *except* the previous winner(s). The giveaway's ID is shown in the footer of its embed.
- `/giveaway-participants giveaway_id` — admin-only, lists everyone currently entered.
- `/giveaway-remove-participant giveaway_id user` — admin-only, removes an entrant and live-updates
  the join button's count if the giveaway is still running.

### Invite Tracker
- `/tracker-to channel` — sets the channel where join logs are posted (embed only, no pings)

### Server Info / Perks Panels
- `/create-embed panel name` — creates the panel's intro message (form for text + icon)
- `/create-embed button panel label [style]` — adds a button to that panel (form for the
  embed shown when it's clicked); `style` is one of `blurple`, `grey`, `green`, `red`
- `/create-embed post panel` — publishes (or republishes) the panel with its current buttons
  in the current channel. Re-run this after adding/editing buttons to push the update.

### Autoresponses
- `/autoresponse-add trigger response` — exact-match (case-insensitive) trigger
- `/autoresponse-remove trigger`
- `/autoresponse-list`

## Notes / things you may want to change
- All data lives in `eventbot.db` (SQLite) in the working directory — back it up before
  redeploying.
- The invite tracker can't detect vanity URLs, widget joins, or joins via a bot's own
  OAuth invite — it'll log those as "Unknown".
- Winner picking uses `guild.get_member`, so it only sees members currently cached by
  the bot; this is normal with the Members intent enabled.
- Every embed the bot generates itself (giveaways, AFK, reminders, leaderboards) uses a fixed
  side-bar color, `config.EMBED_COLOR_HEX` (`#00FFFF` by default). Leaderboards and `/create-embed`
  panel buttons still have their own per-item color pickers on top of that default.
- The little warning banner Discord shows on every bot-submitted popup form ("This form will be
  submitted to X. Do not share passwords...") is injected by the Discord client itself for every
  bot in existence — there's no way for a bot to remove or hide it.
