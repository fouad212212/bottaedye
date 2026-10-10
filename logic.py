# -*- coding: utf-8 -*-
"""
Game logic and embed builders shared by the panel, the Guardian panel and the
background tasks. Functions that take ``data`` MUTATE it and expect the caller
to hold ``storage.edit()`` - they never save by themselves.

Language: every function that produces text takes ``lang`` ("en" | "ar").
Canon phrases ("Tikki, Spots On!") are always English, like in the show.
"""

import random
import time

import discord

import storage
from i18n import tr
from miraculous_data import (
    CANON_POWER_COUNTDOWN,
    FUSION_FORMS,
    GUARDIAN_ROLE_NAME,
    MIRACULOUS,
    POWER_COUNTDOWN_SECONDS,
    TRANSFORM_DURATION_SECONDS,
    TRANSFORM_WARNING_SECONDS,
    UNIFY_ADD_PHRASE,
    UNIFY_DIVIDE_PHRASE,
    UNIFY_PHRASES,
    UNIFY_RELEASE_ALL_PHRASE,
)

PINK = 0xFF1493
GREY = 0x2F3136


# ------------------------------------------------------------------ #
#  Small helpers
# ------------------------------------------------------------------ #

def is_guardian(member: discord.Member, data: dict) -> bool:
    if member.guild_permissions.administrator:
        return True
    if member.id in data.get("guardian_ids", []):
        return True
    return discord.utils.get(member.roles, name=GUARDIAN_ROLE_NAME) is not None


def get_active(data: dict, user_id: int):
    return data["transformed"].get(str(user_id))


def actor_line(secret: bool, member, hero_name: str, lang: str = "en") -> str:
    """How a transformed member is named in an announcement. With Secret
    Identity on, the real @mention is never shown."""
    if secret or member is None:
        return f"**{hero_name}**"
    return tr(lang, "emb.actor_as", mention=member.mention, hero=hero_name)


def kwami_list(names: list) -> str:
    return ", ".join(MIRACULOUS[n]["kwami"] for n in names)


def emoji_list(names: list) -> str:
    return " ".join(MIRACULOUS[n]["emoji"] for n in names)


