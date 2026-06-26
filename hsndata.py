import httpx
from pathlib import Path
from typing import Optional

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment, Message
from nonebot.log import logger
from nonebot.plugin import PluginMetadata

from arclet.alconna import (
    Alconna, Args, Option, Subcommand, 
    CommandMeta, Arparma, MultiVar
)
from nonebot_plugin_alconna import (
    on_alconna, Match, Query, 
    AlconnaMatches, UniMessage
)

# ============================================================================
# 全局配置
# ============================================================================

# HSN监控API的基础URL
API_BASE_URL = "http://23.141.172.246:7001"

# 图表存储路径（本地文件夹）
CHART_PATH = Path("/root/ranksfuck/charts")  # 修改为你的图表文件夹路径

# Phira用户API基础URL
PHIRA_USER_API = "https://phira.5wyxi.com/user"

# HTTP请求超时设置(秒)
REQUEST_TIMEOUT = 30.0

# 图表文件名映射（根据API文档的"图表文件说明"）1
CHART_MAPPING = {
    "hsn": "hsn_trend_minutely.png",           # 全量HSN服务器在线人数变化图表（每分钟自动生成）
    "room": "room_usage_ranking.png",           # 房间名使用次数排行榜
    "user_bar": "user_playtime_ranking_bar.png",  # 用户游玩时间排行榜柱状图
    "user_pie": "user_playtime_ranking_pie.png"   # 用户游玩时间排行榜饼状图
}

# ============================================================================
# 插件元数据
# ============================================================================

__plugin_meta__ = PluginMetadata(
    name="HSN数据监控",
    description="服务器监控数据访问插件",
    usage="""
    /hsndata health - 检查API健康状态
    /hsndata history [开始时间] [结束时间] - 获取HSN历史数据
    /hsndata chart <开始时间> <结束时间> - 生成指定时段图表
    /hsndata charts - 列出所有已生成的图表
    /hsndata image <类型> - 获取图表图片（从本地）
        类型: hsn(在线趋势) | room(房间排名) | user_bar(用户柱状图) | user_pie(用户饼图)
    /hsndata roomrank - 获取房间使用排名
    /hsndata userrank [用户ID] - 获取用户游玩时间排名或查询指定用户
    /hsndata generate - 手动触发图表生成
    /hsndata leaderboard [数量]（必须） - 获取用户游玩时间排行榜
    """,
    type="application",
    homepage="https://github.com/your-repo/nonebot-plugin-hsndata",
    supported_adapters={"~onebot.v11"}
)

# ============================================================================
# ALCONNA命令定义
# ============================================================================

hsndata_cmd = Alconna(
    ["/", "!"],
    "hsndata",
    
    # 子命令1: 健康检查
    Subcommand(
        "health",
        help_text="检查API服务器健康状态"
    ),
    
    # 子命令2: 获取HSN历史数据
    Subcommand(
        "history",
        Args["start?", str]["end?", str],
        help_text="获取HSN历史数据，可选时间范围(格式: YYYY-MM-DD HH:MM:SS)"
    ),
    
    # 子命令3: 生成HSN图表
    Subcommand(
        "chart",
        Args["start", str]["end", str],
        help_text="生成指定时段的HSN图表"
    ),
    
    # 子命令4: 列出所有图表
    Subcommand(
        "charts",
        help_text="获取所有已生成图表的列表"
    ),
    
    # 子命令5: 获取图表图片(从本地文件)
    Subcommand(
        "image",
        Args["chart_type", str],
        help_text="获取图表图片(从本地) - 类型: hsn/room/user_bar/user_pie"
    ),
    
    # 子命令6: 房间使用排名
    Subcommand(
        "roomrank",
        help_text="获取房间使用次数排名"
    ),
    
    # 子命令7: 用户游玩时间排名（支持查询指定用户）
    Subcommand(
        "userrank",
        Args["user_id?", int],
        help_text="获取用户游玩时间排名，或查询指定用户数据"
    ),
    
    # 子命令8: 触发图表生成
    Subcommand(
        "generate",
        help_text="手动触发图表生成流程"
    ),
    
    # 子命令9: 游玩时间排行榜
    Subcommand(
        "leaderboard",
        Args["limit?", int],
        help_text="获取游玩时间排行榜(可选指定前N名)"
    ),
    
    meta=CommandMeta(
        description="HSN数据监控系统 - 访问服务器监控数据",
        usage="hsndata <子命令> [参数]",
        example="""
        /hsndata health
        /hsndata history "2025-10-01 00:00:00" "2025-10-06 23:59:59"
        /hsndata chart "2025-10-05 00:00:00" "2025-10-06 00:00:00"
        /hsndata image hsn
        /hsndata userrank
        /hsndata userrank 12345
        /hsndata leaderboard 10
        """,
        fuzzy_match=True,
    )
)

