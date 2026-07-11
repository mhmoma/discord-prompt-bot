"""新成员欢迎：目的选择 + 私密指引。"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
import discord

_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "onboarding_config.json")
_VIEW_TIMEOUT = None  # 持久 View，重启后在 on_ready 重新注册
_CUSTOM_NOTIFY_COOLDOWN = 86400  # 24h 内同一人只通知管理员一次

_config: dict | None = None
_custom_notify_at: dict[int, float] = {}


def _admin_id() -> int | None:
    raw = os.getenv("ONBOARDING_ADMIN_ID", "1413949409917534268").strip()
    return int(raw) if raw.isdigit() else None


def load_config() -> dict:
    global _config
    if _config is not None:
        return _config
    with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
        _config = json.load(f)
    return _config


def get_purpose(purpose_id: str) -> dict | None:
    for item in load_config().get("purposes", []):
        if item.get("id") == purpose_id:
            return item
    return None


def _build_link_view(purpose: dict) -> discord.ui.View | None:
    url = (purpose.get("url") or "").strip()
    if not url:
        return None
    view = discord.ui.View()
    view.add_item(
        discord.ui.Button(
            label=(purpose.get("button_label") or "打开链接")[:80],
            url=url,
            style=discord.ButtonStyle.link,
        )
    )
    return view


async def _send_dm(client: discord.Client, admin_id: int, text: str, guild: discord.Guild | None) -> bool:
    """尝试多种方式给管理员发 DM。"""
    try:
        admin_user = await client.fetch_user(admin_id)
        await admin_user.send(text)
        return True
    except discord.Forbidden:
        print(f"⚠️ fetch_user DM 被拒（管理员 {admin_id} 可能关闭了服务器成员私信）")
    except Exception as e:
        print(f"⚠️ fetch_user DM 失败: {e}")

    if guild:
        member = guild.get_member(admin_id)
        if member is None:
            try:
                member = await guild.fetch_member(admin_id)
            except (discord.NotFound, discord.HTTPException):
                member = None
        if member:
            try:
                dm = await member.create_dm()
                await dm.send(text)
                return True
            except discord.Forbidden:
                print(f"⚠️ member.create_dm 被拒（管理员 {admin_id}）")
            except Exception as e:
                print(f"⚠️ member.create_dm 失败: {e}")

    return False


async def _notify_admin_custom(
    client: discord.Client,
    user: discord.abc.User,
    guild: discord.Guild | None,
    fallback_channel: discord.abc.Messageable | None = None,
) -> bool:
    admin_id = _admin_id()
    if not admin_id:
        print("⚠️ 未配置 ONBOARDING_ADMIN_ID，跳过定制通知")
        return False

    now = time.time()
    last = _custom_notify_at.get(user.id, 0)
    if now - last < _CUSTOM_NOTIFY_COOLDOWN:
        print(f"ℹ️ 定制通知冷却中，跳过用户 {user.id}（24h 内已通知过）")
        return True
    _custom_notify_at[user.id] = now

    guild_name = guild.name if guild else "未知服务器"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    display = getattr(user, "display_name", None) or user.name
    text = (
        "🔔 **新用户选择了「免费定制」**\n\n"
        f"用户：{user.mention} (`{user.id}`)\n"
        f"用户名：{display}\n"
        f"服务器：**{guild_name}**\n"
        f"时间：{ts}\n\n"
        "请主动私聊对接~"
    )

    if await _send_dm(client, admin_id, text, guild):
        print(f"✅ 定制通知已 DM 管理员 {admin_id}（来自用户 {user.id}）")
        return True

    if fallback_channel and guild:
        admin_member = guild.get_member(admin_id)
        admin_mention = admin_member.mention if admin_member else f"<@{admin_id}>"
        try:
            await fallback_channel.send(
                f"🔔 {admin_mention} **有新「免费定制」咨询**\n"
                f"用户：{user.mention} (`{user.id}`)\n"
                f"Bot 私信未能送达，请检查 Discord 隐私设置（允许服务器成员私信），请在此对接~"
            )
            print(f"⚠️ DM 失败，已在频道 fallback @ 管理员 {admin_id}")
            return True
        except Exception as e:
            print(f"❌ 频道 fallback 也失败: {e}")

    print(f"❌ 定制通知完全失败 admin={admin_id} user={user.id}")
    return False


class OnboardingPurposeSelect(discord.ui.Select):
    def __init__(self):
        options = []
        for item in load_config().get("purposes", []):
            label = item.get("label", "")[:100]
            desc = (item.get("description") or "")[:100]
            emoji = item.get("emoji")
            options.append(
                discord.SelectOption(
                    label=label,
                    value=item["id"],
                    description=desc or None,
                    emoji=emoji or None,
                )
            )
        super().__init__(
            custom_id="onboarding:purpose",
            placeholder="选一个你来的目的…",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        purpose = get_purpose(self.values[0])
        if not purpose:
            await interaction.response.send_message("❌ 选项无效，请重试。", ephemeral=True)
            return

        guide = (purpose.get("guide") or "").strip()
        view = _build_link_view(purpose)

        kwargs: dict = {"ephemeral": True}
        if view is not None:
            kwargs["view"] = view
        await interaction.response.send_message(guide, **kwargs)

        if purpose.get("notify_admin"):
            ok = await _notify_admin_custom(
                interaction.client,
                interaction.user,
                interaction.guild,
                fallback_channel=interaction.channel,
            )
            if not ok:
                await interaction.followup.send(
                    "⚠️ 已记录你的需求，但管理员暂时收不到 Bot 通知。"
                    "请直接在成员列表 **私聊管理员**，或在此频道 @管理员 说明需求。",
                    ephemeral=True,
                )


class OnboardingWelcomeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=_VIEW_TIMEOUT)
        self.add_item(OnboardingPurposeSelect())


def register_views(client: discord.Client):
    client.add_view(OnboardingWelcomeView())


def build_welcome_content(member: discord.Member, bot_name: str) -> str:
    return (
        f"🎉 欢迎 {member.mention} 加入！我是 **{bot_name}**，一只会写 prompt 的哈士奇。\n\n"
        "👇 **你来的目的是？** 从下面选一个，本哈只给你看对应指引（仅你可见）"
    )


async def send_member_welcome(
    member: discord.Member,
    channel: discord.abc.Messageable,
    bot_name: str,
) -> None:
    await channel.send(build_welcome_content(member, bot_name), view=OnboardingWelcomeView())
