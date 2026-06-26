"""
nonebot-plugin-phira-room  (optimized)

Phira 多人房间查询与推送插件 (NoneBot2 + OneBot V11)

性能优化 (相对初版):
  1. 资源 (字体/背景/Logo) 启动时 base64 编码一次,常驻内存,不再每次渲染重读磁盘。
  2. 整个页面 <head> + 全部 CSS 启动时拼装一次,渲染时只拼接 body 片段。
  3. 持久浏览器 + 直接控制 page (get_new_page),wait_until=load,跳过 networkidle。
  4. 输出格式改为 JPEG (像素分辨率与 1280×720 viewport 一致,体积 ~1/5,编码更快)。
  5. 启动时预热 Chromium,首次 /room 不再触发冷启动。
  6. 谱面/用户名:并发解析 + TTL 缓存 + singleflight (同一 ID 并发请求只发一次)。
  7. 房间列表:1 秒短 TTL 单飞缓存,burst 期间多用户共享一次后端拉取。
  8. 全局共享 httpx.AsyncClient (Keep-Alive 连接池),消除重复 TCP/TLS 握手。

功能:
  · /room                   查询当前所有房间
  · /room record <房间名>    查询指定房间的游玩记录
  · 自动监听 SSE,推送新房间通知到配置群
"""
import asyncio
import base64
import html as html_lib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from nonebot import get_bots, get_driver, get_plugin_config, logger
from nonebot.adapters.onebot.v11 import Bot, MessageSegment
from nonebot.plugin import PluginMetadata, require
from pydantic import BaseModel, Field

require("nonebot_plugin_htmlrender")
require("nonebot_plugin_alconna")

from nonebot_plugin_htmlrender import get_new_page  # noqa: E402
from nonebot_plugin_alconna import (  # noqa: E402
    Alconna,
    Args,
    Image,
    Match,
    Subcommand,
    UniMessage,
    on_alconna,
)


# =========================================================
# 配置 (在 .env / .env.prod 中设置)
# =========================================================
class Config(BaseModel):
    phira_api_base: str = "http://23.141.172.246:12345"
    phira_chart_api: str = "https://phira.5wyxi.com"
    phira_notify_groups: List[int] = Field(default_factory=list)
    phira_font_path: str = ""
    phira_bg_path: str = ""
    phira_logo_path: str = ""
    phira_cache_ttl: int = 600
    phira_sse_retry: int = 5
    phira_image_quality: int = 90              # JPEG 质量 1-100
    phira_rooms_singleflight_ttl: float = 1.0  # 房间列表 burst 共享秒数


driver = get_driver()
plugin_config = get_plugin_config(Config)


# =========================================================
# 插件元数据
# =========================================================
__plugin_meta__ = PluginMetadata(
    name="Phira 房间查询",
    description="查询 Phira 多人游戏房间信息,并自动推送新房间通知到 QQ 群。",
    usage=(
        "━━━ 指令列表 ━━━\n"
        "  /room                  查询当前所有房间(图片)\n"
        "  /room record <房间名>   查询指定房间的游玩记录\n\n"
        "━━━ 自动推送 ━━━\n"
        "  插件会通过 SSE 监听后端,新房间创建时自动推送图片通知\n"
        "  到 .env 中配置的 QQ 群。\n\n"
        "━━━ .env 配置 ━━━\n"
        "  PHIRA_NOTIFY_GROUPS=[123456789, 987654321]\n"
        "  PHIRA_FONT_PATH=/abs/path/to/phira.ttf\n"
        "  PHIRA_BG_PATH=/abs/path/to/background.jpg\n"
        "  PHIRA_LOGO_PATH=/abs/path/to/logo.png\n"
        "  # 可选:\n"
        "  PHIRA_API_BASE=http://23.141.172.246:12345\n"
        "  PHIRA_CHART_API=https://phira.5wyxi.com\n"
        "  PHIRA_CACHE_TTL=600\n"
        "  PHIRA_SSE_RETRY=5\n"
        "  PHIRA_IMAGE_QUALITY=90\n"
    ),
    type="application",
    homepage="",
    config=Config,
    supported_adapters={"~onebot.v11"},
)