# 创建Alconna匹配器
hsndata = on_alconna(
    hsndata_cmd,
    auto_send_output=True,
    skip_for_unmatch=True,
    aliases={"hsn", "监控数据"}
)

# ============================================================================
# 工具函数
# ============================================================================

async def make_api_request(
    endpoint: str,
    method: str = "GET",
    params: Optional[dict] = None,
    json_data: Optional[dict] = None
) -> dict | bytes | None:
    """
    向HSN API发起HTTP请求，包含完善的错误处理。
    
    Args:
        endpoint: API端点路径 (例如: "/health")
        method: HTTP方法 (GET, POST等)
        params: 查询参数
        json_data: JSON请求体数据
    
    Returns:
        响应数据 (dict或bytes)
        
    Raises:
        httpx.HTTPError: 网络或HTTP错误
    """
    url = f"{API_BASE_URL}{endpoint}"
    
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.request(
                method=method,
                url=url,
                params=params,
                json=json_data
            )
            response.raise_for_status()
            
            # 对图片返回二进制数据
            content_type = response.headers.get("content-type", "")
            if "image" in content_type:
                return response.content
            
            # 尝试解析JSON，失败则返回文本
            try:
                return response.json()
            except Exception:
                return {"data": response.text}
                
    except httpx.TimeoutException:
        logger.error(f"请求超时: {url}")
        raise
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP错误 {e.response.status_code}: {url}")
        raise
    except httpx.RequestError as e:
        logger.error(f"请求错误 {url}: {e}")
        raise


async def get_username_from_phira(user_id: int) -> str:
    """
    从Phira API获取用户名。
    
    Args:
        user_id: 用户ID
        
    Returns:
        用户名，获取失败则返回"用户{id}"
    """
    try:
        url = f"{PHIRA_USER_API}/{user_id}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            
            data = response.json()
            username = data.get("name", f"用户{user_id}")
            return username
            
    except Exception as e:
        logger.warning(f"获取用户 {user_id} 的用户名失败: {e}")
        return f"用户{user_id}"


def format_json_response(data: dict) -> str:
    """
    将JSON响应数据格式化为可读文本。
    
    Args:
        data: JSON数据字典
        
    Returns:
        格式化的字符串
    """
    import json
    return json.dumps(data, indent=2, ensure_ascii=False)


def create_error_message(error: Exception) -> str:
    """
    创建用户友好的错误消息。
    
    Args:
        error: 异常对象
        
    Returns:
        格式化的错误消息
    """
    if isinstance(error, httpx.TimeoutException):
        return "⏱️ 请求超时，请稍后重试"
    elif isinstance(error, httpx.HTTPStatusError):
        status_code = error.response.status_code
        if status_code == 404:
            return "❌ 资源未找到"
        elif status_code >= 500:
            return "🔧 服务器错误，请稍后重试"
        else:
            return f"❌ HTTP错误: {status_code}"
    elif isinstance(error, httpx.RequestError):
        return "🌐 网络连接失败"
    else:
        return f"❌ 发生错误: {str(error)}"

# ============================================================================
# 命令处理器
# ============================================================================

# 处理器1: 健康检查
@hsndata.assign("health")
async def handle_health():
    """检查API健康状态。"""
    logger.info("收到健康检查请求")
    
    try:
        data = await make_api_request("/health")
        
        if data and isinstance(data, dict):
            status = data.get("status", "unknown")
            message = f"✅ 服务状态: {status}"
            
            if "timestamp" in data:
                message += f"\n🕐 时间: {data['timestamp']}"
                
            await hsndata.send(message)
        else:
            await hsndata.send("✅ 服务正常运行")
            
    except Exception as e:
        logger.exception("健康检查失败")
        await hsndata.send(create_error_message(e))


