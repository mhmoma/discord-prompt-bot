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
# Components V2 单消息最多 40 个子组件；每行 Section+按钮约占 3，留页眉/复制/翻页后每页最多 10 条
LAYOUT_MAX_TAGS = 10
TAGS_PER_PAGE = min(int(os.getenv("DANBOORU_TAGS_PER_PAGE", "10")), LAYOUT_MAX_TAGS)
SUBCATS_PER_PAGE = 25
SUBCATS_BUTTONS_PER_ROW = 5  # 每行多个按钮，避免超过 V2 的 40 组件上限
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


def child_display_label(child: dict) -> str:
    return (child.get("label_cn") or child.get("label") or "").strip()


def child_matches_label(child: dict, label: str) -> bool:
    label = label.strip()
    keys = {child.get("id"), child.get("label"), child.get("label_cn"), child.get("tag_group")}
    return label in {k for k in keys if k}


def find_category(label: str):
    data = load_category_map()
    label = label.strip()
    for cat in data.get("categories", []):
        if label in {cat["label"], cat["id"]}:
            return cat, None
        for child in cat.get("children", []):
            if child_matches_label(child, label):
                return cat, child
    return None, None


def find_subcategory(cat_id: str, sub_label: str):
    data = load_category_map()
    for cat in data.get("categories", []):
        if cat["id"] != cat_id:
            continue
        for child in cat.get("children", []):
            if child_matches_label(child, sub_label):
                return child
    return None


def _session_key(user_id: int) -> str:
    return str(user_id)


def get_session(user_id: int) -> dict:
    return _browser_sessions.get(_session_key(user_id), {})


def set_session(user_id: int, data: dict):
    _browser_sessions[_session_key(user_id)] = data


def build_home_text() -> str:
    data = load_category_map()
    n_cat = len(data.get("categories", []))
    n_sub = sum(len(c.get("children", [])) for c in data.get("categories", []))
    return (
        f"## 📂 Danbooru 标签浏览器\n\n"
        f"同步 [Danbooru tag groups](https://danbooru.donmai.us/wiki_pages/tag_groups) wiki。\n"
        f"**{n_cat}** 个大类 · **{n_sub}** 个子分类/列表\n\n"
        f"**点击下方大类** → 子分类 → 点击 tag 名称看详情与预览图。"
    )


def build_sub_header(category: dict, sub_page: int, total_pages: int, total: int) -> str:
    return (
        f"## {category.get('icon', '📁')} {category['label']} · 选子分类\n\n"
        f"-# 第 **{sub_page + 1}/{total_pages}** 页 · 共 **{total}** 项 · **点击下方名称**"
    )


def _page_tags(tags: list[dict], page: int) -> list[dict]:
    start = page * TAGS_PER_PAGE
    return tags[start:start + TAGS_PER_PAGE]


def _is_artist_tag(tag: dict) -> bool:
    return tag.get("category") == 1


def _tag_button_label(index: int, tag: dict) -> str:
    name = tag["name"]
    cn = tag.get("cn") or ttr.lookup_cn(name)
    count = tag.get("post_count", 0)
    prefix = "🎨 " if _is_artist_tag(tag) else ""
    if cn:
        base = f"{prefix}{index}. {cn} · {name}"
    else:
        base = f"{prefix}{index}. {name}"
    label = f"{base} — {count:,}帖"
    return label if len(label) <= 80 else label[:77] + "…"


def build_detail_text(
    tag: dict,
    sample: Optional[dict] = None,
    *,
    prompt_expanded: bool = False,
) -> str:
    name = tag["name"]
    cn = tag.get("cn") or ttr.lookup_cn(name)
    count = tag.get("post_count", 0)
    is_artist = _is_artist_tag(tag)
    if is_artist:
        title = f"🎨 画师 · {cn} · `{name}`" if cn else f"🎨 画师 · `{name}`"
    else:
        title = f"{cn} · `{name}`" if cn else f"`{name}`"
    search_url = dapi.danbooru_post_url(name)
    post_url = (sample or {}).get("post_url") or search_url

    lines = [f"## {title}", f"**{count:,}** 帖 · [搜索此 tag]({search_url})"]
    if sample:
        meta = []
        if sample.get("score") is not None:
            meta.append(f"🔥 热度 **{sample['score']:,}**")
        if sample.get("fav_count") is not None:
            meta.append(f"❤️ **{sample['fav_count']:,}** 收藏")
        if meta:
            lines.append(" · ".join(meta))
        if sample.get("post_url"):
            lines.append(f"[打开示例原帖]({post_url})")
        tag_string = sample.get("tag_string") or ""
        if tag_string:
            prompt = tag_string.replace("_", " ")
            if prompt_expanded:
                if len(prompt) > 900:
                    prompt = prompt[:897] + "…"
                lines.append(f"\n**📝 提示词**\n```\n{prompt}\n```")
            else:
                lines.append(f"\n-# 📝 提示词已折叠（{len(prompt.split())} 个 tag）· 点击下方 **展开提示词**")
    elif is_artist and count == 0:
        lines.append("\n-# 该名称在 Danbooru 暂无 artist 作品")
    return "\n".join(lines)


