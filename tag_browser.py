from __future__ import annotations

import json
import math
import os
from typing import List, Optional

import aiohttp
import discord

import danbooru_api as dapi
import tag_translate as ttr

MAP_FILE = "danbooru_category_map.json"
# 每页最多 15 条：3 行 × 5 个「查看」按钮 + 翻页 + 主菜单 = 5 行上限
TAGS_PER_PAGE = min(int(os.getenv("DANBOORU_TAGS_PER_PAGE", "15")), 15)
VIEW_TIMEOUT = int(os.getenv("DANBOORU_VIEW_TIMEOUT", "600"))

_category_map = None
_browser_sessions = {}


def load_category_map():
    global _category_map
    if _category_map is not None:
        return _category_map
    with open(MAP_FILE, "r", encoding="utf-8") as f:
        _category_map = json.load(f)
    return _category_map


def find_category(label: str):
    data = load_category_map()
    label = label.strip()
    for cat in data.get("categories", []):
        if label in {cat["label"], cat["id"]}:
            return cat, None
        for child in cat.get("children", []):
            if label in {child["label"], child["id"]}:
                return cat, child
    return None, None


def find_subcategory(cat_id: str, sub_label: str):
    data = load_category_map()
    for cat in data.get("categories", []):
        if cat["id"] != cat_id:
            continue
        for child in cat.get("children", []):
            if sub_label in {child["label"], child["id"]}:
                return child
    return None


def _session_key(user_id: int) -> str:
    return str(user_id)


def get_session(user_id: int) -> dict:
    return _browser_sessions.get(_session_key(user_id), {})


def set_session(user_id: int, data: dict):
    _browser_sessions[_session_key(user_id)] = data


def build_home_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📂 Danbooru 标签浏览器",
        description="从下拉菜单选择**大类**，再选**子分类**，即可浏览 tag 列表。\n点每条 tag 旁的 **查看** 按钮，弹出详情与预览图。",
        color=0x5865F2,
    )
    embed.set_footer(text="指令：D浏览 | 快捷：D类 姿势 性姿势")
    return embed


def build_sub_embed(category: dict) -> discord.Embed:
    lines = [f"{c['label']} → `{c['tag_group']}`" for c in category.get("children", [])]
    embed = discord.Embed(
        title=f"{category.get('icon', '📁')} {category['label']} · 选子分类",
        description="\n".join(lines) if lines else "暂无子分类",
        color=0x57F287,
    )
    embed.set_footer(text="🏠 可点「主菜单」返回")
    return embed


def _page_tags(tags: list[dict], page: int) -> list[dict]:
    start = page * TAGS_PER_PAGE
    return tags[start:start + TAGS_PER_PAGE]


def build_list_embed(sub: dict, tags: list[dict], page: int, total_pages: int) -> discord.Embed:
    page_tags = _page_tags(tags, page)
    lines: List[str] = []
    for i, tag in enumerate(page_tags, start=page * TAGS_PER_PAGE + 1):
        name = tag["name"]
        cn = tag.get("cn") or ttr.lookup_cn(name)
        count = tag.get("post_count", 0)
        label = f"{cn} · `{name}`" if cn else f"`{name}`"
        lines.append(f"**{i}.** {label} — **{count:,}** 帖")

    copy_tags = ", ".join(t["name"] for t in page_tags)
    embed = discord.Embed(
        title=f"📂 {sub['label']}",
        description=f"`{sub['tag_group']}`\n第 **{page + 1}/{total_pages}** 页 · 共 **{len(tags)}** 个 tag",
        color=0xFEE75C,
    )
    if lines:
        body = "\n".join(lines)
        if len(body) > 3900:
            body = body[:3890] + "\n…"
        embed.add_field(name="标签列表", value=body, inline=False)
    if copy_tags:
        embed.add_field(name="📋 本页复制", value=f"```{copy_tags[:950]}```", inline=False)
    embed.set_footer(text="点下方编号按钮「查看」详情与预览 · ◀▶ 翻页")
    return embed


def build_detail_embed(tag: dict, sample: Optional[dict] = None) -> discord.Embed:
    name = tag["name"]
    cn = tag.get("cn") or ttr.lookup_cn(name)
    count = tag.get("post_count", 0)
    title = f"{cn} · `{name}`" if cn else f"`{name}`"
    post_url = (sample or {}).get("post_url") or dapi.danbooru_post_url(name)
    embed = discord.Embed(
        title=title,
        description=f"**{count:,}** 帖",
        url=post_url,
        color=0x5865F2,
    )
    embed.add_field(name="🔗 Danbooru", value=f"[搜索此 tag]({post_url})", inline=False)
    if sample and sample.get("post_url"):
        embed.add_field(name="🖼 示例帖", value=f"[打开示例图]({sample['post_url']})", inline=False)
    preview = (sample or {}).get("preview_url")
    if preview:
        embed.set_image(url=preview)
    return embed