# 处理器2: HSN历史数据
@hsndata.assign("history")
async def handle_history(
    start: Match[str],
    end: Match[str]
):
    """获取HSN历史数据，支持可选时间范围。"""
    logger.info("收到HSN历史数据请求")
    
    try:
        params = {}
        if start.available:
            params["start_time"] = start.result
        if end.available:
            params["end_time"] = end.result
            
        data = await make_api_request(
            "/api/hsn_history/minutely",
            params=params
        )
        
        if not data:
            await hsndata.send("❌ 未获取到数据")
            return
        
        # 格式化响应
        if isinstance(data, dict):
            success = data.get("success", False)
            if not success:
                error_msg = data.get("message", "未知错误")
                await hsndata.send(f"❌ {error_msg}")
                return
                
            history_data = data.get("data", [])
            count = data.get("count", len(history_data))
            start_time = data.get("start_time", "")
            end_time = data.get("end_time", "")
            
            message = f"📊 HSN历史数据\n"
            message += f"━━━━━━━━━━━━━━━━━━\n"
            message += f"📈 记录数: {count}\n"
            if start_time:
                message += f"⏰ 开始: {start_time}\n"
            if end_time:
                message += f"⏰ 结束: {end_time}\n"
            
            if history_data and len(history_data) > 0:
                message += f"\n前{min(5, len(history_data))}条记录:\n"
                for i, record in enumerate(history_data[:5], 1):
                    timestamp = record.get("timestamp", "")
                    online = record.get("online_users", 0)
                    message += f"{i}. {timestamp} - {online}人在线\n"
                
                if count > 5:
                    message += f"\n... 还有 {count - 5} 条记录"
        else:
            message = str(data)
            
        await hsndata.send(message)
        
    except Exception as e:
        logger.exception("获取HSN历史数据失败")
        await hsndata.send(create_error_message(e))


# 处理器3: 生成HSN图表
@hsndata.assign("chart")
async def handle_generate_chart(
    start: str,
    end: str
):
    """生成指定时段的HSN图表。"""
    logger.info(f"收到图表生成请求: {start} 到 {end}")
    
    try:
        params = {
            "start_time": start,
            "end_time": end
        }
        
        data = await make_api_request(
            "/api/generate_hsn_chart",
            params=params
        )
        
        if not data:
            await hsndata.send("❌ 图表生成失败")
            return
        
        # 解析响应
        if isinstance(data, dict):
            success = data.get("success", False)
            if success:
                message = "✅ 图表生成成功\n"
                message += "━━━━━━━━━━━━━━━━━━\n"
                if "filename" in data:
                    message += f"📁 文件名: {data['filename']}\n"
                if "start_time" in data:
                    message += f"⏰ 开始: {data['start_time']}\n"
                if "end_time" in data:
                    message += f"⏰ 结束: {data['end_time']}\n"
                message += "\n💡 提示: 使用 /hsndata charts 查看所有图表"
            else:
                error_msg = data.get("message", "未知错误")
                message = f"❌ 生成失败: {error_msg}"
        else:
            message = format_json_response(data)
            
        await hsndata.send(message)
        
    except Exception as e:
        logger.exception("生成图表失败")
        await hsndata.send(create_error_message(e))


# 处理器4: 列出所有图表
@hsndata.assign("charts")
async def handle_list_charts():
    """获取所有已生成图表的列表。"""
    logger.info("收到图表列表请求")
    
    try:
        data = await make_api_request("/api/hsn_charts_list")
        
        if not data:
            await hsndata.send("❌ 未获取到图表列表")
            return
        
        # 格式化图表列表
        if isinstance(data, dict):
            success = data.get("success", False)
            if not success:
                error_msg = data.get("message", "未知错误")
                await hsndata.send(f"❌ {error_msg}")
                return
                
            charts = data.get("charts", [])
            count = data.get("count", len(charts))
            
            if not charts:
                message = "📊 暂无生成的图表"
            else:
                message = f"📊 图表列表 (共{count}个)\n"
                message += "━━━━━━━━━━━━━━━━━━\n\n"
                for i, chart in enumerate(charts[:15], 1):
                    if isinstance(chart, dict):
                        filename = chart.get("filename", "未知")
                        start = chart.get("start_time", "")
                        end = chart.get("end_time", "")
                        message += f"{i}. {filename}\n"
                        if start and end:
                            message += f"   {start} ~ {end}\n"
                    else:
                        message += f"{i}. {chart}\n"
                
                if count > 15:
                    message += f"\n... 还有 {count - 15} 个图表"
        else:
            message = str(data)
            
        await hsndata.send(message)
        
    except Exception as e:
        logger.exception("获取图表列表失败")
        await hsndata.send(create_error_message(e))


