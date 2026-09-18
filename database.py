import json
import sqlite3
import time
from contextlib import contextmanager

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id INTEGER PRIMARY KEY,
    admin_role_id INTEGER,
    invite_log_channel_id INTEGER,
    giveaway_ping_role_id INTEGER,
    giveaway_host_role_id INTEGER,
    staff_role_id INTEGER
);

CREATE TABLE IF NOT EXISTS giveaway_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    top_message TEXT,
    icon_url TEXT,
    blacklisted_roles TEXT NOT NULL DEFAULT '[]',
    extra_entry_roles TEXT NOT NULL DEFAULT '[]',
    UNIQUE(guild_id, name)
);

CREATE TABLE IF NOT EXISTS giveaways (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER,
    thread_id INTEGER,
    template_id INTEGER,
    prize TEXT NOT NULL,
    winner_count INTEGER NOT NULL DEFAULT 1,
    host_id INTEGER NOT NULL,
    body_text TEXT,
    end_time REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    rerolled INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS giveaway_entries (
    giveaway_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    PRIMARY KEY (giveaway_id, user_id)
);

CREATE TABLE IF NOT EXISTS invite_cache (
    guild_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0,
    inviter_id INTEGER,
    PRIMARY KEY (guild_id, code)
);

CREATE TABLE IF NOT EXISTS embed_panels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    intro_text TEXT,
    icon_url TEXT,
    channel_id INTEGER,
    message_id INTEGER,
    UNIQUE(guild_id, name)
);

CREATE TABLE IF NOT EXISTS embed_buttons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    panel_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    style TEXT NOT NULL DEFAULT 'blurple',
    embed_title TEXT,
    embed_description TEXT,
    embed_color TEXT,
    embed_image TEXT,
    order_index INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS emoji_shortcuts (
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    emoji TEXT NOT NULL,
    PRIMARY KEY (guild_id, name)
);

CREATE TABLE IF NOT EXISTS giveaway_winners (
    giveaway_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    PRIMARY KEY (giveaway_id, user_id)
);

CREATE TABLE IF NOT EXISTS leaderboard_teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    leaderboard_name TEXT NOT NULL,
    team_name TEXT NOT NULL,
    score INTEGER NOT NULL DEFAULT 0,
    UNIQUE(guild_id, leaderboard_name, team_name)
);

CREATE TABLE IF NOT EXISTS team_members (
    team_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    PRIMARY KEY (team_id, user_id)
);

CREATE TABLE IF NOT EXISTS reminder_loops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    interval_seconds INTEGER NOT NULL,
    message TEXT NOT NULL,
    created_by INTEGER NOT NULL,
    next_run REAL NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS one_time_reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    user_id INTEGER NOT NULL,
    message TEXT NOT NULL,
    remind_at REAL NOT NULL,
    delivered INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS autoresponses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    trigger TEXT NOT NULL,
    response TEXT NOT NULL,
    UNIQUE(guild_id, trigger)
);

CREATE TABLE IF NOT EXISTS leaderboards (
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    channel_id INTEGER,
    message_id INTEGER,
    color TEXT DEFAULT '5865f2',
    image_url TEXT,
    emoji TEXT DEFAULT '🏆',
    mode TEXT NOT NULL DEFAULT 'individual',
    PRIMARY KEY (guild_id, name)
);

