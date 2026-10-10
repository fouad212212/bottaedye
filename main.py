# -*- coding: utf-8 -*-
"""
Miraculous RP Discord Bot — button-based edition (v2).

Only three slash commands exist; everything else is buttons and menus:

  /panel   — posts the permanent control panel in this channel (Guardians)
  /setup   — quick wizard: RP channels, log channels, first Guardian (admins)
  /backup  — a Guardian can download this server's data as JSON

Setup
-----
1. pip install -r requirements.txt
2. Put DISCORD_TOKEN in a .env file (see .env.example)
3. Enable "Server Members Intent" in the Discord Developer Portal
4. python main.py
5. In a channel, run /panel once. Then /setup (optional).
"""

import logging
import os
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

import guardian
import logic
import storage
from i18n import tr
from miraculous_data import TRANSFORM_WARNING_SECONDS
from views import CrisisView, ExposureView, MainPanelView, RequestDecisionView

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("miraculous")

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!unused-", intents=intents, help_command=None)


# ------------------------------------------------------------------ #
#  Background task 1: expiry warnings, auto-detransform, exposure
#  Runs over every server; each server is edited under its own lock so a
#  button click and this loop can never overwrite each other.
# ------------------------------------------------------------------ #

@tasks.loop(seconds=20)
async def check_transformations():
    for guild_id in storage.list_all_guild_ids():
        guild = bot.get_guild(guild_id)
        if guild is None:
            continue

        events = []   # what to send once the lock is released
        snap = {}
        try:
            async with storage.edit(guild_id) as data:
                if not data["transformed"]:
                    raise storage.Abort
                now = time.time()
                plang = storage.public_language(data)
                changed = False
                snap = {"rp_log_channel_id": data["rp_log_channel_id"], "log_channel_id": data["log_channel_id"]}

                for uid_str, entry in list(data["transformed"].items()):
                    remaining = entry.get("expires_at", now) - now
                    uid = int(uid_str)
                    if remaining <= 0:
                        member = guild.get_member(uid)
                        secret = storage.is_secret(data, uid)
                        embed = logic.expired_embed(member, entry, secret, plang)
                        expose = secret and data["settings"]["exposure_enabled"]
                        events.append(("expired", entry.get("channel_id"), embed, expose, uid, entry["hero_name"], plang))
                        del data["transformed"][uid_str]
                        changed = True
                    elif remaining <= TRANSFORM_WARNING_SECONDS and not entry.get("warned"):
                        entry["warned"] = True
                        changed = True
                        events.append(("warn", entry.get("channel_id"), logic.expiry_warning_text(entry["hero_name"], plang)))

                if not changed:
                    raise storage.Abort
        except Exception:
            log.exception("check_transformations failed for guild %s", guild_id)
            continue

        for event in events:
            channel_id = event[1]
            channel = guild.get_channel(channel_id) if channel_id else None
            try:
                if event[0] == "warn":
                    if channel:
                        await channel.send(event[2])
                else:
                    _, _, embed, expose, uid, hero, plang = event
                    if channel:
                        await channel.send(embed=embed)
                        if expose:
                            risk = discord.Embed(
                                title=tr(plang, "emb.exposure_title"),
                                description=tr(plang, "emb.exposure_desc", hero=hero),
                                color=0xE74C3C)
                            risk.set_footer(text=f"expose:{uid}")
                            await channel.send(embed=risk, view=ExposureView())
                    await logic.log_rp_event(guild, snap, embed)
            except discord.HTTPException:
                pass


@check_transformations.before_loop
async def _before_check():
    await bot.wait_until_ready()


# ------------------------------------------------------------------ #
#  Background task 2: idle Miraculous return to the Miracle Box
#  (only on servers where a Guardian set "idle days" in Settings)
# ------------------------------------------------------------------ #

