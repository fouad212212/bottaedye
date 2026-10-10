# -*- coding: utf-8 -*-
"""
Everything a member can click: the permanent control panel and the flows it
opens (transform, powers, Unify, the Ladybug cure, duels, theft, feeding,
requests, identity exposure, crisis join/end).

Conventions
-----------
* Mutations happen inside ``async with storage.edit(guild_id) as data`` and
  Discord messages are sent AFTER the block (never hold the lock while
  waiting on Discord).
* Errors go to the clicking member in THEIR language (ephemeral). Public
  announcements use the SERVER language.
* Persistent views (survive restarts): MainPanelView, RequestDecisionView,
  ExposureView, CrisisView - registered in main.py.
"""

import random
import time

import discord
from discord import ui

import guardian
import logic
import storage
from i18n import tr
from miraculous_data import (
    DUEL_ACTIVE_TIMEOUT,
    DUEL_INVITE_TIMEOUT,
    MIRACULOUS,
    REQUIRE_LUCKY_CHARM_FOR_CURE,
    STEAL_COOLDOWN_SECONDS,
    STEAL_RESIST_BONUS,
    STEAL_RESIST_WINDOW,
    UNIFY_ADD_PHRASE,
)


# ------------------------------------------------------------------ #
#  Shared helpers
# ------------------------------------------------------------------ #

def miraculous_options(names: list) -> list:
    return [
        discord.SelectOption(
            label=f"{name} ({MIRACULOUS[name]['kwami']})",
            value=name,
            emoji=MIRACULOUS[name]["emoji"],
            description=MIRACULOUS[name]["concept"],
        )
        for name in names
    ]


def _snap(data: dict) -> dict:
    """The few channel ids needed to log after the lock is released."""
    return {"rp_log_channel_id": data["rp_log_channel_id"], "log_channel_id": data["log_channel_id"]}


async def _announce(interaction: discord.Interaction, embed: discord.Embed, snap: dict, content: str = None) -> None:
    """Public message in the current channel + copy to the RP log."""
    await interaction.response.send_message(content=content, embed=embed)
    await logic.log_rp_event(interaction.guild, snap, embed)


# ------------------------------------------------------------------ #
#  Hero name
# ------------------------------------------------------------------ #

