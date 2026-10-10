# -*- coding: utf-8 -*-
"""
Guardian panel (distribution, configuration, history, settings, crisis) and
the /setup wizard.

Using powers happens elsewhere ("Use Power"); nothing here grants a Guardian
extra RP powers. Views here are short-lived (not persistent); the Guardian
Panel is opened from the main panel's "Guardian Panel" button.
"""

import secrets
import time

import discord
from discord import ui

import logic
import storage
from i18n import tr
from miraculous_data import GUARDIAN_ROLE_NAME, MIRACULOUS


def _options(names: list) -> list:
    return [
        discord.SelectOption(
            label=f"{n} ({MIRACULOUS[n]['kwami']})", value=n,
            emoji=MIRACULOUS[n]["emoji"], description=MIRACULOUS[n]["concept"])
        for n in names
    ]


def _audit(text: str) -> discord.Embed:
    return discord.Embed(description=text, color=logic.GREY)


def _snap(data: dict) -> dict:
    return {"rp_log_channel_id": data["rp_log_channel_id"], "log_channel_id": data["log_channel_id"]}


# ------------------------------------------------------------------ #
#  The panel
# ------------------------------------------------------------------ #

class GuardianPanelView(ui.View):
    def __init__(self, lang: str):
        super().__init__(timeout=300)
        self.lang = lang
        labels = {
            self.give_button: "lbl.g_give", self.take_button: "lbl.g_take",
            self.add_guardian_button: "lbl.g_add", self.remove_guardian_button: "lbl.g_remove",
            self.log_button: "lbl.g_log", self.rp_log_button: "lbl.g_rplog", self.restrict_button: "lbl.g_restrict",
            self.history_button: "lbl.g_history", self.settings_button: "lbl.g_settings", self.crisis_button: "lbl.g_crisis",
        }
        for item, key in labels.items():
            item.label = tr(lang, key)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        data = storage.load_guild(interaction.guild.id)
        if not logic.is_guardian(interaction.user, data):
            await interaction.response.send_message(tr(self.lang, "err.guardian_only"), ephemeral=True)
            return False
        return True

    # ---- row 0 ------------------------------------------------------ #
    @ui.button(label="Give", emoji="🎁", style=discord.ButtonStyle.success, row=0)
    async def give_button(self, interaction: discord.Interaction, button: ui.Button):
        data = storage.load_guild(interaction.guild.id)
        available = [n for n in MIRACULOUS if n not in data["holders"]]
        if not available:
            await interaction.response.send_message(tr(self.lang, "err.all_held"), ephemeral=True)
            return
        await interaction.response.send_message(
            tr(self.lang, "msg.give_choose"), view=GiveView(self.lang, available), ephemeral=True)

    @ui.button(label="Take", emoji="📤", style=discord.ButtonStyle.secondary, row=0)
    async def take_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            tr(self.lang, "msg.take_choose"), view=_OneView(TakeMemberSelect(self.lang)), ephemeral=True)

    @ui.button(label="Add Guardian", emoji="👑", style=discord.ButtonStyle.secondary, row=0)
    async def add_guardian_button(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(tr(self.lang, "err.admin_only"), ephemeral=True)
            return
        await interaction.response.send_message(
            tr(self.lang, "msg.guardian_add_choose"), view=GuardianChangeView(self.lang, add=True), ephemeral=True)

    @ui.button(label="Remove Guardian", emoji="🗑️", style=discord.ButtonStyle.secondary, row=0)
    async def remove_guardian_button(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(tr(self.lang, "err.admin_only"), ephemeral=True)
            return
        data = storage.load_guild(interaction.guild.id)
        if not data["guardian_ids"]:
            await interaction.response.send_message(
                tr(self.lang, "err.no_direct_guardians", role=GUARDIAN_ROLE_NAME), ephemeral=True)
            return
        await interaction.response.send_message(
            tr(self.lang, "msg.guardian_remove_choose"), view=GuardianChangeView(self.lang, add=False), ephemeral=True)

    # ---- row 1 ------------------------------------------------------ #
    @ui.button(label="Log Channel", emoji="🧾", style=discord.ButtonStyle.secondary, row=1)
    async def log_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            tr(self.lang, "msg.log_choose"), view=_OneView(ChannelSetSelect(self.lang, "log_channel_id", "msg.log_set")),
            ephemeral=True)

    @ui.button(label="RP Log Channel", emoji="📖", style=discord.ButtonStyle.secondary, row=1)
    async def rp_log_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            tr(self.lang, "msg.rplog_choose"),
            view=_OneView(ChannelSetSelect(self.lang, "rp_log_channel_id", "msg.rplog_set")), ephemeral=True)

    @ui.button(label="RP Channels", emoji="🔒", style=discord.ButtonStyle.secondary, row=1)
    async def restrict_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            tr(self.lang, "msg.restrict_choose"), view=RestrictChannelsView(self.lang), ephemeral=True)

    # ---- row 2 ------------------------------------------------------ #
    @ui.button(label="History", emoji="📜", style=discord.ButtonStyle.primary, row=2)
    async def history_button(self, interaction: discord.Interaction, button: ui.Button):
        data = storage.load_guild(interaction.guild.id)
        await interaction.response.send_message(
            embed=logic.history_embed(interaction.guild, data, self.lang), ephemeral=True)

    @ui.button(label="Settings", emoji="⚙️", style=discord.ButtonStyle.primary, row=2)
    async def settings_button(self, interaction: discord.Interaction, button: ui.Button):
        data = storage.load_guild(interaction.guild.id)
        view = SettingsView(self.lang, data)
        await interaction.response.send_message(embed=view.embed(data), view=view, ephemeral=True)

    @ui.button(label="Start Crisis", emoji="🚨", style=discord.ButtonStyle.danger, row=2)
    async def crisis_button(self, interaction: discord.Interaction, button: ui.Button):
        data = storage.load_guild(interaction.guild.id)
        if data["crisis"]:
            await interaction.response.send_message(tr(self.lang, "err.crisis_active"), ephemeral=True)
            return
        await interaction.response.send_modal(CrisisModal(self.lang))


