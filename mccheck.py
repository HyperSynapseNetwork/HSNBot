from nonebot import require
require("nonebot_plugin_alconna")
require("nonebot_plugin_htmlrender")
from nonebot.plugin import PluginMetadata
from mcstatus import JavaServer
from nonebot_plugin_alconna import Alconna, Command, on_alconna
from nonebot.adapters.onebot.v11 import MessageSegment
import asyncio
from datetime import datetime
import logging
from nonebot_plugin_htmlrender import html_to_pic



logger = logging.getLogger(__name__)

__plugin_meta__ = PluginMetadata(
    name="Minecraft服务器状态查询",
    description="通过mcstatus获取服务器状态并渲染成图片",
    usage="/mcstatus",
)

mcstatus_cmd = Command("mcstatus")
mcstatus = on_alconna("mcstatus", priority=10, block=True)

@mcstatus.handle()
async def handle_mcstatus():
    try:
        server_info = await get_server_status("play.simpfun.cn", 27098)
        
        html_content = generate_html(server_info)
        image = await html_to_pic(html_content, viewport={"width": 600, "height": 800})
        
        await mcstatus.send(MessageSegment.image(image))
        
    except Exception as e:
        logger.error(f"处理服务器状态请求时出错: {str(e)}")
        await mcstatus.send(f"处理请求时出错: {str(e)}")

async def get_server_status(host: str, port: int) -> dict:
    
    server = JavaServer.lookup(f"{host}:{port}")
    try:
        status = await asyncio.to_thread(server.status)
        return {
            "host": host,
            "port": port,
            "version": status.version.name,
            "players": f"{status.players.online}/{status.players.max}",
            "motd": status.description,
            "latency": f"{status.latency:.2f}ms",
            "players_list": [p.name for p in status.players.sample] if status.players.sample else [],
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        return {
            "host": host,
            "port": port,
            "error": f"服务器查询失败: {str(e)}",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

def generate_html(data: dict) -> str:
    
    if "error" in data:
        return f"""
        <div style="
            background: linear-gradient(135deg, #2c3e50, #4a235a);
            color: white;
            padding: 25px;
            border-radius: 12px;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            box-shadow: 0 8px 16px rgba(0,0,0,0.3);
            max-width: 600px;
        ">
            <div style="
                background: rgba(0,0,0,0.7);
                border-radius: 8px;
                padding: 20px;
                backdrop-filter: blur(5px);
            ">
                <div style="display: flex; align-items: center; margin-bottom: 20px;">
                    <div style="
                        width: 80px;
                        height: 80px;
                        background: url('https://api.iconify.design/mdi:alert-circle.svg') center/contain no-repeat;
                        margin-right: 20px;
                        filter: invert(1);
                    "></div>
                    <div>
                        <h1 style="margin:0; font-size:28px; color:#ff6b6b;">服务器状态查询失败</h1>
                        <h2 style="margin:0; font-size:18px; color:#aaa;">{data['host']}:{data['port']}</h2>
                    </div>
                </div>
                
                <div style="background: rgba(180,70,70,0.5); padding: 15px; border-radius: 8px; margin-bottom: 20px;">
                    <h3 style="margin-top:0; color:#ffaaaa;">错误信息</h3>
                    <p style="font-size:18px;">{data['error']}</p>
                </div>
                
                <div style="text-align: right; color: #aaa; font-size: 14px;">
                    查询时间: {data['timestamp']}
                </div>
            </div>
        </div>
        """
    
    players_list = "\n".join(
        f'<li style="margin:5px; padding:5px; background-color:#e9ecef; border-radius:4px; color:#333;">{player}</li>' 
        for player in data["players_list"]
    ) if data["players_list"] else '<p style="color:#aaa;">无在线玩家信息</p>'
    
    return f"""
    <div style="
        background: linear-gradient(135deg, #1a2a6c, #b21f1f, #1a2a6c);
        color: white;
        padding: 25px;
        border-radius: 12px;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        box-shadow: 0 8px 16px rgba(0,0,0,0.3);
        max-width: 600px;
    ">
        <div style="
            background: rgba(0,0,0,0.7);
            border-radius: 8px;
            padding: 20px;
            backdrop-filter: blur(5px);
        ">
            <div style="display: flex; align-items: center; margin-bottom: 20px;">
                <div style="
                    width: 80px;
                    height: 80px;
                    background: url('https://api.iconify.design/mdi:minecraft.svg') center/contain no-repeat;
                    margin-right: 20px;
                "></div>
                <div>
                    <h1 style="margin:0; font-size:28px;">HSNMC服务器状态</h1>
                    <h2 style="margin:0; font-size:22px; color:#ffcc00;">{data['host']}:{data['port']}</h2>
                </div>
            </div>
            
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 20px;">
                <div style="background: rgba(0,100,0,0.5); padding: 15px; border-radius: 8px;">
                    <h3 style="margin-top:0; color:#aaffaa;">服务器版本</h3>
                    <p style="font-size:20px;">{data['version']}</p>
                </div>
                
                <div style="background: rgba(70,70,180,0.5); padding: 15px; border-radius: 8px;">
                    <h3 style="margin-top:0; color:#aaaaff;">在线玩家</h3>
                    <p style="font-size:20px;">{data['players']}</p>
                </div>
                
                <div style="background: rgba(180,70,70,0.5); padding: 15px; border-radius: 8px;">
                    <h3 style="margin-top:0; color:#ffaaaa;">网络延迟</h3>
                    <p style="font-size:20px;">{data['latency']}</p>
                </div>
            </div>
            
            <div style="background: rgba(30,30,30,0.7); padding: 15px; border-radius: 8px; margin-bottom: 20px;">
                <h3 style="margin-top:0; color:#ffffaa;">服务器描述</h3>
                <p style="font-size:18px;">{data['motd']}</p>
            </div>
            
            <div style="background: rgba(30,30,30,0.7); padding: 15px; border-radius: 8px; margin-bottom: 20px;">
                <h3 style="margin-top:0; color:#aaffff;">在线玩家列表</h3>
                <ul style="
                    columns: 2;
                    column-gap: 20px;
                    padding-left: 20px;
                    max-height: 200px;
                    overflow-y: auto;
                ">{players_list}</ul>
            </div>
            
            <div style="text-align: right; color: #aaa; font-size: 14px;">
                查询时间: {data['timestamp']}
            </div>
        </div>
    </div>
    """