@tasks.loop(minutes=30)
async def reclaim_idle():
    for guild_id in storage.list_all_guild_ids():
        guild = bot.get_guild(guild_id)
        if guild is None:
            continue
        reclaimed = []
        snap = {}
        plang = "en"
        try:
            async with storage.edit(guild_id) as data:
                days = data["settings"]["idle_days"]
                if not days:
                    raise storage.Abort
                now = time.time()
                cutoff = now - days * 86400
                plang = storage.public_language(data)
                changed = False
                snap = {"rp_log_channel_id": data["rp_log_channel_id"], "log_channel_id": data["log_channel_id"]}
                for name, uid in list(data["holders"].items()):
                    last = data["last_active"].get(str(uid))
                    if last is None:               # never seen: start the clock now
                        data["last_active"][str(uid)] = now
                        changed = True
                    elif last < cutoff and str(uid) not in data["transformed"]:
                        del data["holders"][name]
                        storage.record_history(data, name, uid, "idle")
                        reclaimed.append((name, uid, storage.user_language(data, uid)))
                        changed = True
                if not changed:
                    raise storage.Abort
        except Exception:
            log.exception("reclaim_idle failed for guild %s", guild_id)
            continue

        for name, uid, ulang in reclaimed:
            await logic.log_action(guild, snap, discord.Embed(
                description=tr(plang, "msg.audit_idle", name=name, member=f"<@{uid}>", days=days), color=logic.GREY))
            member = guild.get_member(uid)
            if member:
                try:
                    await member.send(tr(ulang, "msg.idle_dm", name=name, guild=guild.name))
                except discord.HTTPException:
                    pass


@reclaim_idle.before_loop
async def _before_reclaim():
    await bot.wait_until_ready()


# ------------------------------------------------------------------ #
#  Lifecycle
# ------------------------------------------------------------------ #

@bot.event
async def on_ready():
    # Persistent views: their buttons keep working after a restart.
    bot.add_view(MainPanelView())
    bot.add_view(RequestDecisionView())
    bot.add_view(ExposureView())
    bot.add_view(CrisisView())
    if not check_transformations.is_running():
        check_transformations.start()
    if not reclaim_idle.is_running():
        reclaim_idle.start()
    try:
        synced = await bot.tree.sync()
        log.info("Synced %d slash command(s).", len(synced))
    except Exception:
        log.exception("Slash command sync failed")
    log.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    log.exception("Command error", exc_info=error)
    message = "❌ Something went wrong. / حدث خطأ ما."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass


# ------------------------------------------------------------------ #
#  Slash commands (guild-only: they need a server to work on)
# ------------------------------------------------------------------ #

@bot.tree.command(name="panel", description="Post the Miraculous control panel in this channel")
@app_commands.guild_only()
async def panel(interaction: discord.Interaction):
    data = storage.load_guild(interaction.guild.id)
    lang = storage.user_language(data, interaction.user.id)
    if not logic.is_guardian(interaction.user, data):
        await interaction.response.send_message(tr(lang, "err.guardian_only"), ephemeral=True)
        return
    plang = storage.public_language(data)
    embed = discord.Embed(title=tr(plang, "emb.panel_title"), description=tr(plang, "emb.panel_desc"), color=0xFF1493)
    embed.set_footer(text=tr(plang, "emb.panel_footer"))
    await interaction.response.send_message(embed=embed, view=MainPanelView())


@bot.tree.command(name="setup", description="Quick wizard: RP channel(s), log channels, and first Guardian")
@app_commands.guild_only()
async def setup_cmd(interaction: discord.Interaction):
    data = storage.load_guild(interaction.guild.id)
    lang = storage.user_language(data, interaction.user.id)
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(tr(lang, "err.admin_only"), ephemeral=True)
        return
    embed = discord.Embed(title=tr(lang, "emb.setup_title"), description=tr(lang, "emb.setup_desc"), color=0xFF1493)
    await interaction.response.send_message(embed=embed, view=guardian.SetupWizardView(lang), ephemeral=True)


@bot.tree.command(name="backup", description="Download this server's Miraculous data as a JSON file (Guardian only)")
@app_commands.guild_only()
async def backup_cmd(interaction: discord.Interaction):
    data = storage.load_guild(interaction.guild.id)
    lang = storage.user_language(data, interaction.user.id)
    if not logic.is_guardian(interaction.user, data):
        await interaction.response.send_message(tr(lang, "err.guardian_only"), ephemeral=True)
        return
    path = storage.export_path(interaction.guild.id)
    await interaction.response.send_message(
        tr(lang, "msg.backup"),
        file=discord.File(path, filename=f"miraculous_backup_{interaction.guild.id}.json"),
        ephemeral=True,
    )


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("No token found! Put DISCORD_TOKEN in a .env file or as an environment variable.")
    bot.run(TOKEN)