class TagOpenButton(discord.ui.Button):
    """点击后在原面板内打开词条详情。"""

    def __init__(self, tag: dict, list_layout: TagListLayout, index: int):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=_tag_button_label(index, tag),
        )
        self.tag = tag
        self.list_layout = list_layout

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.list_layout.user_id:
            await interaction.response.send_message("这是别人的面板哦～", ephemeral=True)
            return
        name = self.tag["name"]
        await interaction.response.edit_message(
            view=LoadingLayout(f"## ⏳ 正在加载\n\n`{name}`\n\n-# 拉取作品预览…")
        )
        try:
            async with aiohttp.ClientSession() as session:
                fresh = await dapi._fetch_single_tag(session, self.tag["name"])
                tag = {**self.tag, **fresh}
                sample = None
                if tag.get("post_count", 0) > 0:
                    sample = await dapi.fetch_sample_post(session, tag["name"])
        except Exception as e:
            await interaction.message.edit(
                view=LoadingLayout(f"## ❌ 加载失败\n\n`{name}`\n\n{e}")
            )
            return
        ll = self.list_layout
        set_session(ll.user_id, {
            **get_session(ll.user_id),
            "layer": "detail",
            "detail_tag": tag,
            "detail_sample": sample,
        })
        layout = TagDetailLayout(
            ll.user_id, ll.sub, ll.tags, ll.page, tag, sample,
            openai_client=ll.openai_client, model_name=ll.model_name,
        )
        try:
            await interaction.message.edit(view=layout)
        except Exception as e:
            await interaction.followup.send(f"❌ 详情面板渲染失败：{e}", ephemeral=True)


class TagDetailLayout(discord.ui.LayoutView):
    def __init__(
        self,
        user_id: int,
        sub: dict,
        tags: list[dict],
        page: int,
        tag: dict,
        sample: Optional[dict] = None,
        prompt_expanded: bool = False,
        openai_client=None,
        model_name=None,
    ):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.user_id = user_id
        self.sub = sub
        self.tags = tags
        self.page = page
        self.tag = tag
        self.sample = sample
        self.prompt_expanded = prompt_expanded
        self.openai_client = openai_client
        self.model_name = model_name
        self._build()

    def _build(self):
        container = discord.ui.Container(accent_color=discord.Color(0x5865F2))
        container.add_item(
            discord.ui.TextDisplay(
                build_detail_text(self.tag, self.sample, prompt_expanded=self.prompt_expanded)
            )
        )
        nav = discord.ui.ActionRow(DetailBackButton(self))
        tag_string = (self.sample or {}).get("tag_string") or ""
        if tag_string:
            label = "收起提示词" if self.prompt_expanded else "📝 展开提示词"
            nav.add_item(TogglePromptButton(self, label))
        post_url = (self.sample or {}).get("post_url")
        if post_url:
            nav.add_item(
                discord.ui.Button(style=discord.ButtonStyle.link, label="打开原帖", url=post_url)
            )
        container.add_item(nav)
        self.add_item(container)

        image_url = (self.sample or {}).get("image_url") or (self.sample or {}).get("preview_url")
        if image_url:
            gallery = discord.ui.MediaGallery()
            gallery.add_item(media=image_url, description=self.tag["name"][:256])
            self.add_item(gallery)


class DetailBackButton(discord.ui.Button):
    def __init__(self, parent: TagDetailLayout):
        super().__init__(style=discord.ButtonStyle.primary, label="◀ 返回列表")
        self.parent_layout = parent

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.parent_layout.user_id:
            await interaction.response.send_message("这是别人的面板哦～", ephemeral=True)
            return
        p = self.parent_layout
        set_session(p.user_id, {**get_session(p.user_id), "layer": "list"})
        await interaction.response.edit_message(
            view=TagListLayout(
                p.user_id, p.sub, p.tags, p.page, p.openai_client, p.model_name
            )
        )