# =========================================================
# 资源 & 模板缓存 (启动时一次性构建)
# =========================================================
_resources: Dict[str, str] = {"font": "", "bg": "", "logo": ""}
_base_head_cache: str = ""
_logo_tag_cache: str = ""


def _file_to_data_url(path: str, mime: str) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.is_file():
        logger.warning(f"[phira-room] 资源文件不存在: {path}")
        return ""
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode('ascii')}"


def _esc(v: Any) -> str:
    return html_lib.escape(str(v))


def _build_base_head() -> str:
    """整合所有静态 CSS,只在启动时构建一次。"""
    font_face = (
        f"@font-face{{font-family:'Phira';"
        f"src:url('{_resources['font']}') format('truetype');"
        f"font-display:block;}}"
        if _resources["font"]
        else ""
    )
    bg_css = (
        f"background-image:url('{_resources['bg']}');"
        f"background-size:cover;background-position:center;"
        if _resources["bg"]
        else "background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);"
    )
    return (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><style>'
        + font_face
        + "*{box-sizing:border-box;margin:0;padding:0}"
        "html,body{width:1280px;height:720px;"
        "font-family:'Phira','Microsoft YaHei','PingFang SC',sans-serif;"
        "color:#fff;overflow:hidden}"
        "body{" + bg_css + "position:relative}"
        "body::before{content:'';position:absolute;inset:0;"
        "background:rgba(0,0,0,.55);z-index:0}"
        ".container{position:relative;z-index:1;width:100%;height:100%;"
        "padding:28px 44px;display:flex;flex-direction:column}"
        ".header{display:flex;align-items:center;gap:16px;margin-bottom:18px}"
        ".logo{width:56px;height:56px;object-fit:contain;"
        "filter:drop-shadow(0 0 10px rgba(255,255,255,.35))}"
        ".title{font-size:38px;font-weight:700;letter-spacing:1.5px;"
        "text-shadow:0 2px 10px rgba(0,0,0,.65)}"
        ".subtitle{margin-left:auto;font-size:17px;opacity:.85;"
        "padding:5px 14px;border-radius:999px;"
        "background:rgba(255,255,255,.10);"
        "border:1px solid rgba(255,255,255,.18)}"
        ".content{flex:1;overflow:hidden;display:flex;flex-direction:column}"
        ".footer{text-align:right;font-size:13px;opacity:.55;"
        "margin-top:8px;letter-spacing:.5px}"
        ".empty{flex:1;display:flex;align-items:center;justify-content:center;"
        "font-size:24px;opacity:.55}"
        # ---- room list ----
        ".room-grid{display:grid;grid-template-columns:repeat(2,1fr);"
        "gap:14px;overflow-y:auto;padding-right:4px;align-content:start}"
        ".room-card{background:rgba(255,255,255,.08);"
        "border:1px solid rgba(255,255,255,.18);"
        "border-radius:12px;padding:12px 16px;"
        "display:flex;flex-direction:column;gap:8px}"
        ".room-top{display:flex;align-items:center;"
        "justify-content:space-between;gap:10px}"
        ".room-name{font-size:22px;font-weight:700;max-width:70%;"
        "overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
        ".state-pill{padding:3px 12px;border-radius:999px;"
        "font-size:13px;font-weight:700;letter-spacing:.5px}"
        ".room-meta{display:flex;gap:22px;flex-wrap:wrap;font-size:14px}"
        ".meta-item{display:flex;flex-direction:column;gap:2px;min-width:0}"
        ".meta-key{font-size:11px;opacity:.55;letter-spacing:1.2px}"
        ".meta-val{font-size:15px;font-weight:600}"
        ".meta-val.chart{max-width:250px;overflow:hidden;"
        "text-overflow:ellipsis;white-space:nowrap}"
        ".room-tags{display:flex;gap:6px;min-height:20px}"
        ".tag{padding:2px 9px;border-radius:6px;font-size:11px;"
        "background:rgba(255,255,255,.12);"
        "border:1px solid rgba(255,255,255,.22)}"
        # ---- records ----
        ".rounds-wrap{overflow-y:auto;padding-right:4px;"
        "display:flex;flex-direction:column;gap:12px}"
        ".round-card{background:rgba(255,255,255,.08);"
        "border:1px solid rgba(255,255,255,.18);"
        "border-radius:12px;padding:12px 18px}"
        ".round-head{display:flex;align-items:center;gap:14px;"
        "padding-bottom:8px;margin-bottom:8px;"
        "border-bottom:1px solid rgba(255,255,255,.14)}"
        ".round-no{font-size:18px;font-weight:700;"
        "color:#fbbf24;letter-spacing:1px}"
        ".round-chart{font-size:16px;opacity:.92;flex:1;"
        "overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
        ".rec-table{width:100%;border-collapse:collapse;font-size:14px}"
        ".rec-table th{text-align:left;padding:4px 8px;"
        "font-weight:500;opacity:.55;font-size:11px;letter-spacing:1px}"
        ".rec-table td{padding:5px 8px}"
        ".rec-row.gold td.rk{color:#fbbf24;font-weight:800}"
        ".rec-row.silver td.rk{color:#d1d5db;font-weight:800}"
        ".rec-row.bronze td.rk{color:#f59e0b;font-weight:800}"
        ".rec-row td.rk{width:32px}"
        ".rec-row td.pl{font-weight:600}"
        ".rec-row td.sc{font-weight:700;color:#fbbf24}"
        ".rec-row td.fc{color:#f472b6;font-weight:700}"
        ".hits .p{color:#fbbf24}.hits .g{color:#60a5fa}"
        ".hits .b{color:#f87171}.hits .m{color:#6b7280}"
        # ---- notify ----
        ".notify-wrap{flex:1;display:flex;flex-direction:column;"
        "align-items:center;justify-content:center;gap:24px}"
        ".bigbadge{padding:7px 20px;border-radius:999px;"
        "background:linear-gradient(135deg,#f472b6,#fb923c);"
        "font-size:16px;font-weight:800;letter-spacing:3px;"
        "box-shadow:0 4px 18px rgba(244,114,182,.45)}"
        ".bigname{font-size:58px;font-weight:900;"
        "text-shadow:0 4px 18px rgba(0,0,0,.7);"
        "text-align:center;max-width:1100px;"
        "overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
        ".bighost{font-size:22px;opacity:.88}"
        ".bighost b{color:#fbbf24}"
        ".tags-row{display:flex;gap:12px}"
        ".big-tag{padding:8px 20px;border-radius:10px;"
        "background:rgba(255,255,255,.12);"
        "border:1px solid rgba(255,255,255,.22);"
        "font-size:16px;font-weight:600;letter-spacing:1px}"
        ".big-tag.muted{opacity:.7}"
        "</style></head><body>"
    )