# 处理器5: 获取图表图片(从本地文件读取)
@hsndata.assign("image")
async def handle_get_chart_image(chart_type: str):
    """
    从本地文件夹读取并发送图表图片。
    
    支持的类型:
    - hsn: HSN在线人数趋势图
    - room: 房间使用排名图
    - user_bar: 用户游玩时间柱状图
    - user_pie: 用户游玩时间饼图
    """
    logger.info(f"收到图表图片请求: {chart_type}")
    
    # 验证图表类型
    if chart_type not in CHART_MAPPING:
        await hsndata.send(
            f"❌ 未知的图表类型: {chart_type}\n\n"
            f"可用类型:\n"
            f"• hsn - HSN在线趋势\n"
            f"• room - 房间排名\n"
            f"• user_bar - 用户柱状图\n"
            f"• user_pie - 用户饼图"
        )
        return
    
    filename = CHART_MAPPING[chart_type]
    chart_file = CHART_PATH / filename
    
    try:
        # 检查文件是否存在
        if not chart_file.exists():
            await hsndata.send(
                f"❌ 图表文件不存在: {filename}\n\n"
                f"💡 提示: \n"
                f"1. 确认图表文件夹路径正确\n"
                f"2. 使用 /hsndata generate 触发图表生成\n"
                f"3. 当前路径: {chart_file.absolute()}"
            )
            return
        
        # 读取本地图表文件
        image_data = chart_file.read_bytes()
        
        # 发送图片及说明
        type_name = {
            "hsn": "HSN在线人数趋势",
            "room": "房间使用排名",
            "user_bar": "用户游玩时间(柱状图)",
            "user_pie": "用户游玩时间(饼图)"
        }.get(chart_type, chart_type)
        
        msg = Message([
            MessageSegment.text(f"📊 {type_name}\n"),
            MessageSegment.image(image_data)
        ])
        
        await hsndata.send(msg)
        
    except Exception as e:
        logger.exception(f"读取图表文件失败: {chart_file}")
        await hsndata.send(f"❌ 读取图表失败: {str(e)}")


# 处理器6: 房间使用排名
@hsndata.assign("roomrank")
async def handle_room_ranking():
    """获取房间使用次数排名。"""
    logger.info("收到房间排名请求")
    
    try:
        data = await make_api_request("/api/room_usage_ranking")
        
        if not data:
            await hsndata.send("❌ 未获取到房间排名数据")
            return
        
        # 格式化排名数据
        if isinstance(data, dict):
            success = data.get("success", False)
            if not success:
                error_msg = data.get("message", "未知错误")
                await hsndata.send(f"❌ {error_msg}")
                return
            
            # API返回的是data字段
            rankings = data.get("data", [])
            count = data.get("count", len(rankings))
            
            if not rankings:
                message = "🏠 暂无房间使用数据"
            else:
                message = "🏠 房间使用排名\n"
                message += "━━━━━━━━━━━━━━━━━━\n\n"
                
                for i, room in enumerate(rankings[:10], 1):
                    if isinstance(room, dict):
                        name = room.get("room_name", "未知")
                        usage = room.get("usage_count", 0)
                        message += f"{i}. {name}\n"
                        message += f"   使用次数: {usage}\n"
                    else:
                        message += f"{i}. {room}\n"
                
                if count > 10:
                    message += f"\n... 还有 {count - 10} 个房间"
        else:
            message = str(data)
            
        await hsndata.send(message)
        
    except Exception as e:
        logger.exception("获取房间排名失败")
        await hsndata.send(create_error_message(e))


