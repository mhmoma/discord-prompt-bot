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
        description="从下拉菜单选择**大类**，再选**子分类**，即可浏览 tag 列表。\n每行右侧点 **查看**，弹出详情与预览图。",
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


def _format_tag_line(index: int, tag: dict) -> str:
    name = tag["name"]
    cn = tag.get("cn") or ttr.lookup_cn(name)
    count = tag.get("post_count", 0)
    label = f"{cn} · `{name}`" if cn else f"`{name}`"
    return f"**{index}.** {label} — **{count:,}** 帖"


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


class TagDetailButton(discord.ui.Button):
    def __init__(self, tag: dict, user_id: int):
        super().__init__(style=discord.ButtonStyle.primary, label="查看")
        self.tag = tag
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("这是别人的面板哦～", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            async with aiohttp.ClientSession() as session:
                sample = await dapi.fetch_sample_post(session, self.tag["name"])
        except Exception as e:
            await interaction.followup.send(f"❌ 加载预览失败：{e}", ephemeral=True)
            return
        embed = build_detail_embed(self.tag, sample)
        await interaction.followup.send(embed=embed, ephemeral=True)


class TagListLayout(discord.ui.LayoutView):
    """Components V2：每行 tag 右侧内嵌「查看」按钮。"""

    def __init__(
        self,
        user_id: int,
        sub: dict,
        tags: list[dict],
        page: int,
        openai_client=None,
        model_name=None,
    ):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.user_id = user_id
        self.sub = sub
        self.tags = tags
        self.page = page
        self.openai_client = openai_client
        self.model_name = model_name
        self.total_pages = max(1, math.ceil(len(tags) / TAGS_PER_PAGE))
        self._build()

    def _build(self):
        page_tags = _page_tags(self.tags, self.page)
        container = discord.ui.Container(accent_color=discord.Color(0xFEE75C))

        header = (
            f"## 📂 {self.sub['label']}\n"
            f"`{self.sub['tag_group']}`\n"
            f"第 **{self.page + 1}/{self.total_pages}** 页 · 共 **{len(self.tags)}** 个 tag"
        )
        container.add_item(discord.ui.TextDisplay(header))

        copy_tags = ", ".join(t["name"] for t in page_tags)
        if copy_tags:
            container.add_item(discord.ui.TextDisplay(f"📋 本页复制\n```{copy_tags[:900]}```"))

        container.add_item(discord.ui.Separator(divider=True, spacing=discord.SeparatorSpacing.small))

        for idx, tag in enumerate(page_tags):
            num = self.page * TAGS_PER_PAGE + idx + 1
            container.add_item(
                discord.ui.Section(
                    _format_tag_line(num, tag),
                    accessory=TagDetailButton(tag, self.user_id),
                )
            )

        nav = discord.ui.ActionRow()
        if self.page > 0:
            nav.add_item(ListPageButton("prev", self))
        if self.page < self.total_pages - 1:
            nav.add_item(ListPageButton("next", self))
        nav.add_item(ListHomeButton(self.user_id, self.openai_client, self.model_name))
        container.add_item(nav)

        self.add_item(container)


class ListPageButton(discord.ui.Button):
    def __init__(self, direction: str, parent: TagListLayout):
        label = "◀ 上页" if direction == "prev" else "下页 ▶"
        super().__init__(style=discord.ButtonStyle.secondary, label=label)
        self.direction = direction
        self.parent_layout = parent

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.parent_layout.user_id:
            await interaction.response.send_message("这是别人的面板哦～", ephemeral=True)
            return
        await interaction.response.defer()
        delta = -1 if self.direction == "prev" else 1
        new_page = max(0, min(self.parent_layout.page + delta, self.parent_layout.total_pages - 1))
        set_session(self.parent_layout.user_id, {**get_session(self.parent_layout.user_id), "page": new_page})
        new_layout = TagListLayout(
            self.parent_layout.user_id,
            self.parent_layout.sub,
            self.parent_layout.tags,
            new_page,
            self.parent_layout.openai_client,
            self.parent_layout.model_name,
        )
        await interaction.message.edit(view=new_layout)


class ListHomeButton(discord.ui.Button):
    def __init__(self, user_id: int, openai_client=None, model_name=None):
        super().__init__(style=discord.ButtonStyle.primary, label="🏠 主菜单")
        self.user_id = user_id
        self.openai_client = openai_client
        self.model_name = model_name

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("这是别人的面板哦～", ephemeral=True)
            return
        set_session(self.user_id, {"layer": "home"})
        view = HomeView(self.user_id, self.openai_client, self.model_name)
        await interaction.response.edit_message(embed=build_home_embed(), view=view)


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
        layout = TagListLayout(self.user_id, sub, tags, page, self.openai_client, self.model_name)
        await interaction.message.edit(embed=None, view=layout)


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
        await interaction.response.edit_message(embed=build_home_embed(), view=view)


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
    layout = TagListLayout(user_id, child, tags, page_idx, openai_client, model_name)
    await loading.edit(content=None, embed=None, view=layout)