def _load_resources() -> None:
    global _base_head_cache, _logo_tag_cache
    _resources["font"] = _file_to_data_url(plugin_config.phira_font_path, "font/ttf")
    _resources["bg"] = _file_to_data_url(plugin_config.phira_bg_path, "image/jpeg")
    _resources["logo"] = _file_to_data_url(plugin_config.phira_logo_path, "image/png")
    _base_head_cache = _build_base_head()
    _logo_tag_cache = (
        f'<img class="logo" src="{_resources["logo"]}" alt="logo"/>'
        if _resources["logo"]
        else ""
    )
    logger.info("[phira-room] 资源与样式模板已缓存到内存")


def _wrap_page(title: str, body_html: str, subtitle: str = "") -> str:
    sub = f'<div class="subtitle">{_esc(subtitle)}</div>' if subtitle else ""
    return (
        f"{_base_head_cache}"
        f'<div class="container">'
        f'<div class="header">{_logo_tag_cache}'
        f'<div class="title">{_esc(title)}</div>{sub}</div>'
        f'<div class="content">{body_html}</div>'
        f'<div class="footer">HSN多人游戏服务器 · Plugin Written By htadiy</div>'
        f"</div></body></html>"
    )


# =========================================================
# TTL 缓存 + Singleflight
# =========================================================
class TTLCache:
    __slots__ = ("ttl", "_d")

    def __init__(self, ttl: int):
        self.ttl = ttl
        self._d: Dict[Any, Tuple[Any, float]] = {}

    def get(self, key):
        item = self._d.get(key)
        if item is None:
            return None
        v, exp = item
        if exp < time.monotonic():
            self._d.pop(key, None)
            return None
        return v

    def set(self, key, value):
        self._d[key] = (value, time.monotonic() + self.ttl)