class HomeView(discord.ui.View):
    def __init__(self, user_id: int, openai_client=None, model_name=None):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.user_id = user_id
        self.openai_client = openai_client
        self.model_name = model_name
        data = load_category_map()
        options = [
            discord.SelectOption(label=f"{c.get('icon', '')} {c['label']}"[:100], value=c["id"])
            for c in data.get("categories", [])[:25]
        ]
        self.add_item(CategorySelect(options, self))


class CategorySelect(discord.ui.Select):
    def __init__(self, options, home_view: HomeView):
        super().__init__(placeholder="选择大类…", min_values=1, max_values=1, options=options)
        self.home_view = home_view

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.home_view.user_id:
            await interaction.response.send_message("这是别人的面板哦～", ephemeral=True)
            return
        cat_id = self.values[0]
        data = load_category_map()
        category = next(c for c in data["categories"] if c["id"] == cat_id)
        set_session(self.home_view.user_id, {"layer": "sub", "category_id": cat_id})
        view = SubCategoryView(self.home_view.user_id, category, self.home_view.openai_client, self.home_view.model_name)
        await interaction.response.edit_message(embed=build_sub_embed(category), view=view)


class SubCategoryView(discord.ui.View):
    def __init__(self, user_id: int, category: dict, openai_client=None, model_name=None):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.user_id = user_id
        self.category = category
        self.openai_client = openai_client
        self.model_name = model_name
        options = [
            discord.SelectOption(label=c["label"][:100], value=c["id"])
            for c in category.get("children", [])[:25]
        ]
        self.add_item(SubCategorySelect(options, self))
        self.add_item(HomeButton(user_id, openai_client, model_name))

    async def load_tag_list(self, interaction: discord.Interaction, sub: dict, page: int = 0):
        await interaction.response.defer()
        try:
            async with aiohttp.ClientSession() as session:
                tags = await dapi.get_group_tags_sorted(session, sub["tag_group"])
                tags = await ttr.enrich_tags_cn(tags, self.openai_client, self.model_name)
                if not tags:
                    await interaction.followup.send(f"🤔 `{sub['tag_group']}` 下未找到 tag。", ephemeral=True)
                    return
                total_pages = max(1, math.ceil(len(tags) / TAGS_PER_PAGE))
                page = max(0, min(page, total_pages - 1))
        except Exception as e:
            await interaction.followup.send(f"❌ 拉取 Danbooru 失败：{e}", ephemeral=True)
            return

        set_session(self.user_id, {
            "layer": "list",
            "category_id": self.category["id"],
            "sub_id": sub["id"],
            "tag_group": sub["tag_group"],
            "sub_label": sub["label"],
            "page": page,
            "tags": tags,
        })
        embed = build_list_embed(sub, tags, page, total_pages)
        view = TagListView(self.user_id, sub, tags, page, self.openai_client, self.model_name)
        await interaction.message.edit(content=None, embed=embed, embeds=[], view=view)


class SubCategorySelect(discord.ui.Select):
    def __init__(self, options, parent: SubCategoryView):
        super().__init__(placeholder="选择子分类…", min_values=1, max_values=1, options=options)
        self.parent_view = parent

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.parent_view.user_id:
            await interaction.response.send_message("这是别人的面板哦～", ephemeral=True)
            return
        sub_id = self.values[0]
        sub = next(c for c in self.parent_view.category["children"] if c["id"] == sub_id)
        await self.parent_view.load_tag_list(interaction, sub, page=0)