CREATE TABLE IF NOT EXISTS leaderboard_scores (
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    score INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, name, user_id)
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(_SCHEMA)
        # Migration for databases created before giveaway_ping_role_id was added.
        try:
            conn.execute("ALTER TABLE guild_settings ADD COLUMN giveaway_ping_role_id INTEGER")
        except sqlite3.OperationalError:
            pass  # column already exists
        # Migration for databases created before leaderboards.mode was added.
        try:
            conn.execute("ALTER TABLE leaderboards ADD COLUMN mode TEXT NOT NULL DEFAULT 'individual'")
        except sqlite3.OperationalError:
            pass
        # Migration for databases created before giveaways.rerolled was added.
        try:
            conn.execute("ALTER TABLE giveaways ADD COLUMN rerolled INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        # Migration for databases created before giveaway_host_role_id was added.
        try:
            conn.execute("ALTER TABLE guild_settings ADD COLUMN giveaway_host_role_id INTEGER")
        except sqlite3.OperationalError:
            pass
        # Migration for databases created before staff_role_id was added.
        try:
            conn.execute("ALTER TABLE guild_settings ADD COLUMN staff_role_id INTEGER")
        except sqlite3.OperationalError:
            pass


# ---------------- guild settings ----------------

def get_guild_settings(guild_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        return dict(row) if row else {
            "guild_id": guild_id, "admin_role_id": None,
            "invite_log_channel_id": None, "giveaway_ping_role_id": None,
            "giveaway_host_role_id": None, "staff_role_id": None,
        }


def set_admin_role(guild_id, role_id):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO guild_settings (guild_id, admin_role_id) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET admin_role_id = excluded.admin_role_id",
            (guild_id, role_id),
        )


def set_invite_log_channel(guild_id, channel_id):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO guild_settings (guild_id, invite_log_channel_id) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET invite_log_channel_id = excluded.invite_log_channel_id",
            (guild_id, channel_id),
        )


def set_giveaway_ping_role(guild_id, role_id):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO guild_settings (guild_id, giveaway_ping_role_id) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET giveaway_ping_role_id = excluded.giveaway_ping_role_id",
            (guild_id, role_id),
        )


def set_giveaway_host_role(guild_id, role_id):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO guild_settings (guild_id, giveaway_host_role_id) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET giveaway_host_role_id = excluded.giveaway_host_role_id",
            (guild_id, role_id),
        )


def set_staff_role(guild_id, role_id):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO guild_settings (guild_id, staff_role_id) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET staff_role_id = excluded.staff_role_id",
            (guild_id, role_id),
        )


# ---------------- giveaway templates ----------------

def create_template(guild_id, name, top_message, icon_url, blacklisted_roles, extra_entry_roles):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO giveaway_templates "
            "(guild_id, name, top_message, icon_url, blacklisted_roles, extra_entry_roles) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id, name) DO UPDATE SET "
            "top_message=excluded.top_message, icon_url=excluded.icon_url, "
            "blacklisted_roles=excluded.blacklisted_roles, extra_entry_roles=excluded.extra_entry_roles",
            (guild_id, name, top_message, icon_url, json.dumps(blacklisted_roles), json.dumps(extra_entry_roles)),
        )


def get_template(guild_id, name):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM giveaway_templates WHERE guild_id = ? AND name = ?", (guild_id, name)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["blacklisted_roles"] = json.loads(d["blacklisted_roles"])
        d["extra_entry_roles"] = json.loads(d["extra_entry_roles"])
        return d


def list_templates(guild_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT name FROM giveaway_templates WHERE guild_id = ? ORDER BY name", (guild_id,)
        ).fetchall()
        return [r["name"] for r in rows]


# ---------------- giveaways ----------------

def create_giveaway(guild_id, channel_id, template_id, prize, winner_count, host_id, body_text, end_time):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO giveaways (guild_id, channel_id, template_id, prize, winner_count, "
            "host_id, body_text, end_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (guild_id, channel_id, template_id, prize, winner_count, host_id, body_text, end_time),
        )
        return cur.lastrowid


def set_giveaway_message(giveaway_id, message_id, thread_id=None):
    with get_conn() as conn:
        if thread_id is not None:
            conn.execute(
                "UPDATE giveaways SET message_id = ?, thread_id = ? WHERE id = ?",
                (message_id, thread_id, giveaway_id),
            )
        else:
            conn.execute(
                "UPDATE giveaways SET message_id = ? WHERE id = ?", (message_id, giveaway_id)
            )


def update_giveaway(giveaway_id, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [giveaway_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE giveaways SET {cols} WHERE id = ?", values)


def get_giveaway(giveaway_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM giveaways WHERE id = ?", (giveaway_id,)).fetchone()
        return dict(row) if row else None


def get_running_giveaways():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM giveaways WHERE status = 'running'").fetchall()
        return [dict(r) for r in rows]


def add_entry(giveaway_id, user_id):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO giveaway_entries (giveaway_id, user_id) VALUES (?, ?)",
            (giveaway_id, user_id),
        )


def remove_entry(giveaway_id, user_id):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
            (giveaway_id, user_id),
        )


def has_entry(giveaway_id, user_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
            (giveaway_id, user_id),
        ).fetchone()
        return row is not None


def count_entries(giveaway_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,)
        ).fetchone()
        return row["c"]


