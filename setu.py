from nonebot import require, get_driver
from nonebot.plugin import PluginMetadata
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11 import Message, MessageSegment, Bot
from arclet.alconna import Alconna, Args, CommandMeta
from nonebot_plugin_alconna import on_alconna, AlconnaMatch, Match
from typing import Optional
import aiohttp
import json
import asyncio

require("nonebot_plugin_alconna")

# 全局变量：撤回延迟时间（秒）
WITHDRAW_DELAY = 10

__plugin_meta__ = PluginMetadata(
    name="色图插件",
    description="通过Lolicon API获取色图，自动撤回",
    usage="/setu",
    type="application",
    supported_adapters={"~onebot.v11"},
)

setu_cmd = on_alconna(
    Alconna(
        "setu",
        Args["keyword?", str],
        meta=CommandMeta(
            description="获取一张随机色图",
            example="/setu",
        ),
    ),
    aliases={"/setu", "色图", "来张色图"},
    block=True,
)

async def fetch_setu_url() -> Optional[str]:
    """从Lolicon API获取图片URL"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.lolicon.app/setu/v2",
                params={"proxy": 0},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                
                # 解析返回的JSON数据
                if data.get("error"):
                    return None
                
                data_list = data.get("data", [])
                if not data_list:
                    return None
                
                urls = data_list[0].get("urls", {})
                return urls.get("original")
    except Exception:
        return None

async def download_image(url: str) -> Optional[bytes]:
    """下载图片并返回二进制数据"""
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"referer": "https://www.pixiv.net/"}
            async with session.get(
                url, 
                headers=headers, 
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    return await resp.read()
                return None
    except Exception:
        return None

async def withdraw_message(bot: Bot, event, message_id: int):
    """撤回消息"""
    try:
        await asyncio.sleep(WITHDRAW_DELAY)
        await bot.delete_msg(message_id=message_id)
    except Exception as e:
        # 撤回失败可能的原因：消息已过期、权限不足等
        print(f"撤回消息失败: {e}")

@setu_cmd.handle()
async def handle_setu(bot: Bot, event, keyword: Match[str] = AlconnaMatch("keyword")):
    # 发送请求提示
    await setu_cmd.send("正在获取图片，请稍等...")
    
    # 获取图片URL
    image_url = await fetch_setu_url()
    if not image_url:
        await setu_cmd.finish("获取图片失败，请稍后重试")
    
    # 下载图片
    image_data = await download_image(image_url)
    if not image_data:
        await setu_cmd.finish("下载图片失败，请稍后重试")
    
    # 发送图片
    try:
        # 发送图片并获取消息ID
        result = await setu_cmd.send(MessageSegment.image(image_data))
        
        # 启动撤回任务
        if hasattr(result, 'message_id'):
            message_id = result.message_id
        elif isinstance(result, dict) and 'message_id' in result:
            message_id = result['message_id']
        else:
            # 如果无法获取消息ID，尝试从事件中获取最后一条消息的ID
            message_id = getattr(event, 'message_id', None)
        
        if message_id:
            # 创建异步任务，在指定时间后撤回消息
            asyncio.create_task(withdraw_message(bot, event, message_id))
            # 发送提示信息，告知用户图片将在指定时间后撤回
            notice_msg = f"图片将在 {WITHDRAW_DELAY} 秒后撤回"
            await setu_cmd.send(notice_msg)
        else:
            await setu_cmd.send("无法获取消息ID，撤回功能可能无法正常工作")
            
    except Exception as e:
        await setu_cmd.finish(f"发送图片失败: {e}")