class HeroNameModal(ui.Modal):
    def __init__(self, lang: str, current: str = None):
        super().__init__(title=tr(lang, "lbl.hero_name_title")[:45])
        self.lang = lang
        self.name_input = ui.TextInput(
            label=tr(lang, "lbl.hero_name_label")[:45], default=current, min_length=2, max_length=32, required=True,
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        name = self.name_input.value.strip()
        async with storage.edit(interaction.guild.id) as data:
            storage.set_hero_name(data, interaction.user.id, name)
            entry = logic.get_active(data, interaction.user.id)
            if entry:
                entry["hero_name"] = name
            storage.touch(data, interaction.user.id)
        await interaction.response.send_message(tr(self.lang, "msg.hero_name_set", name=name), ephemeral=True)


class FirstTimeHeroNameModal(ui.Modal):
    """Shown the first time someone transforms without a hero name yet."""

    def __init__(self, lang: str, names: list, add_to_active: bool):
        super().__init__(title=tr(lang, "lbl.first_hero_title")[:45])
        self.names = names
        self.add_to_active = add_to_active
        self.name_input = ui.TextInput(label=tr(lang, "lbl.hero_name_label")[:45], min_length=2, max_length=32)
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        await perform_transform(interaction, self.names, self.name_input.value.strip(), self.add_to_active)


# ------------------------------------------------------------------ #
#  Transform / Unify
# ------------------------------------------------------------------ #

async def begin_transform(interaction: discord.Interaction, names: list, add_to_active: bool = False):
    data = storage.load_guild(interaction.guild.id)
    hero_name = storage.get_hero_name(data, interaction.user.id)
    if hero_name is None:
        await interaction.response.send_modal(
            FirstTimeHeroNameModal(storage.user_language(data, interaction.user.id), names, add_to_active))
        return
    await perform_transform(interaction, names, hero_name, add_to_active)


async def perform_transform(interaction: discord.Interaction, names: list, hero_name: str, add_to_active: bool):
    err = embed = snap = None
    async with storage.edit(interaction.guild.id) as data:
        ulang = storage.user_language(data, interaction.user.id)
        plang = storage.public_language(data)
        held = storage.find_member_miraculous_list(data, interaction.user.id)
        entry = logic.get_active(data, interaction.user.id)

        if any(n not in held for n in names):
            err = tr(ulang, "err.not_held")
            raise storage.Abort
        if entry and not add_to_active:
            err = tr(ulang, "err.already_transformed")
            raise storage.Abort
        if add_to_active and not entry:
            add_to_active = False
        if add_to_active:
            names = [n for n in names if n not in entry["miraculous"]]
            if not names:
                err = tr(ulang, "err.nothing_to_add")
                raise storage.Abort

        tired = logic.tired_blockers(data, names)
        if tired:
            first = tired[0]
            err = tr(ulang, "err.kwami_tired", kwami=MIRACULOUS[first]["kwami"],
                     food=logic.food_of(first) or tr(ulang, "emb.any_snack"))
            raise storage.Abort

        dark = storage.is_dark(data, interaction.user.id) and data["settings"]["dark_mode_enabled"]
        embed = logic.do_transform(data, interaction.user, names, hero_name, interaction.channel.id,
                                   add_to_active=add_to_active, dark=dark, lang=plang)
        snap = _snap(data)

    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return
    await _announce(interaction, embed, snap)


class TransformSelect(ui.Select):
    def __init__(self, lang: str, held: list):
        super().__init__(placeholder=tr(lang, "lbl.choose_miraculous"), options=miraculous_options(held),
                         min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        await begin_transform(interaction, [self.values[0]])


class UnifySelect(ui.Select):
    def __init__(self, lang: str, candidates: list, add_to_active: bool = False):
        super().__init__(
            placeholder=tr(lang, "lbl.unify_add_ph" if add_to_active else "lbl.unify_ph"),
            options=miraculous_options(candidates),
            min_values=1 if add_to_active else 2,
            max_values=len(candidates),
        )
        self.add_to_active = add_to_active

    async def callback(self, interaction: discord.Interaction):
        await begin_transform(interaction, list(self.values), add_to_active=self.add_to_active)


class OneSelectView(ui.View):
    def __init__(self, select: ui.Select, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.add_item(select)


# ------------------------------------------------------------------ #
#  De-transform (single / Reverse Morphosis / Divide)
# ------------------------------------------------------------------ #

async def do_detransform(interaction: discord.Interaction, release_names: list, from_menu: bool):
    err = embed = snap = None
    async with storage.edit(interaction.guild.id) as data:
        ulang = storage.user_language(data, interaction.user.id)
        plang = storage.public_language(data)
        entry = logic.get_active(data, interaction.user.id)
        if not entry:
            err = tr(ulang, "err.not_transformed")
            raise storage.Abort
        release = [n for n in entry["miraculous"] if n in release_names]
        if not release:
            err = tr(ulang, "err.nothing_to_release")
            raise storage.Abort
        embed = logic.detransform_embed(interaction.user, storage.is_secret(data, interaction.user.id),
                                        entry, release, plang)
        logic.apply_detransform(data, interaction.user.id, release)
        storage.touch(data, interaction.user.id)
        snap = _snap(data)

    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return
    if from_menu:
        await interaction.response.edit_message(content="💫", embed=None, view=None)
        await interaction.channel.send(embed=embed)
        await logic.log_rp_event(interaction.guild, snap, embed)
    else:
        await _announce(interaction, embed, snap)


class DetransformSelect(ui.Select):
    def __init__(self, lang: str, active_names: list):
        super().__init__(placeholder=tr(lang, "lbl.release_ph"), options=miraculous_options(active_names),
                         min_values=1, max_values=len(active_names))

    async def callback(self, interaction: discord.Interaction):
        await do_detransform(interaction, list(self.values), from_menu=True)


class DetransformChooseView(ui.View):
    def __init__(self, lang: str, active_names: list):
        super().__init__(timeout=180)
        self.active_names = active_names
        self.add_item(DetransformSelect(lang, active_names))
        btn = ui.Button(label=tr(lang, "lbl.release_all"), emoji="💫", style=discord.ButtonStyle.danger, row=1)
        btn.callback = self._release_all
        self.add_item(btn)

    async def _release_all(self, interaction: discord.Interaction):
        await do_detransform(interaction, self.active_names, from_menu=True)


# ------------------------------------------------------------------ #
#  Use Power
# ------------------------------------------------------------------ #

async def finish_power(interaction: discord.Interaction, name: str, hero_name: str, *,
                       detail: str = None, target=None, grant: bool = False):
    """The one place a signature power is resolved and announced."""
    info = MIRACULOUS[name]
    err = embed = snap = None
    async with storage.edit(interaction.guild.id) as data:
        ulang = storage.user_language(data, interaction.user.id)
        plang = storage.public_language(data)
        entry = logic.get_active(data, interaction.user.id)

        if not entry or name not in entry["miraculous"]:
            err = tr(ulang, "err.not_transformed_with", name=name)
            raise storage.Abort
        if data["settings"]["kwami_food_enabled"] and storage.is_tired(data, name):
            err = tr(ulang, "err.power_tired", kwami=info["kwami"],
                     food=logic.food_of(name) or tr(ulang, "emb.any_snack"))
            raise storage.Abort
        if target is not None and getattr(target, "bot", False):
            err = tr(ulang, "err.target_bot")
            raise storage.Abort
        if grant and target is not None and target.id == interaction.user.id:
            err = tr(ulang, "err.cant_target_self")
            raise storage.Abort

        hero_name = entry["hero_name"]
        who = logic.actor_line(storage.is_secret(data, interaction.user.id), interaction.user, hero_name, plang)
        cat = info["use_category"]
        notes = []

        if grant:
            key = "emb.akumatize" if name == "Butterfly" else "emb.amok"
            desc = tr(plang, key, who=who, target=target.mention, power=detail)
            data["granted_powers"][str(target.id)] = {
                "power": detail[:300],
                "source": "Akumatize" if name == "Butterfly" else "Amok",
                "granted_by": interaction.user.id,
                "since": time.time(),
            }
        elif cat == "no_input":
            desc = tr(plang, "emb.power_plain", who=who, move=info["signature_move"])
        elif cat == "text_input":
            desc = f"{who}: {detail}"
        else:  # target_member
            desc = tr(plang, "emb.power_on", who=who, move=info["signature_move"], target=target.mention)

        if name == "Ladybug":
            entry["lucky_charm"] = {"object": (detail or "")[:200]}
            notes.append(tr(plang, "emb.lucky_ready"))
        if info.get("leaves_damage"):
            text = detail if detail else f"{info['signature_move']} → {target.mention}"
            storage.add_damage(data, interaction.user.id, hero_name, name, text)

        if logic.register_power_use(data, interaction.user.id, name):
            notes.append(tr(plang, "emb.countdown", minutes=5))
        if data["settings"]["kwami_food_enabled"]:
            notes.append(tr(plang, "emb.kwami_exhausted", kwami=info["kwami"]))

        embed = discord.Embed(
            title=f"{info['emoji']} {hero_name} — {info['signature_move']}!",
            description=desc, color=info["color"],
        )
        if notes:
            embed.set_footer(text=" · ".join(notes))
        snap = _snap(data)

    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return
    await _announce(interaction, embed, snap)


class PowerTextModal(ui.Modal):
    def __init__(self, lang: str, name: str, hero_name: str):
        info = MIRACULOUS[name]
        super().__init__(title=f"{info['signature_move']}"[:45])
        self.name = name
        self.hero_name = hero_name
        self.text = ui.TextInput(label=info["use_prompt"][:45], style=discord.TextStyle.paragraph,
                                 max_length=300)
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction):
        await finish_power(interaction, self.name, self.hero_name, detail=self.text.value)


class GrantPowerModal(ui.Modal):
    """Akumatize / Amok: describe the power being given to the target."""

    def __init__(self, lang: str, name: str, hero_name: str, target):
        info = MIRACULOUS[name]
        super().__init__(title=f"{info['signature_move']}"[:45])
        self.name = name
        self.hero_name = hero_name
        self.target = target
        self.text = ui.TextInput(label=tr(lang, "lbl.grant_power_label")[:45],
                                 style=discord.TextStyle.paragraph, max_length=300)
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction):
        await finish_power(interaction, self.name, self.hero_name,
                           detail=self.text.value, target=self.target, grant=True)


class PowerTargetSelect(ui.UserSelect):
    def __init__(self, lang: str, name: str, hero_name: str):
        super().__init__(placeholder=MIRACULOUS[name]["use_prompt"][:150], min_values=1, max_values=1)
        self.lang = lang
        self.name = name
        self.hero_name = hero_name

    async def callback(self, interaction: discord.Interaction):
        target = self.values[0]
        if MIRACULOUS[self.name]["use_category"] == "target_member_text":
            await interaction.response.send_modal(GrantPowerModal(self.lang, self.name, self.hero_name, target))
        else:
            await finish_power(interaction, self.name, self.hero_name, target=target)


async def dispatch_power(interaction: discord.Interaction, name: str, hero_name: str, lang: str):
    cat = MIRACULOUS[name]["use_category"]
    if cat == "no_input":
        await finish_power(interaction, name, hero_name)
    elif cat == "text_input":
        await interaction.response.send_modal(PowerTextModal(lang, name, hero_name))
    else:
        await interaction.response.send_message(
            MIRACULOUS[name]["use_prompt"], view=OneSelectView(PowerTargetSelect(lang, name, hero_name)),
            ephemeral=True)


class PowerChooseSelect(ui.Select):
    def __init__(self, lang: str, hero_name: str, names: list):
        super().__init__(placeholder=tr(lang, "lbl.choose_power_ph"), options=miraculous_options(names),
                         min_values=1, max_values=1)
        self.lang = lang
        self.hero_name = hero_name

    async def callback(self, interaction: discord.Interaction):
        await dispatch_power(interaction, self.values[0], self.hero_name, self.lang)


# ------------------------------------------------------------------ #
#  Duel: challenge -> accept -> yield / settle by fate
# ------------------------------------------------------------------ #

class DuelOpponentSelect(ui.UserSelect):
    def __init__(self, lang: str):
        super().__init__(placeholder=tr(lang, "lbl.duel_opponent_ph"), min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        opponent = self.values[0]
        data = storage.load_guild(interaction.guild.id)
        lang = storage.user_language(data, interaction.user.id)
        plang = storage.public_language(data)
        me = logic.get_active(data, interaction.user.id)
        other = logic.get_active(data, opponent.id)

        if opponent.id == interaction.user.id or opponent.bot:
            await interaction.response.send_message(tr(lang, "err.duel_bad_opponent"), ephemeral=True)
            return
        if not me:
            await interaction.response.send_message(tr(lang, "err.not_transformed"), ephemeral=True)
            return
        if not other:
            await interaction.response.send_message(tr(lang, "err.duel_opponent_idle"), ephemeral=True)
            return

        who = logic.actor_line(storage.is_secret(data, interaction.user.id), interaction.user, me["hero_name"], plang)
        whom = logic.actor_line(storage.is_secret(data, opponent.id), opponent, other["hero_name"], plang)
        embed = discord.Embed(title=tr(plang, "emb.duel_challenge_title"),
                              description=tr(plang, "emb.duel_challenge", who=who, whom=whom), color=0xE67E22)
        view = DuelInviteView(plang, interaction.user, opponent)
        await interaction.response.send_message(content=opponent.mention, embed=embed, view=view)
        view.message = await interaction.original_response()


class DuelInviteView(ui.View):
    def __init__(self, lang: str, challenger: discord.Member, opponent: discord.Member):
        super().__init__(timeout=DUEL_INVITE_TIMEOUT)
        self.lang = lang
        self.challenger = challenger
        self.opponent = opponent
        self.message = None
        self.accept.label = tr(lang, "lbl.accept")
        self.decline.label = tr(lang, "lbl.decline")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message(tr(self.lang, "err.not_your_duel"), ephemeral=True)
            return False
        return True

    @ui.button(label="Accept", emoji="⚔️", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(
            title=tr(self.lang, "emb.duel_on_title"),
            description=tr(self.lang, "emb.duel_on", a=self.challenger.mention, b=self.opponent.mention),
            color=0xE67E22,
        )
        view = DuelActiveView(self.lang, self.challenger, self.opponent)
        await interaction.response.edit_message(content=None, embed=embed, view=view)
        view.message = interaction.message
        self.stop()

    @ui.button(label="Decline", emoji="🏳️", style=discord.ButtonStyle.secondary)
    async def decline(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.edit_message(
            content=None, view=None,
            embed=discord.Embed(description=tr(self.lang, "emb.duel_declined", b=self.opponent.mention), color=logic.GREY))
        self.stop()

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content=None, view=None, embed=discord.Embed(
                    description=tr(self.lang, "emb.duel_no_answer", b=self.opponent.mention), color=logic.GREY))
            except discord.HTTPException:
                pass


class DuelActiveView(ui.View):
    """Players role-play the fight; whenever they like either one yields, or
    either one asks fate (a weighted d100 roll) to decide."""

    def __init__(self, lang: str, a: discord.Member, b: discord.Member):
        super().__init__(timeout=DUEL_ACTIVE_TIMEOUT)
        self.lang = lang
        self.a = a
        self.b = b
        self.message = None
        self.finished = False
        self.yield_btn.label = tr(lang, "lbl.yield")
        self.fate_btn.label = tr(lang, "lbl.fate")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in (self.a.id, self.b.id):
            await interaction.response.send_message(tr(self.lang, "err.not_your_duel"), ephemeral=True)
            return False
        return True

    async def _resolve(self, interaction: discord.Interaction, winner, loser, rolls=None):
        if self.finished:
            await interaction.response.send_message(tr(self.lang, "err.duel_over"), ephemeral=True)
            return
        self.finished = True
        freed = snap = None
        async with storage.edit(interaction.guild.id) as data:
            storage.record_duel_result(data, winner.id, loser.id)
            storage.touch(data, winner.id)
            storage.touch(data, loser.id)
            freed = logic.free_from_akuma(data, loser.id)
            snap = _snap(data)

        lines = [tr(self.lang, "emb.duel_winner", winner=winner.mention, loser=loser.mention)]
        if rolls:
            lines.append(tr(self.lang, "emb.duel_rolls", a=self.a.mention, ra=rolls[0], b=self.b.mention, rb=rolls[1]))
        embed = discord.Embed(title=tr(self.lang, "emb.duel_result_title"), description="\n".join(lines), color=0xF1C40F)
        await interaction.response.edit_message(embed=embed, view=None)
        await logic.log_rp_event(interaction.guild, snap, embed)
        self.stop()
        if freed:
            free_embed = discord.Embed(description=tr(self.lang, "emb.duel_akuma_freed", loser=loser.mention), color=0x2ECC71)
            await interaction.followup.send(embed=free_embed)

    @ui.button(label="Yield", emoji="🏳️", style=discord.ButtonStyle.secondary)
    async def yield_btn(self, interaction: discord.Interaction, button: ui.Button):
        other = self.b if interaction.user.id == self.a.id else self.a
        await self._resolve(interaction, other, interaction.user)

    @ui.button(label="Let fate decide", emoji="🎲", style=discord.ButtonStyle.primary)
    async def fate_btn(self, interaction: discord.Interaction, button: ui.Button):
        if self.finished:
            await interaction.response.send_message(tr(self.lang, "err.duel_over"), ephemeral=True)
            return
        data = storage.load_guild(interaction.guild.id)
        ra = rb = 0
        for _ in range(6):
            ra = logic.combat_score(data, self.a.id)
            rb = logic.combat_score(data, self.b.id)
            if ra != rb:
                break
        winner, loser = (self.a, self.b) if ra >= rb else (self.b, self.a)
        await self._resolve(interaction, winner, loser, rolls=(ra, rb))

    async def on_timeout(self):
        if self.message and not self.finished:
            try:
                await self.message.edit(view=None, embed=discord.Embed(
                    description=tr(self.lang, "emb.duel_faded", a=self.a.mention, b=self.b.mention), color=logic.GREY))
            except discord.HTTPException:
                pass


# ------------------------------------------------------------------ #
#  Theft: attempt -> victim may resist -> weighted roll
# ------------------------------------------------------------------ #

class StealTargetSelect(ui.UserSelect):
    def __init__(self, lang: str):
        super().__init__(placeholder=tr(lang, "lbl.steal_target_ph"), min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        target = self.values[0]
        err = embed = snap = victim_mir = None
        async with storage.edit(interaction.guild.id) as data:
            ulang = storage.user_language(data, interaction.user.id)
            plang = storage.public_language(data)
            thief = logic.get_active(data, interaction.user.id)
            now = time.time()
            cd_key = f"steal:{interaction.user.id}"
            held = storage.find_member_miraculous_list(data, target.id)

            if not data["settings"]["theft_enabled"]:
                err = tr(ulang, "err.theft_disabled")
            elif not thief:
                err = tr(ulang, "err.steal_need_transformed")
            elif target.bot or target.id == interaction.user.id:
                err = tr(ulang, "err.steal_bad_target")
            elif not held:
                err = tr(ulang, "err.steal_nothing_to_take", target=target.mention)
            elif data["cooldowns"].get(cd_key, 0) > now:
                err = tr(ulang, "err.steal_cooldown", left=logic.fmt_minutes(data["cooldowns"][cd_key] - now))
            if err:
                raise storage.Abort

            target_entry = logic.get_active(data, target.id)
            pool = [n for n in held if target_entry and n in target_entry["miraculous"]] or held
            victim_mir = random.choice(pool)
            data["cooldowns"][cd_key] = now + STEAL_COOLDOWN_SECONDS
            storage.touch(data, interaction.user.id)

            info = MIRACULOUS[victim_mir]
            who = logic.actor_line(storage.is_secret(data, interaction.user.id), interaction.user, thief["hero_name"], plang)
            embed = discord.Embed(
                title=tr(plang, "emb.steal_title", emoji=info["emoji"]),
                description=tr(plang, "emb.steal_attempt", who=who, target=target.mention, name=victim_mir,
                               secs=STEAL_RESIST_WINDOW),
                color=0x8E44AD,
            )
            snap = _snap(data)

        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        view = StealResistView(plang, interaction.user, target, victim_mir)
        await interaction.response.send_message(content=target.mention, embed=embed, view=view)
        view.message = await interaction.original_response()
        await logic.log_rp_event(interaction.guild, snap, embed)


class StealResistView(ui.View):
    def __init__(self, lang: str, thief: discord.Member, victim: discord.Member, miraculous: str):
        super().__init__(timeout=STEAL_RESIST_WINDOW)
        self.lang = lang
        self.thief = thief
        self.victim = victim
        self.miraculous = miraculous
        self.message = None
        self.done = False
        self.resist.label = tr(lang, "lbl.resist")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.victim.id:
            await interaction.response.send_message(tr(self.lang, "err.only_victim"), ephemeral=True)
            return False
        return True

    @ui.button(label="Resist!", emoji="🛡️", style=discord.ButtonStyle.danger)
    async def resist(self, interaction: discord.Interaction, button: ui.Button):
        await self._resolve(resisted=True, interaction=interaction)

    async def on_timeout(self):
        await self._resolve(resisted=False, interaction=None)

    async def _resolve(self, resisted: bool, interaction):
        if self.done:
            return
        self.done = True
        self.stop()
        if interaction:
            guild = interaction.guild
        elif self.message:
            guild = self.message.guild
        else:
            return
        name = self.miraculous
        info = MIRACULOUS[name]
        success = False
        snap = None
        async with storage.edit(guild.id) as data:
            if data["holders"].get(name) != self.victim.id:
                embed = discord.Embed(description=tr(self.lang, "emb.steal_gone", name=name), color=logic.GREY)
            else:
                t_roll = logic.combat_score(data, self.thief.id)
                d_roll = logic.combat_score(data, self.victim.id, bonus=STEAL_RESIST_BONUS if resisted else 0)
                success = t_roll > d_roll
                if success:
                    data["holders"][name] = self.thief.id
                    logic.strip_miraculous(data, self.victim.id, name)
                    storage.record_history(data, name, self.thief.id, "stolen", by=self.victim.id)
                    storage.bump_stat(data, self.thief.id, "steals")
                    storage.bump_stat(data, self.victim.id, "times_stolen_from")
                    storage.touch(data, self.thief.id)
                key = "emb.steal_success" if success else "emb.steal_fail"
                embed = discord.Embed(
                    title=tr(self.lang, "emb.steal_result_title", emoji=info["emoji"]),
                    description=tr(self.lang, key, thief=self.thief.mention, victim=self.victim.mention, name=name)
                    + "\n" + tr(self.lang, "emb.steal_rolls", t=t_roll, d=d_roll,
                                resisted=tr(self.lang, "emb.yes") if resisted else tr(self.lang, "emb.no")),
                    color=0x8E44AD if success else 0x2ECC71,
                )
            snap = _snap(data)
            audit_lang = storage.public_language(data)

        if interaction:
            await interaction.response.edit_message(content=None, embed=embed, view=None)
        elif self.message:
            try:
                await self.message.edit(content=None, embed=embed, view=None)
            except discord.HTTPException:
                pass
        await logic.log_rp_event(guild, snap, embed)
        if success:
            audit = discord.Embed(
                description=tr(audit_lang, "emb.steal_audit",
                               thief=self.thief.mention, victim=self.victim.mention, name=name),
                color=0x8E44AD)
            await logic.log_action(guild, snap, audit)


# ------------------------------------------------------------------ #
#  Feeding Kwamis
# ------------------------------------------------------------------ #

async def feed_kwami(interaction: discord.Interaction, name: str):
    err = embed = snap = None
    async with storage.edit(interaction.guild.id) as data:
        ulang = storage.user_language(data, interaction.user.id)
        plang = storage.public_language(data)
        info = MIRACULOUS[name]
        if data["holders"].get(name) != interaction.user.id:
            err = tr(ulang, "err.not_held")
            raise storage.Abort
        if not storage.is_tired(data, name):
            err = tr(ulang, "err.kwami_not_hungry", kwami=info["kwami"])
            raise storage.Abort
        storage.set_tired(data, name, False)
        storage.touch(data, interaction.user.id)
        food = logic.food_of(name) or tr(plang, "emb.any_snack")
        who = logic.actor_line(storage.is_secret(data, interaction.user.id), interaction.user,
                               storage.get_hero_name(data, interaction.user.id) or interaction.user.display_name, plang)
        embed = discord.Embed(
            description=tr(plang, "emb.fed", emoji=info["emoji"], who=who, kwami=info["kwami"], food=food),
            color=info["color"])
        snap = _snap(data)

    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return
    await _announce(interaction, embed, snap)


class FeedSelect(ui.Select):
    def __init__(self, lang: str, names: list):
        super().__init__(placeholder=tr(lang, "lbl.feed_ph"), options=miraculous_options(names),
                         min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        await feed_kwami(interaction, self.values[0])


# ------------------------------------------------------------------ #
#  Requests (member asks, a Guardian approves or denies)
# ------------------------------------------------------------------ #

class RequestSelect(ui.Select):
    def __init__(self, lang: str, available: list):
        super().__init__(placeholder=tr(lang, "lbl.request_ph"), options=miraculous_options(available),
                         min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        name = self.values[0]
        info = MIRACULOUS[name]
        err = log_channel_id = None
        async with storage.edit(interaction.guild.id) as data:
            lang = storage.user_language(data, interaction.user.id)
            plang = storage.public_language(data)
            if name in data["holders"]:
                err = tr(lang, "err.just_given", name=name)
                raise storage.Abort
            storage.add_pending_request(data, interaction.user.id, name)
            storage.touch(data, interaction.user.id)
            log_channel_id = data["log_channel_id"]

        if err:
            await interaction.response.edit_message(content=err, view=None)
            return

        channel = interaction.guild.get_channel(log_channel_id) if log_channel_id else None
        if channel is None:
            await interaction.response.edit_message(content=tr(lang, "msg.request_no_log", name=name), view=None)
            return
        embed = discord.Embed(
            title=tr(plang, "emb.request_title", emoji=info["emoji"]),
            description=tr(plang, "emb.request_desc", user=interaction.user.mention, name=name, kwami=info["kwami"]),
            color=info["color"],
        )
        embed.set_footer(text=f"req:{interaction.user.id}:{name}")
        try:
            await channel.send(embed=embed, view=RequestDecisionView())
            await interaction.response.edit_message(content=tr(lang, "msg.request_sent", name=name), view=None)
        except discord.HTTPException:
            await interaction.response.edit_message(content=tr(lang, "msg.request_post_failed", name=name), view=None)


class RequestDecisionView(ui.View):
    """Persistent: the request is encoded in the embed footer
    ("req:<user id>:<Miraculous>"), so approvals still work after a restart."""

    def __init__(self):
        super().__init__(timeout=None)

    @staticmethod
    def _parse(interaction: discord.Interaction):
        try:
            _, uid, name = interaction.message.embeds[0].footer.text.split(":", 2)
            return int(uid), name
        except Exception:
            return None, None

    async def _guard(self, interaction: discord.Interaction):
        data = storage.load_guild(interaction.guild.id)
        lang = storage.user_language(data, interaction.user.id)
        if not logic.is_guardian(interaction.user, data):
            await interaction.response.send_message(tr(lang, "err.guardian_only"), ephemeral=True)
            return None
        return lang

    @ui.button(label="Approve", emoji="✅", style=discord.ButtonStyle.success, custom_id="req:approve")
    async def approve(self, interaction: discord.Interaction, button: ui.Button):
        lang = await self._guard(interaction)
        if lang is None:
            return
        uid, name = self._parse(interaction)
        if uid is None or name not in MIRACULOUS:
            await interaction.response.edit_message(content=tr(lang, "err.request_invalid"), embed=None, view=None)
            return

        msg = None
        first = False
        plang = None
        async with storage.edit(interaction.guild.id) as data:
            plang = storage.public_language(data)
            pending = storage.get_pending_request(data, uid)
            if not pending or pending["miraculous"] != name:
                msg = tr(lang, "err.request_invalid")
                raise storage.Abort
            if name in data["holders"]:
                storage.clear_pending_request(data, uid)
                msg = tr(lang, "err.just_given", name=name)
            else:
                data["holders"][name] = uid
                storage.clear_pending_request(data, uid)
                storage.record_history(data, name, uid, "approved", by=interaction.user.id)
                storage.touch(data, uid)
                first = storage.mark_welcomed(data, uid)
                msg = "OK"
        if msg != "OK":
            await interaction.response.edit_message(content=msg, embed=None, view=None)
            return
        member = interaction.guild.get_member(uid)
        await interaction.response.edit_message(
            content=tr(lang, "msg.request_approved", guardian=interaction.user.mention,
                       user=member.mention if member else f"<@{uid}>", name=name),
            embed=None, view=None)
        if member:
            await logic.send_kwami_dm(member, name, storage.user_language(storage.load_guild(interaction.guild.id), uid), first)

    @ui.button(label="Deny", emoji="❌", style=discord.ButtonStyle.danger, custom_id="req:deny")
    async def deny(self, interaction: discord.Interaction, button: ui.Button):
        lang = await self._guard(interaction)
        if lang is None:
            return
        uid, name = self._parse(interaction)
        if uid is None:
            await interaction.response.edit_message(content=tr(lang, "err.request_invalid"), embed=None, view=None)
            return
        async with storage.edit(interaction.guild.id) as data:
            pending = storage.get_pending_request(data, uid)
            if pending and pending["miraculous"] == name:
                storage.clear_pending_request(data, uid)
        await interaction.response.edit_message(
            content=tr(lang, "msg.request_denied", guardian=interaction.user.mention, name=name), embed=None, view=None)
        member = interaction.guild.get_member(uid)
        if member:
            try:
                await member.send(tr(storage.user_language(storage.load_guild(interaction.guild.id), uid),
                                     "msg.request_denied_dm", name=name))
            except discord.HTTPException:
                pass


# ------------------------------------------------------------------ #
#  Identity exposure (a secret hero's transformation ran out)
# ------------------------------------------------------------------ #

class ExposureView(ui.View):
    """Persistent. Footer: "expose:<user id>"."""

    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="I saw their face!", emoji="👀", style=discord.ButtonStyle.danger, custom_id="expose:saw")
    async def saw(self, interaction: discord.Interaction, button: ui.Button):
        try:
            uid = int(interaction.message.embeds[0].footer.text.split(":", 1)[1])
        except Exception:
            await interaction.response.edit_message(view=None)
            return

        err = hero = None
        async with storage.edit(interaction.guild.id) as data:
            lang = storage.user_language(data, interaction.user.id)
            plang = storage.public_language(data)
            if interaction.user.id == uid:
                err = tr(lang, "err.expose_self")
                raise storage.Abort
            if not data["settings"]["exposure_enabled"] or not storage.is_secret(data, uid):
                err = tr(lang, "err.expose_nothing")
                raise storage.Abort
            storage.set_secret(data, uid, False)
            hero = storage.get_hero_name(data, uid) or "???"
            storage.bump_stat(data, interaction.user.id, "exposed_someone")

        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        embed = discord.Embed(
            title=tr(plang, "emb.exposed_title"),
            description=tr(plang, "emb.exposed_desc", witness=interaction.user.mention, hero=hero, user=f"<@{uid}>"),
            color=0xE74C3C,
        )
        await interaction.response.edit_message(embed=embed, view=None)
        member = interaction.guild.get_member(uid)
        if member:
            try:
                await member.send(tr(storage.user_language(storage.load_guild(interaction.guild.id), uid),
                                     "msg.exposed_dm", witness=interaction.user.display_name))
            except discord.HTTPException:
                pass


# ------------------------------------------------------------------ #
#  Crisis (started by a Guardian; heroes join, a Guardian ends it)
# ------------------------------------------------------------------ #

class CrisisView(ui.View):
    """Persistent. The active crisis lives in data["crisis"]; the buttons only
    work on the message it was posted as."""

    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Join the fight", emoji="🦸", style=discord.ButtonStyle.success, custom_id="crisis:join")
    async def join(self, interaction: discord.Interaction, button: ui.Button):
        err = embed = None
        async with storage.edit(interaction.guild.id) as data:
            lang = storage.user_language(data, interaction.user.id)
            plang = storage.public_language(data)
            crisis = data["crisis"]
            if not crisis or crisis["message_id"] != interaction.message.id:
                err = tr(lang, "err.crisis_over")
                raise storage.Abort
            if not logic.get_active(data, interaction.user.id):
                err = tr(lang, "err.crisis_need_transformed")
                raise storage.Abort
            if interaction.user.id in crisis["participants"]:
                err = tr(lang, "err.crisis_already")
                raise storage.Abort
            crisis["participants"].append(interaction.user.id)
            storage.touch(data, interaction.user.id)
            embed = logic.crisis_embed(interaction.guild, data, crisis, plang)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        await interaction.response.edit_message(embed=embed)

    @ui.button(label="End crisis", emoji="🏁", style=discord.ButtonStyle.secondary, custom_id="crisis:end")
    async def end(self, interaction: discord.Interaction, button: ui.Button):
        err = embed = snap = None
        async with storage.edit(interaction.guild.id) as data:
            lang = storage.user_language(data, interaction.user.id)
            plang = storage.public_language(data)
            if not logic.is_guardian(interaction.user, data):
                err = tr(lang, "err.guardian_only")
                raise storage.Abort
            crisis = data["crisis"]
            if not crisis or crisis["message_id"] != interaction.message.id:
                err = tr(lang, "err.crisis_over")
                raise storage.Abort
            for uid in crisis["participants"]:
                storage.bump_stat(data, uid, "crises")
            embed = logic.crisis_embed(interaction.guild, data, crisis, plang, ended=True)
            data["crisis"] = None
            snap = _snap(data)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        await interaction.response.edit_message(embed=embed, view=None)
        await logic.log_rp_event(interaction.guild, snap, embed)


# ------------------------------------------------------------------ #
#  THE MAIN PANEL (persistent)
# ------------------------------------------------------------------ #

class MainPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    # ---- helpers ---------------------------------------------------- #
    @staticmethod
    def _ctx(interaction: discord.Interaction):
        data = storage.load_guild(interaction.guild.id)
        return data, storage.user_language(data, interaction.user.id)

    # ---- row 0: information & identity ------------------------------ #
    @ui.button(label="Miracle Box", emoji="📦", style=discord.ButtonStyle.primary, custom_id="panel:box", row=0)
    async def box_button(self, interaction: discord.Interaction, button: ui.Button):
        data, lang = self._ctx(interaction)
        await interaction.response.send_message(
            embed=logic.miraculous_box_embed(interaction.guild, data, lang), ephemeral=True)

    @ui.button(label="My Miraculous", emoji="🎴", style=discord.ButtonStyle.primary, custom_id="panel:mine", row=0)
    async def mine_button(self, interaction: discord.Interaction, button: ui.Button):
        data, lang = self._ctx(interaction)
        await interaction.response.send_message(
            embed=logic.my_miraculous_embed(interaction.user, data, lang), ephemeral=True)

    @ui.button(label="Hero Name", emoji="🎭", style=discord.ButtonStyle.secondary, custom_id="panel:heroname", row=0)
    async def hero_name_button(self, interaction: discord.Interaction, button: ui.Button):
        data, lang = self._ctx(interaction)
        await interaction.response.send_modal(
            HeroNameModal(lang, storage.get_hero_name(data, interaction.user.id)))

    @ui.button(label="Secret Identity", emoji="🕵️", style=discord.ButtonStyle.secondary, custom_id="panel:secret", row=0)
    async def secret_button(self, interaction: discord.Interaction, button: ui.Button):
        async with storage.edit(interaction.guild.id) as data:
            lang = storage.user_language(data, interaction.user.id)
            new = not storage.is_secret(data, interaction.user.id)
            storage.set_secret(data, interaction.user.id, new)
        await interaction.response.send_message(tr(lang, "msg.secret_on" if new else "msg.secret_off"), ephemeral=True)

    @ui.button(label="Active Heroes", emoji="🦸", style=discord.ButtonStyle.success, custom_id="panel:active", row=0)
    async def active_button(self, interaction: discord.Interaction, button: ui.Button):
        data, lang = self._ctx(interaction)
        await interaction.response.send_message(
            embed=logic.active_heroes_embed(interaction.guild, data, lang), ephemeral=True)

    # ---- row 1: transformation & powers ----------------------------- #
    @ui.button(label="Transform", emoji="✨", style=discord.ButtonStyle.success, custom_id="panel:transform", row=1)
    async def transform_button(self, interaction: discord.Interaction, button: ui.Button):
        data, lang = self._ctx(interaction)
        if not await logic.ensure_channel_allowed(interaction, data, lang):
            return
        held = storage.find_member_miraculous_list(data, interaction.user.id)
        if not held:
            await interaction.response.send_message(tr(lang, "err.no_miraculous"), ephemeral=True)
            return
        if logic.get_active(data, interaction.user.id):
            await interaction.response.send_message(tr(lang, "err.already_transformed_hint"), ephemeral=True)
            return
        if len(held) == 1:
            await begin_transform(interaction, held)
            return
        await interaction.response.send_message(
            tr(lang, "msg.choose_transform"), view=OneSelectView(TransformSelect(lang, held)), ephemeral=True)

    @ui.button(label="Use Power", emoji="💥", style=discord.ButtonStyle.danger, custom_id="panel:power", row=1)
    async def power_button(self, interaction: discord.Interaction, button: ui.Button):
        data, lang = self._ctx(interaction)
        if not await logic.ensure_channel_allowed(interaction, data, lang):
            return
        active = logic.get_active(data, interaction.user.id)
        if not active:
            await interaction.response.send_message(tr(lang, "err.transform_first"), ephemeral=True)
            return
        names = active["miraculous"]
        if len(names) == 1:
            await dispatch_power(interaction, names[0], active["hero_name"], lang)
            return
        await interaction.response.send_message(
            tr(lang, "msg.choose_power"),
            view=OneSelectView(PowerChooseSelect(lang, active["hero_name"], names)), ephemeral=True)

    @ui.button(label="Unify", emoji="🔗", style=discord.ButtonStyle.success, custom_id="panel:unify", row=1)
    async def unify_button(self, interaction: discord.Interaction, button: ui.Button):
        data, lang = self._ctx(interaction)
        if not await logic.ensure_channel_allowed(interaction, data, lang):
            return
        held = storage.find_member_miraculous_list(data, interaction.user.id)
        active = logic.get_active(data, interaction.user.id)

        if active:  # canon: Unify while transformed adds another Miraculous
            candidates = [n for n in held if n not in active["miraculous"]]
            if not candidates:
                await interaction.response.send_message(tr(lang, "err.unify_nothing_to_add"), ephemeral=True)
                return
            await interaction.response.send_message(
                tr(lang, "msg.unify_add", phrase=UNIFY_ADD_PHRASE),
                view=OneSelectView(UnifySelect(lang, candidates, add_to_active=True)), ephemeral=True)
            return

        if len(held) < 2:
            await interaction.response.send_message(tr(lang, "err.unify_need_two", n=len(held)), ephemeral=True)
            return
        await interaction.response.send_message(
            tr(lang, "msg.unify_new"), view=OneSelectView(UnifySelect(lang, held)), ephemeral=True)

    @ui.button(label="Miraculous Ladybug!", emoji="🐞", style=discord.ButtonStyle.success, custom_id="panel:cure", row=1)
    async def cure_button(self, interaction: discord.Interaction, button: ui.Button):
        err = embed = snap = None
        async with storage.edit(interaction.guild.id) as data:
            lang = storage.user_language(data, interaction.user.id)
            plang = storage.public_language(data)
            if not storage.channel_allowed(data, interaction.channel.id):
                err = tr(lang, "err.channel_restricted",
                         where=", ".join(f"<#{c}>" for c in data["allowed_channels"]))
                raise storage.Abort
            active = logic.get_active(data, interaction.user.id)
            if not active or "Ladybug" not in active["miraculous"]:
                err = tr(lang, "err.cure_not_ladybug")
                raise storage.Abort
            charm = active.get("lucky_charm")
            if REQUIRE_LUCKY_CHARM_FOR_CURE and not charm:
                err = tr(lang, "err.cure_need_charm")
                raise storage.Abort
            akumas = dict(data["granted_powers"])
            damage = list(data["damage_log"])
            if not akumas and not damage:
                err = tr(lang, "err.cure_nothing")
                raise storage.Abort

            data["granted_powers"] = {}
            storage.clear_damage(data)
            active.pop("lucky_charm", None)
            storage.bump_stat(data, interaction.user.id, "cures")
            storage.touch(data, interaction.user.id)

            who = logic.actor_line(storage.is_secret(data, interaction.user.id), interaction.user,
                                   active["hero_name"], plang)
            charm_text = f" (**{logic.clip(charm['object'], 100)}**)" if charm and charm.get("object") else ""
            embed = discord.Embed(
                title="🐞 Miraculous Ladybug!",
                description="**\"Miraculous Ladybug!\"**\n\n" + tr(plang, "emb.cure_desc", who=who, charm=charm_text),
                color=0xFF0000,
            )
            if akumas:
                lines = []
                for uid_str, grant in akumas.items():
                    fate = tr(plang, "emb.cure_akuma" if grant.get("source") == "Akumatize" else "emb.cure_amok")
                    lines.append(f"🦋 <@{uid_str}> — **{logic.clip(grant['power'], 80)}**: {fate}")
                embed.add_field(name=tr(plang, "emb.cure_purified"), value=logic.fit_lines(lines), inline=False)
            lines = [f"{MIRACULOUS[d['miraculous']]['emoji']} **{d['hero_name']}** — {logic.clip(d['text'])}"
                     for d in damage if d.get("miraculous") in MIRACULOUS]
            if lines:
                embed.add_field(name=tr(plang, "emb.cure_repaired"), value=logic.fit_lines(lines), inline=False)
            embed.set_footer(text=tr(plang, "emb.cure_spent"))
            snap = _snap(data)

        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        await _announce(interaction, embed, snap)

    @ui.button(label="Duel", emoji="⚔️", style=discord.ButtonStyle.danger, custom_id="panel:duel", row=1)
    async def duel_button(self, interaction: discord.Interaction, button: ui.Button):
        data, lang = self._ctx(interaction)
        if not await logic.ensure_channel_allowed(interaction, data, lang):
            return
        if not logic.get_active(data, interaction.user.id):
            await interaction.response.send_message(tr(lang, "err.transform_first"), ephemeral=True)
            return
        await interaction.response.send_message(
            tr(lang, "msg.duel_choose"), view=OneSelectView(DuelOpponentSelect(lang)), ephemeral=True)

    # ---- row 2: world actions --------------------------------------- #
    @ui.button(label="Emergency Call", emoji="🚨", style=discord.ButtonStyle.danger, custom_id="panel:emergency", row=2)
    async def emergency_button(self, interaction: discord.Interaction, button: ui.Button):
        data, lang = self._ctx(interaction)
        if not await logic.ensure_channel_allowed(interaction, data, lang):
            return
        active = logic.get_active(data, interaction.user.id)
        if not active:
            await interaction.response.send_message(tr(lang, "err.transform_first"), ephemeral=True)
            return
        plang = storage.public_language(data)
        pings, hidden = [], []
        for uid_str, entry in data["transformed"].items():
            if int(uid_str) == interaction.user.id:
                continue
            if storage.is_secret(data, int(uid_str)):
                hidden.append(f"**{entry['hero_name']}**")   # no ping: it would reveal who they are
            else:
                pings.append(f"<@{uid_str}>")
        who = logic.actor_line(storage.is_secret(data, interaction.user.id), interaction.user, active["hero_name"], plang)
        embed = discord.Embed(title=tr(plang, "emb.emergency_title"),
                              description=tr(plang, "emb.emergency_desc", who=who), color=0xE74C3C)
        if hidden:
            embed.add_field(name=tr(plang, "emb.emergency_secret"), value=", ".join(hidden), inline=False)
        await _announce(interaction, embed, _snap(data), content=" ".join(pings) or None)

    @ui.button(label="Feed Kwami", emoji="🍪", style=discord.ButtonStyle.secondary, custom_id="panel:feed", row=2)
    async def feed_button(self, interaction: discord.Interaction, button: ui.Button):
        data, lang = self._ctx(interaction)
        held = storage.find_member_miraculous_list(data, interaction.user.id)
        if not data["settings"]["kwami_food_enabled"]:
            await interaction.response.send_message(tr(lang, "err.food_disabled"), ephemeral=True)
            return
        if not held:
            await interaction.response.send_message(tr(lang, "err.no_miraculous"), ephemeral=True)
            return
        tired = [n for n in held if storage.is_tired(data, n)]
        if not tired:
            await interaction.response.send_message(tr(lang, "err.all_fed"), ephemeral=True)
            return
        if len(tired) == 1:
            await feed_kwami(interaction, tired[0])
            return
        await interaction.response.send_message(
            tr(lang, "msg.choose_feed"), view=OneSelectView(FeedSelect(lang, tired)), ephemeral=True)

    @ui.button(label="Steal", emoji="🦹", style=discord.ButtonStyle.danger, custom_id="panel:steal", row=2)
    async def steal_button(self, interaction: discord.Interaction, button: ui.Button):
        data, lang = self._ctx(interaction)
        if not await logic.ensure_channel_allowed(interaction, data, lang):
            return
        if not data["settings"]["theft_enabled"]:
            await interaction.response.send_message(tr(lang, "err.theft_disabled"), ephemeral=True)
            return
        if not logic.get_active(data, interaction.user.id):
            await interaction.response.send_message(tr(lang, "err.steal_need_transformed"), ephemeral=True)
            return
        await interaction.response.send_message(
            tr(lang, "msg.steal_choose"), view=OneSelectView(StealTargetSelect(lang)), ephemeral=True)

    @ui.button(label="Request", emoji="🙋", style=discord.ButtonStyle.secondary, custom_id="panel:request", row=2)
    async def request_button(self, interaction: discord.Interaction, button: ui.Button):
        data, lang = self._ctx(interaction)
        available = [n for n in MIRACULOUS if n not in data["holders"]]
        if not available:
            await interaction.response.send_message(tr(lang, "err.all_held"), ephemeral=True)
            return
        await interaction.response.send_message(
            tr(lang, "msg.request_choose"), view=OneSelectView(RequestSelect(lang, available)), ephemeral=True)

    @ui.button(label="De-transform", emoji="💫", style=discord.ButtonStyle.secondary, custom_id="panel:detransform", row=2)
    async def detransform_button(self, interaction: discord.Interaction, button: ui.Button):
        data, lang = self._ctx(interaction)
        active = logic.get_active(data, interaction.user.id)
        if not active:
            await interaction.response.send_message(tr(lang, "err.not_transformed"), ephemeral=True)
            return
        names = active["miraculous"]
        if len(names) == 1:
            await do_detransform(interaction, names, from_menu=False)
            return
        await interaction.response.send_message(
            tr(lang, "msg.detransform_fusion"), view=DetransformChooseView(lang, names), ephemeral=True)

    # ---- row 3: extras ---------------------------------------------- #
    @ui.button(label="Leaderboard", emoji="🏆", style=discord.ButtonStyle.secondary, custom_id="panel:leaderboard", row=3)
    async def leaderboard_button(self, interaction: discord.Interaction, button: ui.Button):
        data, lang = self._ctx(interaction)
        await interaction.response.send_message(
            embed=logic.leaderboard_embed(interaction.guild, data, lang), ephemeral=True)

    @ui.button(label="Dark Side", emoji="🌑", style=discord.ButtonStyle.secondary, custom_id="panel:dark", row=3)
    async def dark_button(self, interaction: discord.Interaction, button: ui.Button):
        err = None
        async with storage.edit(interaction.guild.id) as data:
            lang = storage.user_language(data, interaction.user.id)
            if not data["settings"]["dark_mode_enabled"]:
                err = tr(lang, "err.dark_disabled")
                raise storage.Abort
            new = not storage.is_dark(data, interaction.user.id)
            storage.set_dark(data, interaction.user.id, new)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        await interaction.response.send_message(tr(lang, "msg.dark_on" if new else "msg.dark_off"), ephemeral=True)

    @ui.button(label="Language / اللغة", emoji="🌐", style=discord.ButtonStyle.secondary, custom_id="panel:language", row=3)
    async def language_button(self, interaction: discord.Interaction, button: ui.Button):
        async with storage.edit(interaction.guild.id) as data:
            current = storage.user_language(data, interaction.user.id)
            new = "ar" if current == "en" else "en"
            data["languages"][str(interaction.user.id)] = new
        await interaction.response.send_message(tr(new, "msg.language_set"), ephemeral=True)

    @ui.button(label="Guardian Panel", emoji="👑", style=discord.ButtonStyle.primary, custom_id="panel:guardian", row=3)
    async def guardian_button(self, interaction: discord.Interaction, button: ui.Button):
        data, lang = self._ctx(interaction)
        if not logic.is_guardian(interaction.user, data):
            await interaction.response.send_message(tr(lang, "err.guardian_only"), ephemeral=True)
            return
        await interaction.response.send_message(
            embed=discord.Embed(title=tr(lang, "emb.guardian_title"), description=tr(lang, "emb.guardian_desc"),
                                color=0xF1C40F),
            view=guardian.GuardianPanelView(lang), ephemeral=True)