# 处理器7: 用户游玩时间排名（支持查询指定用户）
@hsndata.assign("userrank")
async def handle_user_ranking(user_id: Match[int]):
    """
    获取用户游玩时间排名，或查询指定用户数据。
    如果提供user_id，则查询该用户的详细数据。
    否则显示所有用户排名。
    """
    logger.info(f"收到用户排名请求，用户ID: {user_id.result if user_id.available else '全部'}")
    
    try:
        # 如果指定了用户ID，查询单个用户数据
        if user_id.available and user_id.result:
            await handle_single_user_query(user_id.result)
            return
        
        # 否则获取所有用户排名
        data = await make_api_request("/api/user_playtime_ranking")
        
        if not data:
            await hsndata.send("❌ 未获取到用户排名数据")
            return
        
        # 格式化排名数据
        if isinstance(data, dict):
            success = data.get("success", False)
            if not success:
                error_msg = data.get("message", "未知错误")
                await hsndata.send(f"❌ {error_msg}")
                return
            
            # API返回的是data字段
            rankings = data.get("data", [])
            count = data.get("count", len(rankings))
            
            if not rankings:
                message = "👥 暂无用户游戏时长数据"
            else:
                message = "👥 用户游戏时长排名\n"
                message += "━━━━━━━━━━━━━━━━━━\n\n"
                medals = ["🥇", "🥈", "🥉"]
                
                # 批量获取用户名
                for i, user in enumerate(rankings[:10], 1):
                    medal = medals[i-1] if i <= 3 else f"{i}."
                    
                    if isinstance(user, dict):
                        uid = user.get("user_id", 0)
                        playtime_sec = user.get("playtime_seconds", 0)
                        playtime_hrs = user.get("playtime_hours", 0)
                        
                        # 获取用户名
                        username = await get_username_from_phira(uid)
                        
                        message += f"{medal} {username}\n"
                        message += f"   游玩时长: {playtime_hrs:.1f}小时 ({playtime_sec}秒)\n"
                    else:
                        message += f"{medal} {user}\n"
                
                if count > 10:
                    message += f"\n... 还有 {count - 10} 个用户"
                
                message += f"\n\n💡 提示: 使用 /hsndata userrank <用户ID> 查询指定用户"
        else:
            message = str(data)
            
        await hsndata.send(message)
        
    except Exception as e:
        logger.exception("获取用户排名失败")
        await hsndata.send(create_error_message(e))


