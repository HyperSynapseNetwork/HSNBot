from nonebot.plugin import PluginMetadata
from nonebot import get_driver
from arclet.alconna import Alconna, CommandMeta
from nonebot_plugin_alconna import on_alconna
from nonebot.adapters.onebot.v11 import Message
import aiohttp
import asyncio
import json

USERNAME = "fucked"
PASSWORD = "fucked"


cksvr_cmd = Alconna(
    "/cksvr",
    meta=CommandMeta(
        description="检查CK服务器状态",
        usage="/cksvr",
        example="/cksvr"
    )
)

cksvr = on_alconna(cksvr_cmd, aliases={"/cksvr"}, priority=10, block=True)

@cksvr.handle()
async def handle_cksvr():
    reader = None
    writer = None
    
    async with aiohttp.ClientSession() as session:
        login_data = {
            "email": USERNAME,
            "password": PASSWORD
        }
        
        try:
            async with session.post(
                "https://phira.5wyxi.com/login", 
                json=login_data,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status != 200:
                    await cksvr.send(f"登录失败，状态码: {response.status}")
                
                result = await response.json()
                token = result.get("token")
                
                if not token:
                    await cksvr.send("获取token失败，请检查请求参数")
        except aiohttp.ClientError as e:
            await cksvr.send(f"❌ 网络异常: {str(e)}")
        except asyncio.TimeoutError as e:
            await cksvr.send(f"❌ 连接超时: {str(e)}")
        except Exception as e:
            await cksvr.send(f"❌ 登录时发生未知错误: {str(e)}")
    
    token_hex = token.encode('utf-8').hex()
    
    try:
        reader, writer = await asyncio.open_connection(
            'service.htadiy.cc', 7865
        )
    except ConnectionRefusedError:
        await cksvr.finish("❌ 服务器异常：连接被拒绝，服务器可能根本没开")
    except OSError as e:
        if e.errno == 111:  
            await cksvr.finish("❌ 服务器异常：连接被拒绝，可能服务器可能根本没开")
        else:
            await cksvr.finish(f"❌ 网络异常: {str(e)}")
    except Exception as e:
        await cksvr.send(f"❌ 握手时发生未知错误: {str(e)}")
    
    try:
        header = bytes.fromhex('01220120')
        token_bytes = bytes.fromhex(token_hex)
        packet = header + token_bytes
        
        writer.write(packet)
        await writer.drain()
        
        try:
            response = await asyncio.wait_for(reader.read(1024), timeout=5.0)
            if response:
                await cksvr.send("✅ 服务器正常")
            else:
                await cksvr.send("❌ 服务器假死了")
                
        except asyncio.TimeoutError:
            await cksvr.send("❌ 服务器假死了")
            
    except Exception as e:
        await cksvr.send(f"❌ 在发包时异常: {str(e)}")
    finally:
        if writer and not writer.is_closing():
            writer.close()
            await writer.wait_closed()

driver = get_driver()

@driver.on_startup
async def startup():
    print("CK服务器检查器插件已加载")
    print(f"当前用户名: {USERNAME}")
    print("注意：请确保在代码中修改USERNAME和PASSWORD全局变量")

@driver.on_shutdown
async def shutdown():
    print("CK服务器检查器插件已卸载")