class TogglePromptButton(discord.ui.Button):
    def __init__(self, parent: TagDetailLayout, label: str):
        super().__init__(style=discord.ButtonStyle.secondary, label=label[:80])
        self.parent_layout = parent

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.parent_layout.user_id:
            await interaction.response.send_message("这是别人的面板哦～", ephemeral=True)
            return
        p = self.parent_layout
        await interaction.response.edit_message(
            view=TagDetailLayout(
                p.user_id, p.sub, p.tags, p.page, p.tag, p.sample,
                prompt_expanded=not p.prompt_expanded,
                openai_client=p.openai_client, model_name=p.model_name,
            )
        )


class LoadingLayout(discord.ui.LayoutView):
    def __init__(self, text: str):
        super().__init__(timeout=VIEW_TIMEOUT)
        container = discord.ui.Container(accent_color=discord.Color(0x5865F2))
        container.add_item(discord.ui.TextDisplay(text))
        self.add_item(container)


class TagListLayout(discord.ui.LayoutView):
    """Components V2：每行 tag 名称为可点击按钮，点开看详情与预览图。"""

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
            f"## 📂 {child_display_label(self.sub)}\n"
            f"`{self.sub['tag_group']}`\n"
            f"第 **{self.page + 1}/{self.total_pages}** 页 · 共 **{len(self.tags)}** 个 tag"
            f"\n\n-# 按 Danbooru **作品数** 降序 · 点击名称在同一面板查看详情"
        )
        copy_tags = ", ".join(t["name"] for t in page_tags)
        if copy_tags:
            header += f"\n\n📋 本页复制\n```{copy_tags[:700]}```"

        container.add_item(discord.ui.TextDisplay(header))

        for idx, tag in enumerate(page_tags):
            num = self.page * TAGS_PER_PAGE + idx + 1
            container.add_item(discord.ui.ActionRow(TagOpenButton(tag, self, num)))

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
        await interaction.response.edit_message(
            view=HomeLayout(self.user_id, self.openai_client, self.model_name)
        )


class HomeCategoryButton(discord.ui.Button):
    def __init__(self, category: dict, user_id: int, openai_client=None, model_name=None):
        icon = category.get("icon", "📁")
        label = f"{icon} {category['label']}"[:80]
        super().__init__(style=discord.ButtonStyle.secondary, label=label)
        self.category = category
        self.user_id = user_id
        self.openai_client = openai_client
        self.model_name = model_name

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("这是别人的面板哦～", ephemeral=True)
            return
        set_session(self.user_id, {"layer": "sub", "category_id": self.category["id"]})
        await interaction.response.edit_message(
            view=SubCategoryLayout(
                self.user_id, self.category, self.openai_client, self.model_name, sub_page=0
            )
        )


class HomeLayout(discord.ui.LayoutView):
    def __init__(self, user_id: int, openai_client=None, model_name=None):
        super().__init__(timeout=VIEW_TIMEOUT)
        data = load_category_map()
        categories = data.get("categories", [])
        container = discord.ui.Container(accent_color=discord.Color(0x5865F2))
        container.add_item(discord.ui.TextDisplay(build_home_text()))
        for i in range(0, len(categories), 5):
            chunk = categories[i:i + 5]
            container.add_item(
                discord.ui.ActionRow(
                    *[
                        HomeCategoryButton(c, user_id, openai_client, model_name)
                        for c in chunk
                    ]
                )
            )
        self.add_item(container)