def clip(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def fit_lines(lines: list, max_lines: int = 10) -> str:
    """Joins lines for an embed field (1024 character limit)."""
    shown = list(lines[:max_lines])
    extra = len(lines) - max_lines
    if extra > 0:
        shown.append(f"…+{extra}")
    return "\n".join(shown)[:1024]


def fmt_minutes(seconds: float) -> str:
    seconds = max(0, int(seconds))
    mins, secs = divmod(seconds, 60)
    return f"{mins}m {secs:02d}s"


def food_of(name: str) -> str:
    return MIRACULOUS[name].get("food") or None


# ------------------------------------------------------------------ #
#  Canon phrases
# ------------------------------------------------------------------ #

def transform_phrase(name: str, dark: bool = False) -> str:
    info = MIRACULOUS[name]
    if dark and info.get("dark_phrase"):
        return info["dark_phrase"]
    return info["phrase"]


def detransform_phrase(name: str, dark: bool = False) -> str:
    """Canon de-transformation phrase. Miraculous whose phrase was never
    revealed (None in miraculous_data.py) fall back to a neutral one."""
    info = MIRACULOUS[name]
    if dark and info.get("dark_detransform"):
        return info["dark_detransform"]
    return info.get("detransform") or f"{info['kwami']}, Power Down!"


def unify_phrase(all_names: list, new_names: list, from_civilian: bool) -> str:
    """Canon Unification phrase (see miraculous_data.py)."""
    if not from_civilian:
        return f"{kwami_list(new_names)}, {UNIFY_ADD_PHRASE}"
    word = UNIFY_PHRASES.get(len(all_names), UNIFY_ADD_PHRASE)
    return f"{kwami_list(all_names)}, {word}"


def fusion_form_name(names: list):
    return FUSION_FORMS.get(frozenset(names))


# ------------------------------------------------------------------ #
#  Channel gate & logging
# ------------------------------------------------------------------ #

async def ensure_channel_allowed(interaction: discord.Interaction, data: dict, lang: str) -> bool:
    """Gate for RP actions when the Guardian restricted them to some channels.
    Sends the error itself and returns False when blocked."""
    if storage.channel_allowed(data, interaction.channel.id):
        return True
    allowed = data.get("allowed_channels", [])
    where = ", ".join(f"<#{cid}>" for cid in allowed)
    await interaction.response.send_message(tr(lang, "err.channel_restricted", where=where), ephemeral=True)
    return False


async def _post(guild: discord.Guild, channel_id, embed: discord.Embed) -> None:
    if not channel_id:
        return
    channel = guild.get_channel(channel_id)
    if channel is None:
        return
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass


async def log_action(guild: discord.Guild, data: dict, embed: discord.Embed) -> None:
    """Best-effort post to the Guardian audit log channel."""
    await _post(guild, data.get("log_channel_id"), embed)


async def log_rp_event(guild: discord.Guild, data: dict, embed: discord.Embed) -> None:
    """Best-effort copy of a story beat to the separate RP log channel."""
    await _post(guild, data.get("rp_log_channel_id"), embed)


# ------------------------------------------------------------------ #
#  Transformation state changes (mutate `data`)
# ------------------------------------------------------------------ #

def strip_miraculous(data: dict, user_id: int, name: str) -> bool:
    """Removes ONE Miraculous from the member's active transformation (used
    when a Miraculous is taken, stolen or reclaimed). Ends the transformation
    entirely when nothing is left. Returns True if the member was affected."""
    entry = get_active(data, user_id)
    if not entry or name not in entry["miraculous"]:
        return False
    entry["miraculous"] = [n for n in entry["miraculous"] if n != name]
    if "Ladybug" not in entry["miraculous"]:
        entry.pop("lucky_charm", None)
    if not entry["miraculous"]:
        del data["transformed"][str(user_id)]
    return True


def strip_all_active(data: dict, user_id: int) -> None:
    data["transformed"].pop(str(user_id), None)


def tired_blockers(data: dict, names: list) -> list:
    """Miraculous in `names` whose Kwami is too tired to transform."""
    if not data["settings"]["kwami_food_enabled"]:
        return []
    return [n for n in names if storage.is_tired(data, n)]


def do_transform(data: dict, member: discord.Member, names: list, hero_name: str, channel_id: int,
                 add_to_active: bool = False, dark: bool = False, lang: str = "en") -> discord.Embed:
    """Transforms the member (1 Miraculous = normal, 2+ = Unification) and
    returns the public announcement. add_to_active=True is the canon
    "Unify!" while already transformed: the timer keeps running."""
    existing = get_active(data, member.id)

    if add_to_active and existing:
        new_names = [n for n in names if n not in existing["miraculous"]]
        existing["miraculous"] = existing["miraculous"] + new_names
        entry = existing
        hero_name = existing["hero_name"]
        dark = existing.get("dark", False)
        from_civilian = False
    else:
        new_names = list(names)
        entry = {"miraculous": new_names, "hero_name": hero_name, "dark": dark,
                 "countdown": False, "power_used": False}
        storage.start_transform_timer(entry, channel_id, TRANSFORM_DURATION_SECONDS)
        from_civilian = True

    all_names = entry["miraculous"]
    data["transformed"][str(member.id)] = entry
    storage.set_hero_name(data, member.id, hero_name)
    storage.bump_stat(data, member.id, "transforms")
    storage.touch(data, member.id)

    who = actor_line(storage.is_secret(data, member.id), member, hero_name, lang)
    infos = [MIRACULOUS[n] for n in all_names]

    if len(infos) == 1:
        info = infos[0]
        phrase = transform_phrase(all_names[0], dark)
        embed = discord.Embed(
            title=f"{'🌑 ' if dark else ''}{info['emoji']} {hero_name}!",
            description=f"**\"{phrase}\"**\n\n" + tr(lang, "emb.transforms", who=who),
            color=0x2B0A3D if dark else info["color"],
        )
    else:
        phrase = unify_phrase(all_names, new_names, from_civilian)
        powers = "\n".join(f"• **{i['kwami']}** — {i['signature_move']} ({i['tool']})" for i in infos)
        form = fusion_form_name(all_names)
        form_line = "\n\n" + tr(lang, "emb.fusion_known_as", form=form) if form else ""
        key = "emb.unifies_new" if from_civilian else "emb.unifies_add"
        embed = discord.Embed(
            title=f"{'🌑 ' if dark else ''}{emoji_list(all_names)} {hero_name}!",
            description=f"**\"{phrase}\"**\n\n" + tr(lang, key, who=who) + f"\n\n{powers}{form_line}",
            color=0x2B0A3D if dark else PINK,
        )

    if from_civilian:
        embed.set_footer(text=tr(lang, "emb.lasts", minutes=TRANSFORM_DURATION_SECONDS // 60))
    else:
        embed.set_footer(text=tr(lang, "emb.timer_continues"))
    return embed


def detransform_embed(member, secret: bool, entry: dict, release: list, lang: str = "en") -> discord.Embed:
    """Single Miraculous: its own phrase. Whole fusion: Reverse Morphosis.
    Part of a fusion: Divide."""
    hero_name = entry["hero_name"]
    dark = entry.get("dark", False)
    active_names = entry["miraculous"]
    keep = [n for n in active_names if n not in release]
    who = actor_line(secret, member, hero_name, lang)

    if not keep:
        if len(release) == 1:
            phrase = detransform_phrase(release[0], dark)
        else:
            phrase = f"{kwami_list(release)}, {UNIFY_RELEASE_ALL_PHRASE}"
        embed = discord.Embed(
            title=tr(lang, "emb.detransforms_title", hero=hero_name),
            description=f"**\"{phrase}\"**\n\n" + tr(
                lang, "emb.detransforms", who=who,
                kwamis=" & ".join(MIRACULOUS[n]["kwami"] for n in release),
                emojis=emoji_list(release)),
            color=GREY,
        )
        embed.set_footer(text=tr(lang, "emb.transform_again"))
    else:
        phrase = f"{kwami_list(release)}, {kwami_list(keep)}, {UNIFY_DIVIDE_PHRASE}"
        embed = discord.Embed(
            title=tr(lang, "emb.divides_title", hero=hero_name),
            description=f"**\"{phrase}\"**\n\n" + tr(
                lang, "emb.divides", who=who,
                released=" & ".join(MIRACULOUS[n]["kwami"] for n in release),
                kept=" & ".join(MIRACULOUS[n]["kwami"] for n in keep),
                released_emojis=emoji_list(release), kept_emojis=emoji_list(keep)),
            color=GREY,
        )
    return embed


def apply_detransform(data: dict, user_id: int, release: list) -> None:
    """Removes the released Miraculous from the member's transformation."""
    entry = get_active(data, user_id)
    if not entry:
        return
    keep = [n for n in entry["miraculous"] if n not in release]
    if keep:
        entry["miraculous"] = keep
        if "Ladybug" not in keep:
            entry.pop("lucky_charm", None)
    else:
        del data["transformed"][str(user_id)]


def register_power_use(data: dict, user_id: int, miraculous_name: str) -> bool:
    """Bookkeeping after a signature power: stats, Kwami tiredness and the
    canon ~5 minute countdown. Returns True if the countdown just started."""
    info = MIRACULOUS[miraculous_name]
    storage.bump_power(data, user_id, info["signature_move"])
    storage.touch(data, user_id)
    if data["settings"]["kwami_food_enabled"]:
        storage.set_tired(data, miraculous_name, True)

    entry = get_active(data, user_id)
    started = False
    if entry:
        entry["power_used"] = True
        if CANON_POWER_COUNTDOWN and not entry.get("countdown"):
            entry["countdown"] = True
            new_expiry = time.time() + POWER_COUNTDOWN_SECONDS
            if new_expiry < entry["expires_at"]:
                entry["expires_at"] = new_expiry
                entry["warned"] = False
                started = True
    return started


# ------------------------------------------------------------------ #
#  Duel / theft rolls
# ------------------------------------------------------------------ #

def combat_score(data: dict, user_id: int, bonus: int = 0) -> int:
    """d100 + 10 per extra fused Miraculous + 5 if a power was used."""
    entry = get_active(data, user_id)
    score = random.randint(1, 100) + bonus
    if entry:
        score += 10 * (len(entry["miraculous"]) - 1)
        if entry.get("power_used"):
            score += 5
    return score


def free_from_akuma(data: dict, user_id: int):
    """Returns the removed akuma/amok state of a member, or None."""
    return data["granted_powers"].pop(str(user_id), None)


# ------------------------------------------------------------------ #
#  Embeds
# ------------------------------------------------------------------ #

def miraculous_box_embed(guild: discord.Guild, data: dict, lang: str) -> discord.Embed:
    embed = discord.Embed(title=tr(lang, "emb.box_title"), color=0x9932CC)
    food_on = data["settings"]["kwami_food_enabled"]
    for name, info in MIRACULOUS.items():
        holder_id = data["holders"].get(name)
        if holder_id:
            member = guild.get_member(holder_id)
            holder_text = member.mention if member else tr(lang, "emb.member_left")
        else:
            holder_text = tr(lang, "emb.available")
        tired = " 😴" if (holder_id and food_on and storage.is_tired(data, name)) else ""
        embed.add_field(
            name=f"{info['emoji']} {name} — {info['kwami']} ({info['concept']})",
            value=tr(lang, "emb.holder", holder=holder_text) + tired,
            inline=False,
        )
    return embed


def my_miraculous_embed(member: discord.Member, data: dict, lang: str) -> discord.Embed:
    held = storage.find_member_miraculous_list(data, member.id)
    active = get_active(data, member.id)
    hero_name = storage.get_hero_name(data, member.id)

    if not held:
        return discord.Embed(
            title=tr(lang, "emb.mine_none_title"),
            description=tr(lang, "emb.mine_none_desc"),
            color=0x808080,
        )

    if active:
        kwamis = " + ".join(MIRACULOUS[n]["kwami"] for n in active["miraculous"])
        remaining = fmt_minutes(active.get("expires_at", time.time()) - time.time())
        status = tr(lang, "emb.status_transformed", hero=active["hero_name"], kwamis=kwamis, left=remaining)
        if active.get("dark"):
            status = "🌑 " + status
    else:
        status = tr(lang, "emb.status_idle")

    title = tr(lang, "emb.mine_title_many", n=len(held)) if len(held) > 1 else tr(lang, "emb.mine_title_one", name=held[0])
    embed = discord.Embed(title=title, description=tr(lang, "emb.status", status=status), color=PINK)
    embed.add_field(name=tr(lang, "emb.hero_name"), value=hero_name or tr(lang, "emb.hero_name_unset"), inline=False)
    embed.add_field(
        name=tr(lang, "emb.identity"),
        value=tr(lang, "emb.identity_secret") if storage.is_secret(data, member.id) else tr(lang, "emb.identity_public"),
        inline=True,
    )
    embed.add_field(
        name=tr(lang, "emb.dark_side"),
        value=tr(lang, "emb.on") if storage.is_dark(data, member.id) else tr(lang, "emb.off"),
        inline=True,
    )

    food_on = data["settings"]["kwami_food_enabled"]
    lines = []
    for name in held:
        info = MIRACULOUS[name]
        state = ""
        if food_on:
            if storage.is_tired(data, name):
                state = " — " + tr(lang, "emb.kwami_tired", food=food_of(name) or tr(lang, "emb.any_snack"))
            else:
                state = " — " + tr(lang, "emb.kwami_ready")
        lines.append(f"{info['emoji']} **{name}** · {info['kwami']} ({info['concept']}){state}")
    embed.add_field(name=tr(lang, "emb.your_kwamis"), value=fit_lines(lines, 19), inline=False)

    s = storage.get_stats(data, member.id)
    rec = storage.get_duel_record(data, member.id) or {"wins": 0, "losses": 0}
    top_power = max(s["powers"].items(), key=lambda kv: kv[1]) if s["powers"] else None
    stat_lines = [
        tr(lang, "emb.stat_transforms", n=s["transforms"]),
        tr(lang, "emb.stat_duels", w=rec["wins"], l=rec["losses"], streak=s["duel_streak"], best=s["best_streak"]),
        tr(lang, "emb.stat_powers", n=data["power_use_count"].get(str(member.id), 0)),
    ]
    if top_power:
        stat_lines.append(tr(lang, "emb.stat_top_power", power=top_power[0], n=top_power[1]))
    if s.get("cures"):
        stat_lines.append(tr(lang, "emb.stat_cures", n=s["cures"]))
    if s.get("steals"):
        stat_lines.append(tr(lang, "emb.stat_steals", n=s["steals"]))
    if s.get("crises"):
        stat_lines.append(tr(lang, "emb.stat_crises", n=s["crises"]))
    embed.add_field(name=tr(lang, "emb.stats"), value="\n".join(stat_lines), inline=False)

    if str(member.id) in data["granted_powers"]:
        g = data["granted_powers"][str(member.id)]
        embed.add_field(name=tr(lang, "emb.akumatized_you"), value=clip(g["power"], 200), inline=False)
    return embed


def active_heroes_embed(guild: discord.Guild, data: dict, lang: str) -> discord.Embed:
    embed = discord.Embed(title=tr(lang, "emb.active_title"), color=0x2ECC71)
    if not data["transformed"] and not data["granted_powers"]:
        embed.description = tr(lang, "emb.active_none")
        return embed

    now = time.time()
    lines = []
    for uid_str, entry in data["transformed"].items():
        member = guild.get_member(int(uid_str))
        secret = storage.is_secret(data, int(uid_str))
        kwamis = " + ".join(MIRACULOUS[n]["kwami"] for n in entry["miraculous"])
        who = actor_line(secret, member, entry["hero_name"], lang)
        form = fusion_form_name(entry["miraculous"]) if len(entry["miraculous"]) > 1 else None
        extra = f" · *{form}*" if form else ""
        dark = "🌑 " if entry.get("dark") else ""
        lines.append(dark + tr(lang, "emb.active_line", who=who, kwamis=kwamis, left=fmt_minutes(entry.get("expires_at", now) - now)) + extra)
    if lines:
        embed.add_field(name=tr(lang, "emb.active_heroes"), value=fit_lines(lines, 15), inline=False)

    ak = []
    for uid_str, g in data["granted_powers"].items():
        member = guild.get_member(int(uid_str))
        secret = storage.is_secret(data, int(uid_str))
        name = f"**{storage.get_hero_name(data, int(uid_str)) or '???'}**" if (secret or member is None) else member.mention
        ak.append(f"🦋 {name} — {clip(g['power'], 80)} ({g['source']})")
    if ak:
        embed.add_field(name=tr(lang, "emb.active_akumatized"), value=fit_lines(ak, 10), inline=False)
    return embed


def leaderboard_embed(guild: discord.Guild, data: dict, lang: str) -> discord.Embed:
    def display(uid_str: str) -> str:
        uid = int(uid_str)
        if storage.is_secret(data, uid):
            return storage.get_hero_name(data, uid) or tr(lang, "emb.mysterious")
        member = guild.get_member(uid)
        return member.display_name if member else tr(lang, "emb.unknown")

    embed = discord.Embed(title=tr(lang, "emb.lb_title"), color=0xF1C40F)

    duels = sorted(data["duel_record"].items(), key=lambda kv: kv[1]["wins"], reverse=True)[:5]
    embed.add_field(
        name=tr(lang, "emb.lb_duelists"),
        value="\n".join(f"**{display(u)}** — {r['wins']}W / {r['losses']}L" for u, r in duels) or tr(lang, "emb.lb_no_duels"),
        inline=False,
    )
    powers = sorted(data["power_use_count"].items(), key=lambda kv: kv[1], reverse=True)[:5]
    embed.add_field(
        name=tr(lang, "emb.lb_active"),
        value="\n".join(tr(lang, "emb.lb_power_line", name=display(u), n=c) for u, c in powers) or tr(lang, "emb.lb_no_powers"),
        inline=False,
    )
    streaks = sorted(((u, s.get("best_streak", 0)) for u, s in data["stats"].items()), key=lambda kv: kv[1], reverse=True)[:3]
    streaks = [(u, n) for u, n in streaks if n > 1]
    if streaks:
        embed.add_field(
            name=tr(lang, "emb.lb_streaks"),
            value="\n".join(f"**{display(u)}** — {n}" for u, n in streaks),
            inline=False,
        )
    return embed


def history_embed(guild: discord.Guild, data: dict, lang: str, limit: int = 15) -> discord.Embed:
    embed = discord.Embed(title=tr(lang, "emb.history_title"), color=GREY)
    rows = data["holder_history"][-limit:][::-1]
    if not rows:
        embed.description = tr(lang, "emb.history_none")
        return embed
    lines = []
    for row in rows:
        info = MIRACULOUS.get(row["miraculous"])
        if not info:
            continue
        member = guild.get_member(row["user_id"])
        who = member.mention if member else f"<@{row['user_id']}>"
        by = f" ← <@{row['by']}>" if row.get("by") else ""
        when = f"<t:{int(row['time'])}:R>"
        lines.append(f"{info['emoji']} **{row['miraculous']}** · {tr(lang, 'emb.hist_' + row['action'])} {who}{by} · {when}")
    embed.description = "\n".join(lines)[:4000]
    return embed


def expired_embed(member, entry: dict, secret: bool, lang: str) -> discord.Embed:
    who = actor_line(secret, member, entry["hero_name"], lang)
    return discord.Embed(
        title=tr(lang, "emb.expired_title", hero=entry["hero_name"]),
        description=tr(lang, "emb.expired_desc", who=who, emojis=emoji_list(entry["miraculous"])),
        color=GREY,
    )


def expiry_warning_text(hero_name: str, lang: str) -> str:
    return tr(lang, "msg.expiry_warning", hero=hero_name)


def kwami_intro_embed(name: str, lang: str) -> discord.Embed:
    """Sent by DM when a member receives a Miraculous."""
    info = MIRACULOUS[name]
    food = food_of(name) or tr(lang, "emb.any_snack")
    embed = discord.Embed(
        title=tr(lang, "emb.kwami_intro_title", emoji=info["emoji"], kwami=info["kwami"]),
        description=tr(lang, "emb.kwami_intro_desc", kwami=info["kwami"], name=name,
                       jewel=info["jewel"], concept=info["concept"]) + "\n\n" + info["description"],
        color=info["color"],
    )
    embed.add_field(name=tr(lang, "emb.transform_phrase"), value=f"“{info['phrase']}”", inline=True)
    embed.add_field(name=tr(lang, "emb.detransform_phrase"),
                    value=f"“{detransform_phrase(name)}”", inline=True)
    embed.add_field(name=tr(lang, "emb.signature"), value=f"{info['signature_move']} ({info['tool']})", inline=False)
    embed.add_field(name=tr(lang, "emb.favourite_food"), value=food, inline=True)
    return embed


def welcome_embed(lang: str) -> discord.Embed:
    return discord.Embed(
        title=tr(lang, "emb.welcome_title"),
        description=tr(lang, "emb.welcome_desc"),
        color=PINK,
    )


async def send_kwami_dm(member: discord.Member, name: str, lang: str, first: bool) -> None:
    """DMs the Kwami introduction (plus the guide the very first time).
    `first` comes from storage.mark_welcomed(), called inside storage.edit().
    Closed DMs are silently ignored."""
    embeds = []
    if first:
        embeds.append(welcome_embed(lang))
    embeds.append(kwami_intro_embed(name, lang))
    try:
        await member.send(embeds=embeds)
    except discord.HTTPException:
        pass


def crisis_embed(guild: discord.Guild, data: dict, crisis: dict, lang: str, ended: bool = False) -> discord.Embed:
    """The crisis announcement. Participants are listed by hero name when they
    use Secret Identity, by @mention otherwise."""
    names = []
    for uid in crisis["participants"]:
        entry = data["transformed"].get(str(uid))
        hero = (entry or {}).get("hero_name") or storage.get_hero_name(data, uid) or "???"
        member = guild.get_member(uid)
        names.append(f"**{hero}**" if (storage.is_secret(data, uid) or member is None) else f"{member.mention} (**{hero}**)")
    embed = discord.Embed(
        title=(tr(lang, "emb.crisis_ended_title", title=crisis["title"]) if ended
               else tr(lang, "emb.crisis_title", title=crisis["title"])),
        description=crisis["description"],
        color=0x2ECC71 if ended else 0xE74C3C,
    )
    embed.add_field(
        name=tr(lang, "emb.crisis_fighters", n=len(names)),
        value=fit_lines(names, 15) if names else tr(lang, "emb.crisis_nobody"),
        inline=False,
    )
    embed.set_footer(text=f"crisis:{crisis['id']}")
    return embed