def list_entries(giveaway_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT user_id FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,)
        ).fetchall()
        return [r["user_id"] for r in rows]


# ---------------- invite tracking ----------------

def cache_invites(guild_id, invites):
    """invites: list of (code, uses, inviter_id)"""
    with get_conn() as conn:
        for code, uses, inviter_id in invites:
            conn.execute(
                "INSERT INTO invite_cache (guild_id, code, uses, inviter_id) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(guild_id, code) DO UPDATE SET uses = excluded.uses, inviter_id = excluded.inviter_id",
                (guild_id, code, uses, inviter_id),
            )


def get_cached_invites(guild_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM invite_cache WHERE guild_id = ?", (guild_id,)
        ).fetchall()
        return {r["code"]: dict(r) for r in rows}


def update_invite_use(guild_id, code, uses):
    with get_conn() as conn:
        conn.execute(
            "UPDATE invite_cache SET uses = ? WHERE guild_id = ? AND code = ?",
            (uses, guild_id, code),
        )


def count_invites_by_user(guild_id, user_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(uses), 0) AS total FROM invite_cache WHERE guild_id = ? AND inviter_id = ?",
            (guild_id, user_id),
        ).fetchone()
        return row["total"]


# ---------------- embed panels ----------------

def create_panel(guild_id, name, intro_text, icon_url):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO embed_panels (guild_id, name, intro_text, icon_url) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, name) DO UPDATE SET intro_text=excluded.intro_text, icon_url=excluded.icon_url",
            (guild_id, name, intro_text, icon_url),
        )
        row = conn.execute(
            "SELECT id FROM embed_panels WHERE guild_id = ? AND name = ?", (guild_id, name)
        ).fetchone()
        return row["id"]


def get_panel(guild_id, name):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM embed_panels WHERE guild_id = ? AND name = ?", (guild_id, name)
        ).fetchone()
        return dict(row) if row else None


def get_panel_by_id(panel_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM embed_panels WHERE id = ?", (panel_id,)).fetchone()
        return dict(row) if row else None


def list_panels(guild_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT name FROM embed_panels WHERE guild_id = ? ORDER BY name", (guild_id,)
        ).fetchall()
        return [r["name"] for r in rows]


def set_panel_message(panel_id, channel_id, message_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE embed_panels SET channel_id = ?, message_id = ? WHERE id = ?",
            (channel_id, message_id, panel_id),
        )


def add_button(panel_id, label, style, embed_title, embed_description, embed_color, embed_image):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(order_index), -1) + 1 AS n FROM embed_buttons WHERE panel_id = ?",
            (panel_id,),
        ).fetchone()
        order_index = row["n"]
        cur = conn.execute(
            "INSERT INTO embed_buttons (panel_id, label, style, embed_title, embed_description, "
            "embed_color, embed_image, order_index) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (panel_id, label, style, embed_title, embed_description, embed_color, embed_image, order_index),
        )
        return cur.lastrowid


def get_buttons(panel_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM embed_buttons WHERE panel_id = ? ORDER BY order_index", (panel_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_button(button_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM embed_buttons WHERE id = ?", (button_id,)).fetchone()
        return dict(row) if row else None


def update_button(button_id, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [button_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE embed_buttons SET {cols} WHERE id = ?", values)


def delete_button(button_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM embed_buttons WHERE id = ?", (button_id,))


# ---------------- autoresponses ----------------

def add_autoresponse(guild_id, trigger, response):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO autoresponses (guild_id, trigger, response) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, trigger) DO UPDATE SET response = excluded.response",
            (guild_id, trigger.lower().strip(), response),
        )


def remove_autoresponse(guild_id, trigger):
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM autoresponses WHERE guild_id = ? AND trigger = ?",
            (guild_id, trigger.lower().strip()),
        )
        return cur.rowcount > 0


def get_autoresponse(guild_id, trigger):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM autoresponses WHERE guild_id = ? AND trigger = ?",
            (guild_id, trigger.lower().strip()),
        ).fetchone()
        return dict(row) if row else None