_chart_cache = TTLCache(plugin_config.phira_cache_ttl)
_user_cache = TTLCache(plugin_config.phira_cache_ttl)
_chart_inflight: Dict[int, "asyncio.Future[str]"] = {}
_user_inflight: Dict[int, "asyncio.Future[str]"] = {}


# =========================================================
# 共享 HTTP 客户端 (Keep-Alive)
# =========================================================
_http_client: Optional[httpx.AsyncClient] = None


def _get_http() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=50,
                keepalive_expiry=30.0,
            ),
        )
    return _http_client


# =========================================================
# 房间列表 (短 TTL 单飞缓存,burst 共享)
# =========================================================
_rooms_lock = asyncio.Lock()
_rooms_cache: Optional[Tuple[List[Dict[str, Any]], float]] = None


async def fetch_rooms(force: bool = False) -> List[Dict[str, Any]]:
    global _rooms_cache
    if not force and _rooms_cache is not None:
        data, exp = _rooms_cache
        if time.monotonic() < exp:
            return data
    async with _rooms_lock:
        if not force and _rooms_cache is not None:
            data, exp = _rooms_cache
            if time.monotonic() < exp:
                return data
        url = f"{plugin_config.phira_api_base}/api/rooms/info"
        resp = await _get_http().get(url)
        resp.raise_for_status()
        data = resp.json()
        _rooms_cache = (
            data,
            time.monotonic() + plugin_config.phira_rooms_singleflight_ttl,
        )
        return data