class SubCategoryLayout(discord.ui.LayoutView):
    def __init__(
        self,
        user_id: int,
        category: dict,
        openai_client=None,
        model_name=None,
        sub_page: int = 0,
    ):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.user_id = user_id
        self.category = category
        self.openai_client = openai_client
        self.model_name = model_name
        self.sub_page = sub_page
        children = category.get("children", [])
        self.sub_total_pages = max(1, math.ceil(len(children) / SUBCATS_PER_PAGE))
        start = sub_page * SUBCATS_PER_PAGE
        page_children = children[start:start + SUBCATS_PER_PAGE]

        container = discord.ui.Container(accent_color=discord.Color(0x57F287))
        container.add_item(
            discord.ui.TextDisplay(
                build_sub_header(category, sub_page, self.sub_total_pages, len(children))
            )
        )
        for i in range(0, len(page_children), SUBCATS_BUTTONS_PER_ROW):
            chunk = page_children[i:i + SUBCATS_BUTTONS_PER_ROW]
            container.add_item(
                discord.ui.ActionRow(
                    *[SubCategoryOpenButton(sub, self) for sub in chunk]
                )
            )

        nav = discord.ui.ActionRow()
        if sub_page > 0:
            nav.add_item(SubCatPageButton("prev", self))
        if sub_page < self.sub_total_pages - 1:
            nav.add_item(SubCatPageButton("next", self))
        nav.add_item(GoHomeButton(user_id, openai_client, model_name))
        container.add_item(nav)
        self.add_item(container)

    async def load_tag_list(self, interaction: discord.Interaction, sub: dict, page: int = 0):
        label = child_display_label(sub)
        await interaction.response.edit_message(
            view=LoadingLayout(f"## ⏳ 正在加载\n\n**{label}**\n`{sub['tag_group']}`\n\n-# 首次约需几秒，之后会走缓存")
        )
        try:
            async with aiohttp.ClientSession() as session:
                tags = await dapi.get_group_tags_sorted(session, sub["tag_group"])
                tags = await ttr.enrich_tags_cn(tags, self.openai_client, self.model_name, allow_ai=False)
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
            "sub": sub,
            "tag_group": sub["tag_group"],
            "sub_label": label,
            "page": page,
            "tags": tags,
        })
        layout = TagListLayout(self.user_id, sub, tags, page, self.openai_client, self.model_name)
        try:
            await interaction.message.edit(view=layout)
        except Exception as e:
            await interaction.followup.send(f"❌ 面板渲染失败：{e}", ephemeral=True)


class SubCategoryOpenButton(discord.ui.Button):
    def __init__(self, sub: dict, parent: SubCategoryLayout):
        label = child_display_label(sub)[:80]
        super().__init__(style=discord.ButtonStyle.secondary, label=label)
        self.sub = sub
        self.parent_layout = parent

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.parent_layout.user_id:
            await interaction.response.send_message("这是别人的面板哦～", ephemeral=True)
            return
        await self.parent_layout.load_tag_list(interaction, self.sub, page=0)


class SubCatPageButton(discord.ui.Button):
    def __init__(self, direction: str, parent: SubCategoryLayout):
        label = "◀ 上页分类" if direction == "prev" else "下页分类 ▶"
        super().__init__(style=discord.ButtonStyle.secondary, label=label)
        self.direction = direction
        self.parent_layout = parent

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.parent_layout.user_id:
            await interaction.response.send_message("这是别人的面板哦～", ephemeral=True)
            return
        delta = -1 if self.direction == "prev" else 1
        new_page = max(0, min(self.parent_layout.sub_page + delta, self.parent_layout.sub_total_pages - 1))
        await interaction.response.edit_message(
            view=SubCategoryLayout(
                self.parent_layout.user_id,
                self.parent_layout.category,
                self.parent_layout.openai_client,
                self.parent_layout.model_name,
                sub_page=new_page,
            )
        )


class GoHomeButton(discord.ui.Button):
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
        await interaction.response.edit_message(
            view=HomeLayout(self.user_id, self.openai_client, self.model_name)
        )


async def open_browser(channel, user_id: int, openai_client=None, model_name=None):
    layout = HomeLayout(user_id, openai_client, model_name)
    set_session(user_id, {"layer": "home"})
    return await channel.send(view=layout)


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
            + "、".join(child_display_label(c) for c in cat.get("children", [])[:30])
        )
        return

    loading = await channel.send(f"⏳ 正在加载 **{child_display_label(child)}**…")
    try:
        async with aiohttp.ClientSession() as session:
            tags = await dapi.get_group_tags_sorted(session, child["tag_group"])
            tags = await ttr.enrich_tags_cn(tags, openai_client, model_name, allow_ai=False)
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
        "sub": child,
        "tag_group": child["tag_group"],
        "sub_label": child_display_label(child),
        "page": page_idx,
        "tags": tags,
    })
    layout = TagListLayout(user_id, child, tags, page_idx, openai_client, model_name)
    await loading.edit(content=None, view=layout)