def list_autoresponses(guild_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM autoresponses WHERE guild_id = ? ORDER BY trigger", (guild_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------- leaderboards ----------------

def create_leaderboard(guild_id, name, channel_id, color, image_url, emoji, mode="individual"):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO leaderboards (guild_id, name, channel_id, color, image_url, emoji, mode) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id, name) DO UPDATE SET channel_id=excluded.channel_id, "
            "color=excluded.color, image_url=excluded.image_url, emoji=excluded.emoji, mode=excluded.mode",
            (guild_id, name, channel_id, color, image_url, emoji, mode),
        )


def set_leaderboard_message(guild_id, name, message_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE leaderboards SET message_id = ? WHERE guild_id = ? AND name = ?",
            (message_id, guild_id, name),
        )


def get_leaderboard(guild_id, name):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM leaderboards WHERE guild_id = ? AND name = ?", (guild_id, name)
        ).fetchone()
        return dict(row) if row else None


def delete_leaderboard(guild_id, name):
    with get_conn() as conn:
        conn.execute("DELETE FROM leaderboards WHERE guild_id = ? AND name = ?", (guild_id, name))
        conn.execute("DELETE FROM leaderboard_scores WHERE guild_id = ? AND name = ?", (guild_id, name))


def list_leaderboards(guild_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT name FROM leaderboards WHERE guild_id = ? ORDER BY name", (guild_id,)
        ).fetchall()
        return [r["name"] for r in rows]


def adjust_score(guild_id, name, user_id, delta):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO leaderboard_scores (guild_id, name, user_id, score) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, name, user_id) DO UPDATE SET score = score + excluded.score",
            (guild_id, name, user_id, delta),
        )


def get_scores(guild_id, name):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT user_id, score FROM leaderboard_scores WHERE guild_id = ? AND name = ? "
            "ORDER BY score DESC",
            (guild_id, name),
        ).fetchall()
        return [dict(r) for r in rows]


def get_user_score(guild_id, name, user_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT score FROM leaderboard_scores WHERE guild_id = ? AND name = ? AND user_id = ?",
            (guild_id, name, user_id),
        ).fetchone()
        return row["score"] if row else 0


def set_leaderboard_mode(guild_id, name, mode):
    with get_conn() as conn:
        conn.execute(
            "UPDATE leaderboards SET mode = ? WHERE guild_id = ? AND name = ?", (mode, guild_id, name)
        )


# ---------------- emoji shortcuts ----------------

def add_emoji_shortcut(guild_id, name, emoji):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO emoji_shortcuts (guild_id, name, emoji) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, name) DO UPDATE SET emoji = excluded.emoji",
            (guild_id, name.lower().strip(), emoji),
        )


def remove_emoji_shortcut(guild_id, name):
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM emoji_shortcuts WHERE guild_id = ? AND name = ?", (guild_id, name.lower().strip())
        )
        return cur.rowcount > 0


def list_emoji_shortcuts(guild_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM emoji_shortcuts WHERE guild_id = ? ORDER BY name", (guild_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def apply_emoji_shortcuts(guild_id, text):
    """Replaces :name: occurrences in text with registered emoji shortcuts."""
    if not text:
        return text
    shortcuts = list_emoji_shortcuts(guild_id)
    for row in shortcuts:
        text = text.replace(f":{row['name']}:", row["emoji"])
    return text


# ---------------- giveaway winners ----------------

def record_winners(giveaway_id, user_ids):
    with get_conn() as conn:
        for uid in user_ids:
            conn.execute(
                "INSERT OR IGNORE INTO giveaway_winners (giveaway_id, user_id) VALUES (?, ?)",
                (giveaway_id, uid),
            )


def get_winners(giveaway_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT user_id FROM giveaway_winners WHERE giveaway_id = ?", (giveaway_id,)
        ).fetchall()
        return [r["user_id"] for r in rows]


def mark_rerolled(giveaway_id):
    with get_conn() as conn:
        conn.execute("UPDATE giveaways SET rerolled = 1 WHERE id = ?", (giveaway_id,))


# ---------------- team leaderboards ----------------

def create_team(guild_id, leaderboard_name, team_name):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO leaderboard_teams (guild_id, leaderboard_name, team_name) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, leaderboard_name, team_name) DO NOTHING",
            (guild_id, leaderboard_name, team_name),
        )
        row = conn.execute(
            "SELECT id FROM leaderboard_teams WHERE guild_id = ? AND leaderboard_name = ? AND team_name = ?",
            (guild_id, leaderboard_name, team_name),
        ).fetchone()
        return row["id"]