async def fetch_chart_name(chart_id: Optional[int]) -> str:
    if chart_id is None:
        return "未选谱"
    cached = _chart_cache.get(chart_id)
    if cached is not None:
        return cached
    pending = _chart_inflight.get(chart_id)
    if pending is not None:
        return await pending
    fut: "asyncio.Future[str]" = asyncio.get_event_loop().create_future()
    _chart_inflight[chart_id] = fut
    try:
        name = f"Chart#{chart_id}"
        try:
            resp = await _get_http().get(
                f"{plugin_config.phira_chart_api}/chart/{chart_id}"
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and data.get("name"):
                name = str(data["name"])
        except Exception as e:
            logger.warning(f"[phira-room] 获取谱面 {chart_id} 失败: {e}")
        _chart_cache.set(chart_id, name)
        if not fut.done():
            fut.set_result(name)
        return name
    finally:
        _chart_inflight.pop(chart_id, None)


async def fetch_user_name(user_id: int) -> str:
    cached = _user_cache.get(user_id)
    if cached is not None:
        return cached
    pending = _user_inflight.get(user_id)
    if pending is not None:
        return await pending
    fut: "asyncio.Future[str]" = asyncio.get_event_loop().create_future()
    _user_inflight[user_id] = fut
    try:
        name = f"User#{user_id}"
        try:
            resp = await _get_http().get(
                f"{plugin_config.phira_chart_api}/user/{user_id}"
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and data.get("name"):
                name = str(data["name"])
        except Exception as e:
            logger.warning(f"[phira-room] 获取用户 {user_id} 失败: {e}")
        _user_cache.set(user_id, name)
        if not fut.done():
            fut.set_result(name)
        return name
    finally:
        _user_inflight.pop(user_id, None)


async def _gather_names(
    user_ids: List[int], chart_ids: List[int]
) -> Tuple[Dict[int, str], Dict[int, str]]:
    user_task = (
        asyncio.gather(*[fetch_user_name(u) for u in user_ids])
        if user_ids
        else asyncio.sleep(0, result=[])
    )
    chart_task = (
        asyncio.gather(*[fetch_chart_name(c) for c in chart_ids])
        if chart_ids
        else asyncio.sleep(0, result=[])
    )
    user_names, chart_names = await asyncio.gather(user_task, chart_task)
    return dict(zip(user_ids, user_names)), dict(zip(chart_ids, chart_names))


# =========================================================
# HTML → 图片 (持久浏览器 + JPEG)
# =========================================================
_render_warned: bool = False


async def _html_to_bytes(html: str) -> bytes:
    """渲染 HTML 字符串为 JPEG 字节。使用持久 Chromium 浏览器。"""
    async with get_new_page(viewport={"width": 1280, "height": 720}) as page:
        await page.set_content(html, wait_until="load")
        # 等待字体真正可用,避免首帧 fallback 字体
        try:
            await page.evaluate("document.fonts && document.fonts.ready")
        except Exception:
            pass
        return await page.screenshot(
            type="jpeg",
            quality=plugin_config.phira_image_quality,
            full_page=False,
            clip={"x": 0, "y": 0, "width": 1280, "height": 720},
        )


_STATE_LABEL = {
    "SELECTING_CHART": ("选谱中", "#3b82f6"),
    "WAITING_FOR_READY": ("准备中", "#f59e0b"),
    "PLAYING": ("游戏中", "#10b981"),
}


def _state_label(state: str):
    return _STATE_LABEL.get(state, (state or "未知", "#888"))


# =========================================================
# 渲染:房间列表
# =========================================================
async def render_room_list(rooms: List[Dict[str, Any]]) -> bytes:
    if not rooms:
        body = '<div class="empty">当前暂无房间 ~</div>'
    else:
        host_ids = list({r["data"]["host"] for r in rooms})
        chart_ids = list(
            {
                r["data"].get("chart")
                for r in rooms
                if r["data"].get("chart") is not None
            }
        )
        host_map, chart_map = await _gather_names(host_ids, chart_ids)

        parts: List[str] = ['<div class="room-grid">']
        for r in rooms:
            d = r["data"]
            label, color = _state_label(d.get("state", ""))
            chart_id = d.get("chart")
            chart_name = (
                chart_map.get(chart_id, "未选谱") if chart_id is not None else "未选谱"
            )
            host_name = host_map.get(d["host"], f"User#{d['host']}")
            users_count = len(d.get("users", []))
            tag_html = ""
            if d.get("lock"):
                tag_html += '<span class="tag">✓ 房间锁定</span>'
            if d.get("cycle"):
                tag_html += '<span class="tag">✓ 循环模式</span>'
            parts.append(
                f'<div class="room-card">'
                f'<div class="room-top">'
                f'<div class="room-name">{_esc(r["name"])}</div>'
                f'<div class="state-pill" style="background:{color}">'
                f"{_esc(label)}</div></div>"
                f'<div class="room-meta">'
                f'<div class="meta-item"><span class="meta-key">房主</span>'
                f'<span class="meta-val">{_esc(host_name)}</span></div>'
                f'<div class="meta-item"><span class="meta-key">人数</span>'
                f'<span class="meta-val">{users_count}</span></div>'
                f'<div class="meta-item"><span class="meta-key">当前谱面</span>'
                f'<span class="meta-val chart">{_esc(chart_name)}</span></div>'
                f'</div><div class="room-tags">{tag_html}</div></div>'
            )
        parts.append("</div>")
        body = "".join(parts)

    html = _wrap_page("HSN在线房间列表", body, f"共 {len(rooms)} 个房间")
    return await _html_to_bytes(html)


# =========================================================
# 渲染:房间记录
# =========================================================
async def render_room_records(room_name: str, room_data: Dict[str, Any]) -> bytes:
    rounds = room_data.get("rounds", []) or []
    if not rounds:
        body = '<div class="empty">该房间暂无游玩记录 ~</div>'
    else:
        chart_ids = list({rd["chart"] for rd in rounds})
        player_ids: set = set()
        for rd in rounds:
            for rec in rd.get("records", []):
                player_ids.add(rec["player"])
        player_id_list = list(player_ids)

        player_map, chart_map = await _gather_names(player_id_list, chart_ids)

        parts: List[str] = ['<div class="rounds-wrap">']
        n = len(rounds)
        # 倒序展示(最新一轮在前)
        for idx, rd in enumerate(reversed(rounds), start=1):
            actual_idx = n - idx + 1
            chart_name = chart_map.get(rd["chart"], f"Chart#{rd['chart']}")
            recs = sorted(
                rd.get("records", []),
                key=lambda x: x.get("score", 0),
                reverse=True,
            )
            row_buf: List[str] = []
            for i, rec in enumerate(recs):
                pname = player_map.get(rec["player"], f"User#{rec['player']}")
                fc = "✦ FC" if rec.get("full_combo") else ""
                acc = rec.get("accuracy", 0) * 100
                rank_class = (
                    "gold" if i == 0
                    else "silver" if i == 1
                    else "bronze" if i == 2
                    else ""
                )
                row_buf.append(
                    f'<tr class="rec-row {rank_class}">'
                    f'<td class="rk">{i + 1}</td>'
                    f'<td class="pl">{_esc(pname)}</td>'
                    f'<td class="sc">{rec.get("score", 0):,}</td>'
                    f'<td class="ac">{acc:.2f}%</td>'
                    f'<td class="cb">{rec.get("max_combo", 0)}</td>'
                    f'<td class="hits">'
                    f'<span class="p">{rec.get("perfect", 0)}</span> / '
                    f'<span class="g">{rec.get("good", 0)}</span> / '
                    f'<span class="b">{rec.get("bad", 0)}</span> / '
                    f'<span class="m">{rec.get("miss", 0)}</span></td>'
                    f'<td class="fc">{fc}</td></tr>'
                )
            parts.append(
                f'<div class="round-card">'
                f'<div class="round-head">'
                f'<div class="round-no">第 {actual_idx} 轮</div>'
                f'<div class="round-chart">{_esc(chart_name)}</div>'
                f'</div>'
                f'<table class="rec-table"><thead><tr>'
                f"<th>#</th><th>玩家</th><th>分数</th><th>准度</th>"
                f"<th>Combo</th><th>P / G / B / M</th><th></th>"
                f"</tr></thead><tbody>{''.join(row_buf)}</tbody></table>"
                f"</div>"
            )
        parts.append("</div>")
        body = "".join(parts)

    html = _wrap_page("房间游玩记录", body, f"{room_name} · {len(rounds)} 轮")
    return await _html_to_bytes(html)


# =========================================================
# 渲染:新房间通知
# =========================================================
async def render_new_room(room_name: str, room_data: Dict[str, Any]) -> bytes:
    host_id = room_data.get("host", 0)
    host_name = await fetch_user_name(host_id) if host_id else "未知"
    tags_html = ""
    if room_data.get("lock"):
        tags_html += '<div class="big-tag">✓ 房间锁定</div>'
    if room_data.get("cycle"):
        tags_html += '<div class="big-tag">✓ 循环模式</div>'
    if not tags_html:
        tags_html = '<div class="big-tag muted">公开房间</div>'

    body = (
        '<div class="notify-wrap">'
        '<div class="bigbadge">NEW ROOM</div>'
        f'<div class="bigname">房间ID: {_esc(room_name)}</div>'
        f'<div class="bighost">房主:<b>{_esc(host_name)}</b></div>'
        f'<div class="tags-row">{tags_html}</div>'
        '</div>'
    )
    html = _wrap_page("新房间通知", body, "HSN多人游戏服务器")
    return await _html_to_bytes(html)


# =========================================================
# 命令注册 (Alconna)
# =========================================================
room_cmd = on_alconna(
    Alconna(
        "room",
        Subcommand("record", Args["name?", str]),
    ),
    use_cmd_start=True,
    skip_for_unmatch=False,
    auto_send_output=False,
    priority=10,
    block=True,
)


@room_cmd.assign("record")
async def _handle_record(name: Match[str]):
    room_name = name.result if name.available else ""
    if not room_name:
        await UniMessage("用法:/room record <房间名>").send()
        return
    try:
        rooms = await fetch_rooms()
    except Exception as e:
        logger.exception(f"[phira-room] 获取房间列表失败: {e}")
        await UniMessage(f"获取房间信息失败:{e}").send()
        return
    target = next((r for r in rooms if r.get("name") == room_name), None)
    if target is None:
        await UniMessage(f"未找到房间「{room_name}」").send()
        return
    try:
        img = await render_room_records(room_name, target.get("data", {}))
    except Exception as e:
        logger.exception(f"[phira-room] 渲染房间记录失败: {e}")
        await UniMessage(f"渲染失败:{e}").send()
        return
    await UniMessage(Image(raw=img)).send()


@room_cmd.assign("$main")
async def _handle_list():
    try:
        rooms = await fetch_rooms()
    except Exception as e:
        logger.exception(f"[phira-room] 获取房间列表失败: {e}")
        await UniMessage(f"获取房间信息失败:{e}").send()
        return
    try:
        img = await render_room_list(rooms)
    except Exception as e:
        logger.exception(f"[phira-room] 渲染房间列表失败: {e}")
        await UniMessage(f"渲染失败:{e}").send()
        return
    await UniMessage(Image(raw=img)).send()


# =========================================================
# SSE 监听
# =========================================================
_sse_task: Optional[asyncio.Task] = None


async def _push_new_room(room_name: str, room_data: Dict[str, Any]) -> None:
    if not plugin_config.phira_notify_groups:
        return
    try:
        img = await render_new_room(room_name, room_data)
    except Exception as e:
        logger.exception(f"[phira-room] 渲染新房间通知失败: {e}")
        return
    bots = get_bots()
    if not bots:
        logger.warning("[phira-room] 无可用 Bot,跳过推送")
        return
    seg = MessageSegment.image(img)
    for _, bot in bots.items():
        if not isinstance(bot, Bot):
            continue
        for gid in plugin_config.phira_notify_groups:
            try:
                await bot.send_group_msg(group_id=int(gid), message=seg)
            except Exception as e:
                logger.warning(f"[phira-room] 推送到群 {gid} 失败: {e}")


async def _handle_sse_event(event_type: str, payload: Dict[str, Any]) -> None:
    if event_type == "create_room":
        await _push_new_room(payload.get("room", ""), payload.get("data", {}))


async def _sse_loop() -> None:
    url = f"{plugin_config.phira_api_base}/api/rooms/listen"
    while True:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "GET", url, headers={"Accept": "text/event-stream"}
                ) as resp:
                    resp.raise_for_status()
                    logger.success(f"[phira-room] SSE 已连接: {url}")
                    event_type: Optional[str] = None
                    data_lines: List[str] = []
                    async for line in resp.aiter_lines():
                        if line.startswith(":"):
                            continue
                        if line == "":
                            if event_type and data_lines:
                                raw = "\n".join(data_lines)
                                try:
                                    payload = json.loads(raw)
                                    await _handle_sse_event(event_type, payload)
                                except Exception as e:
                                    logger.exception(
                                        f"[phira-room] 处理 SSE 事件失败: {e}"
                                    )
                            event_type = None
                            data_lines = []
                        elif line.startswith("event:"):
                            event_type = line[6:].strip()
                        elif line.startswith("data:"):
                            data_lines.append(line[5:].lstrip())
        except asyncio.CancelledError:
            logger.info("[phira-room] SSE 监听已取消")
            raise
        except Exception as e:
            logger.warning(
                f"[phira-room] SSE 异常,{plugin_config.phira_sse_retry}s 后重连: {e}"
            )
            await asyncio.sleep(plugin_config.phira_sse_retry)


# =========================================================
# 浏览器预热(消除首次冷启动)
# =========================================================
async def _prewarm_browser() -> None:
    try:
        async with get_new_page(viewport={"width": 100, "height": 100}) as page:
            await page.set_content(
                "<html><body style='background:#000'></body></html>",
                wait_until="load",
            )
        logger.info("[phira-room] Chromium 预热完成")
    except Exception as e:
        logger.warning(f"[phira-room] Chromium 预热失败(忽略): {e}")


# =========================================================
# 启停钩子
# =========================================================
@driver.on_startup
async def _on_startup() -> None:
    global _sse_task
    _load_resources()
    asyncio.create_task(_prewarm_browser())
    _sse_task = asyncio.create_task(_sse_loop())
    logger.info("[phira-room] 已启动 (优化版)")


@driver.on_shutdown
async def _on_shutdown() -> None:
    global _sse_task, _http_client
    if _sse_task is not None and not _sse_task.done():
        _sse_task.cancel()
        try:
            await _sse_task
        except asyncio.CancelledError:
            pass
    _sse_task = None
    if _http_client is not None:
        try:
            await _http_client.aclose()
        except Exception:
            pass
        _http_client = None
    logger.info("[phira-room] 已停止")
