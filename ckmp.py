from nonebot.plugin import PluginMetadata
from nonebot import get_driver
from arclet.alconna import Alconna, CommandMeta
from nonebot_plugin_alconna import on_alconna
from nonebot.adapters.onebot.v11 import Message
import aiohttp
import asyncio
import json

# 全局变量 - 在这里修改用户名和密码
USERNAME = "YOUR_FUCKING_EMAIL"
PASSWORD = "YOUR_FUCKING_PASSWORD"

# 插件元信息
__plugin_meta__ = PluginMetadata(
    name="CK服务器检查器",
    description="检查CK服务器状态的插件",
    usage="/cksvr - 检查服务器状态",
    type="application",
    homepage="https://github.com/your-repo",
    supported_adapters={"onebot.v11"},
)

# 创建Alconna命令
cksvr_cmd = Alconna(
    "/cksvr",
    meta=CommandMeta(
        description="检查CK服务器状态",
        usage="/cksvr",
        example="/cksvr"
    )
)

# 创建命令处理器
cksvr = on_alconna(cksvr_cmd, aliases={"/cksvr"}, priority=10, block=True)

@cksvr.handle()
async def handle_cksvr():
    reader = None
    writer = None
    
    # 第一步：发送POST请求获取token
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
    
    # 第二步：将token转换为hex
        token_hex = token.encode('utf-8').hex()
    
    # 第三步：建立TCP连接
    try:
        reader, writer = await asyncio.open_connection(
            'service.htadiy.com', 7865
        )
    except ConnectionRefusedError:
        await cksvr.finish("❌ 服务器异常：连接被拒绝，服务器可能根本没开")
    except OSError as e:
        if e.errno == 111:  # 连接被拒绝的错误码
            await cksvr.finish("❌ 服务器异常：连接被拒绝，可能服务器可能根本没开")
        else:
            await cksvr.finish(f"❌ 网络异常: {str(e)}")
    except Exception as e:
        await cksvr.send(f"❌ 握手时发生未知错误: {str(e)}")
    
    # 只有在连接成功后才执行以下代码
    try:
        # 构造数据包：01 22 01 20 + hex(token)
        header = bytes.fromhex('01160114')
        token_bytes = bytes.fromhex(token_hex)
        packet = header + token_bytes
        
        # 发送数据包
        writer.write(packet)
        await writer.drain()
        
        # 设置超时等待响应
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
        # 确保在连接成功的情况下关闭连接
        if writer and not writer.is_closing():
            writer.close()
            await writer.wait_closed()

# 配置加载时的提示
driver = get_driver()

@driver.on_startup
async def startup():
    print("CK服务器检查器插件已加载")
    print(f"当前用户名: {USERNAME}")
    print("注意：请确保在代码中修改USERNAME和PASSWORD全局变量")

@driver.on_shutdown
async def shutdown():
    print("CK服务器检查器插件已卸载")