class TagViewButton(discord.ui.Button):
    def __init__(self, index: int, tag: dict, row: int, user_id: int):
        cn = (tag.get("cn") or "").strip()
        short = cn[:8] if cn else tag["name"][:10]
        label = f"{index}·{short}"[:80]
        super().__init__(style=discord.ButtonStyle.secondary, label=label, row=min(row, 2))
        self.tag = tag
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("这是别人的面板哦～", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        sample = None
        try:
            async with aiohttp.ClientSession() as session:
                sample = await dapi.fetch_sample_post(session, self.tag["name"])
        except Exception as e:
            await interaction.followup.send(f"❌ 加载预览失败：{e}", ephemeral=True)
            return
        embed = build_detail_embed(self.tag, sample)
        await interaction.followup.send(embed=embed, ephemeral=True)


class TagListView(discord.ui.View):
    def __init__(self, user_id: int, sub: dict, tags: list[dict], page: int, openai_client=None, model_name=None):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.user_id = user_id
        self.sub = sub
        self.tags = tags
        self.page = page
        self.openai_client = openai_client
        self.model_name = model_name
        self.total_pages = max(1, math.ceil(len(tags) / TAGS_PER_PAGE))

        page_tags = _page_tags(tags, page)
        for idx, tag in enumerate(page_tags):
            num = page * TAGS_PER_PAGE + idx + 1
            self.add_item(TagViewButton(num, tag, idx // 5, user_id))

        if page > 0:
            self.add_item(PageButton("prev", self))
        if page < self.total_pages - 1:
            self.add_item(PageButton("next", self))
        self.add_item(HomeButton(user_id, openai_client, model_name))

    async def refresh(self, interaction: discord.Interaction, new_page: int):
        await interaction.response.defer()
        new_page = max(0, min(new_page, self.total_pages - 1))
        set_session(self.user_id, {**get_session(self.user_id), "page": new_page})
        embed = build_list_embed(self.sub, self.tags, new_page, self.total_pages)
        view = TagListView(self.user_id, self.sub, self.tags, new_page, self.openai_client, self.model_name)
        await interaction.message.edit(embed=embed, embeds=[], view=view)


class PageButton(discord.ui.Button):
    def __init__(self, direction: str, parent: TagListView):
        label = "◀ 上页" if direction == "prev" else "下页 ▶"
        super().__init__(style=discord.ButtonStyle.secondary, label=label, row=3)
        self.direction = direction
        self.parent_view = parent

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.parent_view.user_id:
            await interaction.response.send_message("这是别人的面板哦～", ephemeral=True)
            return
        new_page = self.parent_view.page + (-1 if self.direction == "prev" else 1)
        await self.parent_view.refresh(interaction, new_page)


class HomeButton(discord.ui.Button):
    def __init__(self, user_id: int, openai_client=None, model_name=None):
        super().__init__(style=discord.ButtonStyle.primary, label="🏠 主菜单", row=4)
        self.user_id = user_id
        self.openai_client = openai_client
        self.model_name = model_name

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("这是别人的面板哦～", ephemeral=True)
            return
        set_session(self.user_id, {"layer": "home"})
        view = HomeView(self.user_id, self.openai_client, self.model_name)
        await interaction.response.edit_message(embed=build_home_embed(), embeds=[], view=view)


async def open_browser(channel, user_id: int, openai_client=None, model_name=None):
    view = HomeView(user_id, openai_client, model_name)
    set_session(user_id, {"layer": "home"})
    return await channel.send(embed=build_home_embed(), view=view)


async def open_category_text(channel, user_id: int, cat_label: str, sub_label: str, page: int, openai_client=None, model_name=None):
    cat, child = find_category(cat_label)
    if not cat:
        await channel.send(f"❌ 未找到分类「{cat_label}」。发 `D浏览` 打开面板。")
        return
    if not child and sub_label:
        child = find_subcategory(cat["id"], sub_label)
    if not child:
        await channel.send(
            f"❌ 未找到子分类「{sub_label}」。大类 **{cat['label']}** 下可选："
            + "、".join(c["label"] for c in cat.get("children", []))
        )
        return

    loading = await channel.send(f"⏳ 正在加载 **{child['label']}**…")
    try:
        async with aiohttp.ClientSession() as session:
            tags = await dapi.get_group_tags_sorted(session, child["tag_group"])
            tags = await ttr.enrich_tags_cn(tags, openai_client, model_name)
            if not tags:
                await loading.edit(content=f"🤔 `{child['tag_group']}` 下没有 tag。")
                return
            total_pages = max(1, math.ceil(len(tags) / TAGS_PER_PAGE))
            page_idx = max(0, min(page - 1, total_pages - 1))
    except Exception as e:
        await loading.edit(content=f"❌ Danbooru 请求失败：{e}")
        return

    set_session(user_id, {
        "layer": "list",
        "category_id": cat["id"],
        "sub_id": child["id"],
        "tag_group": child["tag_group"],
        "sub_label": child["label"],
        "page": page_idx,
        "tags": tags,
    })
    embed = build_list_embed(child, tags, page_idx, total_pages)
    view = TagListView(user_id, child, tags, page_idx, openai_client, model_name)
    await loading.edit(content=None, embed=embed, view=view)