def get_team(guild_id, leaderboard_name, team_name):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM leaderboard_teams WHERE guild_id = ? AND leaderboard_name = ? AND team_name = ?",
            (guild_id, leaderboard_name, team_name),
        ).fetchone()
        return dict(row) if row else None


def get_team_by_id(team_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM leaderboard_teams WHERE id = ?", (team_id,)).fetchone()
        return dict(row) if row else None


def list_teams(guild_id, leaderboard_name):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM leaderboard_teams WHERE guild_id = ? AND leaderboard_name = ? ORDER BY score DESC",
            (guild_id, leaderboard_name),
        ).fetchall()
        return [dict(r) for r in rows]


def get_user_team(guild_id, leaderboard_name, user_id):
    """Returns the team dict a user belongs to on this leaderboard, or None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT t.* FROM leaderboard_teams t JOIN team_members m ON m.team_id = t.id "
            "WHERE t.guild_id = ? AND t.leaderboard_name = ? AND m.user_id = ?",
            (guild_id, leaderboard_name, user_id),
        ).fetchone()
        return dict(row) if row else None


def add_team_member(team_id, user_id):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO team_members (team_id, user_id) VALUES (?, ?)", (team_id, user_id)
        )


def remove_team_member(team_id, user_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM team_members WHERE team_id = ? AND user_id = ?", (team_id, user_id))


def get_team_members(team_id):
    with get_conn() as conn:
        rows = conn.execute("SELECT user_id FROM team_members WHERE team_id = ?", (team_id,)).fetchall()
        return [r["user_id"] for r in rows]


def adjust_team_score(team_id, delta):
    with get_conn() as conn:
        conn.execute("UPDATE leaderboard_teams SET score = score + ? WHERE id = ?", (delta, team_id))


def disband_team(team_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM team_members WHERE team_id = ?", (team_id,))
        conn.execute("DELETE FROM leaderboard_teams WHERE id = ?", (team_id,))


# ---------------- reminder loops ----------------

def create_reminder_loop(guild_id, channel_id, role_id, interval_seconds, message, created_by, next_run):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO reminder_loops (guild_id, channel_id, role_id, interval_seconds, message, "
            "created_by, next_run) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, channel_id, role_id, interval_seconds, message, created_by, next_run),
        )
        return cur.lastrowid


def get_reminder_loop(loop_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM reminder_loops WHERE id = ?", (loop_id,)).fetchone()
        return dict(row) if row else None


def list_active_reminder_loops(guild_id=None):
    with get_conn() as conn:
        if guild_id is None:
            rows = conn.execute("SELECT * FROM reminder_loops WHERE active = 1").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM reminder_loops WHERE active = 1 AND guild_id = ?", (guild_id,)
            ).fetchall()
        return [dict(r) for r in rows]


def set_reminder_loop_next_run(loop_id, next_run):
    with get_conn() as conn:
        conn.execute("UPDATE reminder_loops SET next_run = ? WHERE id = ?", (next_run, loop_id))


def deactivate_reminder_loop(loop_id):
    with get_conn() as conn:
        cur = conn.execute("UPDATE reminder_loops SET active = 0 WHERE id = ? AND active = 1", (loop_id,))
        return cur.rowcount > 0


# ---------------- one-time reminders ----------------

def create_one_time_reminder(guild_id, user_id, message, remind_at):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO one_time_reminders (guild_id, user_id, message, remind_at) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, message, remind_at),
        )
        return cur.lastrowid


def get_pending_reminders():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM one_time_reminders WHERE delivered = 0").fetchall()
        return [dict(r) for r in rows]


def mark_reminder_delivered(reminder_id):
    with get_conn() as conn:
        conn.execute("UPDATE one_time_reminders SET delivered = 1 WHERE id = ?", (reminder_id,))

