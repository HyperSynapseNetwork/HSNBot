from nonebot import require
require("nonebot_plugin_alconna")
from nonebot_plugin_alconna import Alconna, Args, Option, on_alconna, AlconnaQuery, Query
from nonebot.plugin import PluginMetadata
from nonebot.params import Arg
from nonebot.adapters.onebot.v11 import MessageSegment, Message
from arclet.alconna import CommandMeta
import aiohttp
import json

__plugin_meta__ = PluginMetadata(
    name="用户数量查询",
    description="查询服务器当前用户数量",
    usage="/users - 获取服务器当前用户数量",
)

users_cmd = on_alconna(
    Alconna(
        "users",
        meta=CommandMeta(description="获取本phira服务器玩家总数"),
    ),
    aliases={"用户数量", "在线人数"},
    block=True,
    use_cmd_start=True
)

@users_cmd.handle()
async def handle_users():
    try:
        # 创建异步
        async with aiohttp.ClientSession() as session:
            # 发送GET请求
            async with session.get('http://154.64.253.143:5001/users') as response:
                if response.status == 200:
                    data = await response.json()
                    user_count = data.get('total_online_users', '未知')
                    
                    await users_cmd.send(f"本群Phira服务器现在有{user_count}个人")
                else:
                    await users_cmd.send("获取服务器状态失败，请联系群主")
    except aiohttp.ClientError:
        await users_cmd.send("服务器暴晒炸了")
    except json.JSONDecodeError:
        await users_cmd.send("服务器被攻击了")
    except Exception as e:
        await users_cmd.send(f"未知错误: {str(e)}")