async def handle_single_user_query(user_id: int):
    """
    查询指定用户的游玩数据。
    
    Args:
        user_id: 用户ID
    """
    logger.info(f"查询用户 {user_id} 的数据")
    
    try:
        # 从排行榜API获取所有用户数据
        data = await make_api_request("/api/playtime_leaderboard")
        
        if not data or not isinstance(data, dict):
            await hsndata.send("❌ 未获取到用户数据")
            return
        
        success = data.get("success", False)
        if not success:
            error_msg = data.get("message", "未知错误")
            await hsndata.send(f"❌ {error_msg}")
            return
        
        leaderboard = data.get("data", [])
        total_users = data.get("total_users", len(leaderboard))
        
        # 查找指定用户
        user_data = None
        user_rank = 0
        for i, user in enumerate(leaderboard, 1):
            if isinstance(user, dict) and user.get("user_id") == user_id:
                user_data = user
                user_rank = i
                break
        
        if not user_data:
            await hsndata.send(f"❌ 未找到用户ID为 {user_id} 的数据")
            return
        
        # 获取用户名
        username = await get_username_from_phira(user_id)
        
        # 格式化用户数据
        # total_playtime 单位是秒
        playtime_sec = user_data.get("total_playtime", 0)
        
        # 计算时分秒
        hours = int(playtime_sec // 3600)
        minutes = int((playtime_sec % 3600) // 60)
        seconds = int(playtime_sec % 60)
        playtime_hrs = playtime_sec / 3600
        
        message = f"👤 用户数据查询\n"
        message += "━━━━━━━━━━━━━━━━━━\n\n"
        message += f"🆔 用户ID: {user_id}\n"
        message += f"👤 用户名: {username}\n"
        message += f"🏆 排名: 第 {user_rank} 名 (共{total_users}人)\n\n"
        message += f"⏱️ 游玩时长:\n"
        message += f"  • {playtime_hrs:.2f} 小时\n"
        message += f"  • {hours}小时 {minutes}分钟 {seconds}秒\n"
        message += f"  • {playtime_sec} 秒\n"
        
        await hsndata.send(message)
        
    except Exception as e:
        logger.exception(f"查询用户 {user_id} 失败")
        await hsndata.send(create_error_message(e))


# 处理器8: 手动触发图表生成
@hsndata.assign("generate")
async def handle_trigger_generation():
    """手动触发图表生成流程。"""
    logger.info("收到手动图表生成触发请求")
    
    try:
        data = await make_api_request(
            "/api/generate_charts",
            method="POST"
        )
        
        if not data:
            await hsndata.send("❌ 图表生成触发失败")
            return
        
        # 解析响应
        if isinstance(data, dict):
            success = data.get("success", False)
            if success:
                message = "✅ 图表生成已触发\n"
                message += "━━━━━━━━━━━━━━━━━━\n"
                if "message" in data:
                    message += f"ℹ️ {data['message']}"
            else:
                error_msg = data.get("message", "未知错误")
                message = f"❌ 触发失败: {error_msg}"
        else:
            message = format_json_response(data)
            
        await hsndata.send(message)
        
    except Exception as e:
        logger.exception("触发图表生成失败")
        await hsndata.send(create_error_message(e))


# 处理器9: 游玩时间排行榜
@hsndata.assign("leaderboard")
async def handle_leaderboard(limit: Match[int]):
    """获取游玩时间排行榜，支持可选的前N名限制。"""
    logger.info(f"收到排行榜请求，限制: {limit.result if limit.available else '全部'}")
    
    try:
        # 决定使用哪个端点
        if limit.available and limit.result and limit.result > 0:
            endpoint = f"/api/playtime_leaderboard/top/{limit.result}"
        else:
            endpoint = "/api/playtime_leaderboard"
        
        data = await make_api_request(endpoint)
        
        if not data:
            await hsndata.send("❌ 未获取到排行榜数据")
            return
        
        # 格式化排行榜
        if isinstance(data, dict):
            success = data.get("success", False)
            if not success:
                error_msg = data.get("message", "未知错误")
                await hsndata.send(f"❌ {error_msg}")
                return
            
            # API返回的是data字段
            leaderboard = data.get("data", [])
            total_users = data.get("total_users", len(leaderboard))
            timestamp = data.get("timestamp", "")
            
            if not leaderboard:
                message = "🏆 排行榜暂无数据"
            else:
                limit_text = f"Top {limit.result}" if limit.available else "完整"
                message = f"🏆 游戏时长排行榜 ({limit_text})\n"
                message += "━━━━━━━━━━━━━━━━━━\n"
                if timestamp:
                    message += f"⏰ 更新时间: {timestamp}\n"
                message += f"👥 总用户数: {total_users}\n\n"
                
                medals = ["🥇", "🥈", "🥉"]
                
                # 批量获取用户名并显示
                for i, player in enumerate(leaderboard, 1):
                    medal = medals[i-1] if i <= 3 else f"{i}."
                    
                    if isinstance(player, dict):
                        uid = player.get("user_id", 0)
                        playtime = player.get("total_playtime", 0)
                        
                        # 获取用户名
                        username = await get_username_from_phira(uid)
                        
                        # 格式化游玩时间(假设单位为秒)
                        hours = int(playtime // 3600)
                        minutes = int((playtime % 3600) // 60)
                        
                        message += f"{medal} {username}\n"
                        message += f"   {hours}小时{minutes}分钟 ({playtime}秒)\n"
                    else:
                        message += f"{medal} {player}\n"
                
                shown = len(leaderboard)
                if total_users > shown:
                    message += f"\n显示 {shown}/{total_users} 个玩家"
        else:
            message = str(data)
            
        await hsndata.send(message)
        
    except Exception as e:
        logger.exception("获取排行榜失败")
        await hsndata.send(create_error_message(e))


# ============================================================================
# 默认处理器 (无子命令时显示帮助)
# ============================================================================

@hsndata.handle()
async def handle_default(result: Arparma = AlconnaMatches()):
    """处理无子命令的主命令 - 显示帮助信息。"""
    if not result.matched or not result.subcommands:
        help_text = """
📊 HSN数据监控系统

━━━━━━━━━━━━━━━━━━━━━━━━

📋 可用命令:

【基础功能】
  /hsndata health
    └─ 检查服务状态

【数据查询】
  /hsndata history [开始] [结束]
    └─ 获取历史数据
  /hsndata roomrank
    └─ 房间使用排名
  /hsndata userrank [用户ID]
    └─ 用户时长排名或查询指定用户
  /hsndata leaderboard [数量](必须)
    └─ 游戏时长排行榜

【图表功能】
  /hsndata chart <开始> <结束>
    └─ 生成指定时段图表
  /hsndata charts
    └─ 列出所有图表
  /hsndata image <类型>
    └─ 获取图表图片(从本地)
    类型: hsn | room | user_bar | user_pie
  /hsndata generate
    └─ 触发图表生成

━━━━━━━━━━━━━━━━━━━━━━━━

💡 示例:
  /hsndata health
  /hsndata history "2025-10-01 00:00:00" "2025-10-06 23:59:59"
  /hsndata image hsn
  /hsndata userrank
  /hsndata userrank 12345
  /hsndata leaderboard 10

⏰ 时间格式: YYYY-MM-DD HH:MM:SS
        """
        await hsndata.send(help_text.strip())