class _OneView(ui.View):
    def __init__(self, item: ui.Item, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.add_item(item)


# ------------------------------------------------------------------ #
#  Give (assigns directly; the member gets the Kwami introduction by DM)
# ------------------------------------------------------------------ #

class GiveView(ui.View):
    def __init__(self, lang: str, available: list):
        super().__init__(timeout=300)
        self.lang = lang
        self.miraculous = None
        self.member = None
        miraculous_select = ui.Select(placeholder=tr(lang, "lbl.choose_miraculous"), options=_options(available),
                                      min_values=1, max_values=1)
        member_select = ui.UserSelect(placeholder=tr(lang, "lbl.choose_member"), min_values=1, max_values=1)
        miraculous_select.callback = self._pick_miraculous
        member_select.callback = self._pick_member
        self._ms, self._us = miraculous_select, member_select
        self.add_item(miraculous_select)
        self.add_item(member_select)
        self.confirm.label = tr(lang, "lbl.confirm")

    async def _pick_miraculous(self, interaction: discord.Interaction):
        self.miraculous = self._ms.values[0]
        await interaction.response.defer()

    async def _pick_member(self, interaction: discord.Interaction):
        self.member = self._us.values[0]
        await interaction.response.defer()

    @ui.button(label="Confirm", style=discord.ButtonStyle.success, row=2)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        if not self.miraculous or not self.member:
            await interaction.response.send_message(tr(self.lang, "err.pick_both"), ephemeral=True)
            return
        name, member = self.miraculous, self.member
        info = MIRACULOUS[name]
        err = first = snap = plang = mlang = None
        async with storage.edit(interaction.guild.id) as data:
            if member.bot:
                err = tr(self.lang, "err.target_bot")
                raise storage.Abort
            if name in data["holders"]:
                err = tr(self.lang, "err.already_held", name=name)
                raise storage.Abort
            data["holders"][name] = member.id
            storage.record_history(data, name, member.id, "given", by=interaction.user.id)
            storage.touch(data, member.id)
            storage.kwami(data, name)["tired"] = False
            first = storage.mark_welcomed(data, member.id)
            snap = _snap(data)
            plang = storage.public_language(data)
            mlang = storage.user_language(data, member.id)

        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        await interaction.response.edit_message(
            content=tr(self.lang, "msg.gave", emoji=info["emoji"], name=name, kwami=info["kwami"], member=member.mention),
            view=None)
        await interaction.channel.send(
            tr(plang, "msg.gave_public", emoji=info["emoji"], guardian=interaction.user.mention, name=name,
               kwami=info["kwami"], member=member.mention))
        await logic.log_action(interaction.guild, snap, _audit(
            tr(plang, "msg.audit_give", guardian=interaction.user.mention, name=name, member=member.mention)))
        await logic.send_kwami_dm(member, name, mlang, first)


# ------------------------------------------------------------------ #
#  Take (a member may hold several: pick the member, then the Miraculous)
# ------------------------------------------------------------------ #

class TakeMemberSelect(ui.UserSelect):
    def __init__(self, lang: str):
        super().__init__(placeholder=tr(lang, "lbl.choose_member"), min_values=1, max_values=1)
        self.lang = lang

    async def callback(self, interaction: discord.Interaction):
        member = self.values[0]
        data = storage.load_guild(interaction.guild.id)
        held = storage.find_member_miraculous_list(data, member.id)
        if not held:
            await interaction.response.edit_message(
                content=tr(self.lang, "err.member_holds_none", member=member.mention), view=None)
            return
        await interaction.response.edit_message(
            content=tr(self.lang, "msg.take_which", member=member.mention),
            view=_OneView(TakeMiraculousSelect(self.lang, member, held)))


class TakeMiraculousSelect(ui.Select):
    def __init__(self, lang: str, member: discord.Member, held: list):
        super().__init__(placeholder=tr(lang, "lbl.take_ph"), options=_options(held), min_values=1, max_values=1)
        self.lang = lang
        self.member = member

    async def callback(self, interaction: discord.Interaction):
        name = self.values[0]
        err = snap = plang = None
        was_active = False
        async with storage.edit(interaction.guild.id) as data:
            if data["holders"].get(name) != self.member.id:
                err = tr(self.lang, "err.no_longer_holder")
                raise storage.Abort
            del data["holders"][name]
            # taking a Miraculous also ends it inside any active transformation
            was_active = logic.strip_miraculous(data, self.member.id, name)
            storage.record_history(data, name, self.member.id, "taken", by=interaction.user.id)
            snap = _snap(data)
            plang = storage.public_language(data)

        if err:
            await interaction.response.edit_message(content=err, view=None)
            return
        extra = " " + tr(self.lang, "msg.take_ended_transform") if was_active else ""
        await interaction.response.edit_message(
            content=tr(self.lang, "msg.took", name=name, member=self.member.mention) + extra, view=None)
        await logic.log_action(interaction.guild, snap, _audit(
            tr(plang, "msg.audit_take", guardian=interaction.user.mention, name=name, member=self.member.mention)))


# ------------------------------------------------------------------ #
#  Guardians
# ------------------------------------------------------------------ #

class GuardianChangeView(ui.View):
    def __init__(self, lang: str, add: bool):
        super().__init__(timeout=300)
        self.lang = lang
        self.add = add
        self.member = None
        select = ui.UserSelect(placeholder=tr(lang, "lbl.choose_member"), min_values=1, max_values=1)
        select.callback = self._pick
        self._select = select
        self.add_item(select)
        self.confirm.label = tr(lang, "lbl.confirm")
        self.confirm.style = discord.ButtonStyle.success if add else discord.ButtonStyle.danger

    async def _pick(self, interaction: discord.Interaction):
        self.member = self._select.values[0]
        await interaction.response.defer()

    @ui.button(label="Confirm", style=discord.ButtonStyle.success, row=1)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        if not self.member:
            await interaction.response.send_message(tr(self.lang, "err.pick_member"), ephemeral=True)
            return
        err = snap = plang = None
        async with storage.edit(interaction.guild.id) as data:
            if self.add:
                storage.add_guardian(data, self.member.id)
            else:
                if self.member.id not in data["guardian_ids"]:
                    err = tr(self.lang, "err.not_direct_guardian", member=self.member.mention)
                    raise storage.Abort
                storage.remove_guardian(data, self.member.id)
            snap = _snap(data)
            plang = storage.public_language(data)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        key_user = "msg.guardian_added" if self.add else "msg.guardian_removed"
        await interaction.response.edit_message(
            content=tr(self.lang, key_user, member=self.member.mention, role=GUARDIAN_ROLE_NAME), view=None)
        await logic.log_action(interaction.guild, snap, _audit(
            tr(plang, "msg.audit_guardian_add" if self.add else "msg.audit_guardian_remove",
               admin=interaction.user.mention, member=self.member.mention)))


# ------------------------------------------------------------------ #
#  Channels
# ------------------------------------------------------------------ #

class ChannelSetSelect(ui.ChannelSelect):
    """Sets one channel id field of the guild data (audit log / RP log)."""

    def __init__(self, lang: str, field: str, done_key: str):
        super().__init__(placeholder=tr(lang, "lbl.choose_channel"), channel_types=[discord.ChannelType.text],
                         min_values=1, max_values=1)
        self.lang = lang
        self.field = field
        self.done_key = done_key

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        async with storage.edit(interaction.guild.id) as data:
            data[self.field] = channel.id
        await interaction.response.edit_message(content=tr(self.lang, self.done_key, channel=channel.mention), view=None)


class RestrictChannelsView(ui.View):
    def __init__(self, lang: str):
        super().__init__(timeout=180)
        self.lang = lang
        select = ui.ChannelSelect(placeholder=tr(lang, "lbl.restrict_ph"), channel_types=[discord.ChannelType.text],
                                  min_values=1, max_values=25)
        select.callback = self._set
        self._select = select
        self.add_item(select)
        self.clear.label = tr(lang, "lbl.allow_everywhere")

    async def _set(self, interaction: discord.Interaction):
        chans = self._select.values
        async with storage.edit(interaction.guild.id) as data:
            data["allowed_channels"] = [c.id for c in chans]
        await interaction.response.edit_message(
            content=tr(self.lang, "msg.restricted", channels=", ".join(c.mention for c in chans)), view=None)

    @ui.button(label="Allow Everywhere", style=discord.ButtonStyle.secondary, row=1)
    async def clear(self, interaction: discord.Interaction, button: ui.Button):
        async with storage.edit(interaction.guild.id) as data:
            data["allowed_channels"] = []
        await interaction.response.edit_message(content=tr(self.lang, "msg.unrestricted"), view=None)


# ------------------------------------------------------------------ #
#  Settings (toggles + language + idle reclaim)
# ------------------------------------------------------------------ #

IDLE_CHOICES = [0, 14, 30, 60]

SETTING_TOGGLES = [
    ("theft_enabled", "lbl.s_theft"),
    ("exposure_enabled", "lbl.s_exposure"),
    ("dark_mode_enabled", "lbl.s_dark"),
    ("kwami_food_enabled", "lbl.s_food"),
]


class SettingsView(ui.View):
    def __init__(self, lang: str, data: dict):
        super().__init__(timeout=300)
        self.lang = lang
        self._toggles = []   # [(button, field, label key)]
        for i, (field, label_key) in enumerate(SETTING_TOGGLES):
            btn = ui.Button(style=discord.ButtonStyle.secondary, row=0 if i < 3 else 1)
            btn.callback = self._make_toggle(field)
            self._toggles.append((btn, field, label_key))
            self.add_item(btn)
        lang_btn = ui.Button(emoji="🌐", style=discord.ButtonStyle.secondary, row=1)
        lang_btn.callback = self._toggle_language
        self._lang_btn = lang_btn
        self.add_item(lang_btn)
        idle_btn = ui.Button(emoji="💤", style=discord.ButtonStyle.secondary, row=1)
        idle_btn.callback = self._cycle_idle
        self._idle_btn = idle_btn
        self.add_item(idle_btn)
        self.refresh(data)

    def refresh(self, data: dict) -> None:
        s = data["settings"]
        for btn, field, label_key in self._toggles:
            on = s[field]
            btn.label = f"{tr(self.lang, label_key)}: {tr(self.lang, 'emb.on') if on else tr(self.lang, 'emb.off')}"
            btn.style = discord.ButtonStyle.success if on else discord.ButtonStyle.danger
        self._lang_btn.label = tr(self.lang, "lbl.s_language", lang="العربية" if s["language"] == "ar" else "English")
        days = s["idle_days"]
        self._idle_btn.label = tr(self.lang, "lbl.s_idle", days=days if days else tr(self.lang, "emb.off"))

    def embed(self, data: dict) -> discord.Embed:
        return discord.Embed(title=tr(self.lang, "emb.settings_title"), description=tr(self.lang, "emb.settings_desc"),
                             color=0x95A5A6)

    def _make_toggle(self, field: str):
        async def callback(interaction: discord.Interaction):
            async with storage.edit(interaction.guild.id) as data:
                data["settings"][field] = not data["settings"][field]
            self.refresh(data)
            await interaction.response.edit_message(embed=self.embed(data), view=self)
        return callback

    async def _toggle_language(self, interaction: discord.Interaction):
        async with storage.edit(interaction.guild.id) as data:
            data["settings"]["language"] = "ar" if data["settings"]["language"] == "en" else "en"
        self.refresh(data)
        await interaction.response.edit_message(embed=self.embed(data), view=self)

    async def _cycle_idle(self, interaction: discord.Interaction):
        async with storage.edit(interaction.guild.id) as data:
            cur = data["settings"]["idle_days"]
            nxt = IDLE_CHOICES[(IDLE_CHOICES.index(cur) + 1) % len(IDLE_CHOICES)] if cur in IDLE_CHOICES else 0
            data["settings"]["idle_days"] = nxt
        self.refresh(data)
        await interaction.response.edit_message(embed=self.embed(data), view=self)


# ------------------------------------------------------------------ #
#  Crisis
# ------------------------------------------------------------------ #

class CrisisModal(ui.Modal):
    def __init__(self, lang: str):
        super().__init__(title=tr(lang, "lbl.crisis_modal_title")[:45])
        self.lang = lang
        self.title_input = ui.TextInput(label=tr(lang, "lbl.crisis_name")[:45], max_length=80)
        self.desc_input = ui.TextInput(label=tr(lang, "lbl.crisis_desc")[:45], style=discord.TextStyle.paragraph,
                                       max_length=800)
        self.add_item(self.title_input)
        self.add_item(self.desc_input)

    async def on_submit(self, interaction: discord.Interaction):
        from views import CrisisView  # local import: views imports this module

        err = embed = snap = None
        crisis = None
        async with storage.edit(interaction.guild.id) as data:
            plang = storage.public_language(data)
            if data["crisis"]:
                err = tr(self.lang, "err.crisis_active")
                raise storage.Abort
            crisis = {
                "id": secrets.token_hex(3),
                "title": self.title_input.value.strip(),
                "description": self.desc_input.value.strip(),
                "started_by": interaction.user.id,
                "channel_id": interaction.channel.id,
                "message_id": None,
                "participants": [],
                "started_at": time.time(),
            }
            data["crisis"] = crisis
            embed = logic.crisis_embed(interaction.guild, data, crisis, plang)
            snap = _snap(data)

        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        await interaction.response.send_message(embed=embed, view=CrisisView())
        message = await interaction.original_response()
        async with storage.edit(interaction.guild.id) as data:
            if data["crisis"] and data["crisis"]["id"] == crisis["id"]:
                data["crisis"]["message_id"] = message.id
        await logic.log_rp_event(interaction.guild, snap, embed)


# ------------------------------------------------------------------ #
#  /setup wizard (every field optional; untouched fields are left as-is)
# ------------------------------------------------------------------ #

class SetupWizardView(ui.View):
    def __init__(self, lang: str):
        super().__init__(timeout=300)
        self.lang = lang
        self.rp_channels = self.log_channel = self.rp_log_channel = self.guardian = None
        self._rp = ui.ChannelSelect(placeholder=tr(lang, "lbl.setup_rp"), channel_types=[discord.ChannelType.text],
                                    min_values=0, max_values=25, row=0)
        self._log = ui.ChannelSelect(placeholder=tr(lang, "lbl.setup_log"), channel_types=[discord.ChannelType.text],
                                     min_values=0, max_values=1, row=1)
        self._rplog = ui.ChannelSelect(placeholder=tr(lang, "lbl.setup_rplog"), channel_types=[discord.ChannelType.text],
                                       min_values=0, max_values=1, row=2)
        self._g = ui.UserSelect(placeholder=tr(lang, "lbl.setup_guardian"), min_values=0, max_values=1, row=3)
        for item, attr in ((self._rp, "rp_channels"), (self._log, "log_channel"),
                           (self._rplog, "rp_log_channel"), (self._g, "guardian")):
            item.callback = self._make_cb(item, attr)
            self.add_item(item)
        self.finish.label = tr(lang, "lbl.finish_setup")

    def _make_cb(self, item, attr):
        async def cb(interaction: discord.Interaction):
            vals = list(item.values)
            setattr(self, attr, vals if attr == "rp_channels" else (vals[0] if vals else None))
            await interaction.response.defer()
        return cb

    @ui.button(label="Finish Setup", emoji="✅", style=discord.ButtonStyle.success, row=4)
    async def finish(self, interaction: discord.Interaction, button: ui.Button):
        summary = []
        async with storage.edit(interaction.guild.id) as data:
            if self.rp_channels:
                data["allowed_channels"] = [c.id for c in self.rp_channels]
                summary.append(tr(self.lang, "msg.setup_rp", channels=", ".join(c.mention for c in self.rp_channels)))
            if self.log_channel:
                data["log_channel_id"] = self.log_channel.id
                summary.append(tr(self.lang, "msg.setup_log", channel=self.log_channel.mention))
            if self.rp_log_channel:
                data["rp_log_channel_id"] = self.rp_log_channel.id
                summary.append(tr(self.lang, "msg.setup_rplog", channel=self.rp_log_channel.mention))
            if self.guardian:
                storage.add_guardian(data, self.guardian.id)
                summary.append(tr(self.lang, "msg.setup_guardian", member=self.guardian.mention))
        text = ("✅ " + tr(self.lang, "msg.setup_done") + "\n" + "\n".join(f"• {s}" for s in summary)
                if summary else tr(self.lang, "msg.setup_nothing"))
        await interaction.response.edit_message(content=text, embed=None, view=None)
