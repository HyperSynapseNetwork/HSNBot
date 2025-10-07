from nonebot import require, get_driver
require("nonebot_plugin_alconna")
from nonebot.plugin import PluginMetadata
from nonebot_plugin_alconna import on_alconna, Alconna, Args, Match, UniMessage
from playwright.async_api import async_playwright
from arclet.alconna import CommandMeta
import asyncio
import os



__plugin_meta__ = PluginMetadata(
    name="Phira房间截图工具",
    description="通过/room指令获取Phira房间列表截图",
    usage="/room [等待秒数] - 获取房间列表截图\n可添加等待秒数参数让页面加载更长时间",
    config=None,
    extra={
        "example": "/room 3\n房间 5\n房间列表"
    }
)


room_cmd = on_alconna(
    Alconna(
        "room",
        Args["wait_second?", int],
        meta=CommandMeta(description="获取在线房间列表"),
    ),
    aliases={"房间", "房间列表"},
    use_cmd_start=True,
    auto_send_output=True
)


BROWSER_PATH = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", None)

async def capture_phira_screenshot(wait_second: int = 0) -> bytes:
    """使用Playwright"""
    async with async_playwright() as p:
        
        browser = await p.chromium.launch(
            executable_path=BROWSER_PATH,
            args=["--disable-gpu", "--no-sandbox"] if BROWSER_PATH else None
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            device_scale_factor=1.0  
        )
        page = await context.new_page()
        
        try:
            
            await page.goto(
                "https://phira.htadiy.cc/rooms.html",
                wait_until="networkidle",
                timeout=20000
            )
            
            
            await asyncio.sleep(wait_second)
            
            
            screenshot = await page.screenshot(
                full_page=False,
                type="jpeg"
            )
            return screenshot
        except Exception as e:
            raise RuntimeError(f"截图失败: {str(e)}")
        finally:
            await browser.close()

@room_cmd.handle()
async def handle_room_cmd(wait_second: Match[int]):
    
    wait = wait_second.result if wait_second.available else 0
    
    
    if wait < 0 or wait > 30:
        await room_cmd.finish("响应超时")
    
    try:
        
        await room_cmd.send("正在获取房间列表截图，请稍候...")
        
        
        screenshot = await capture_phira_screenshot(wait)
        
        
        await UniMessage.image(raw=screenshot).send()
    except Exception as e:
        await room_cmd.finish(f"❌ 截图失败: {str(e)}\n请稍后再试或联系管理员进行处理。")


driver = get_driver()
@driver.on_shutdown
async def close_playwright():
    
    pass