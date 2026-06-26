from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.plugin import on_command
from nonebot.params import CommandArg
import subprocess

restart = on_command("restart", priority=5, block=True)

@restart.handle()
async def handle_restart(event: GroupMessageEvent, args: Message = CommandArg()):
    # 添加调试日志
    
    # 检查发送者是否为群主或管理员
    if event.sender.role not in ["owner", "admin"]:
        await restart.send("注意：仅限管理员与群主可使用此命令。")
        return  # 确保函数结束
    
    arg_text = args.extract_plain_text().strip()
    
    try:
        if arg_text == "api":
            # 执行 API 重启命令
            result1 = subprocess.run(["bash", "/root/botstopapi.sh"], capture_output=True, text=True)
            result2 = subprocess.run(["bash", "/root/startapi.sh"], capture_output=True, text=True)
            
            if result2.returncode == 0:
                await restart.send("API重启成功")
            else:
                await restart.send(f"API重启失败：{result2.stderr}")
        else:
            # 执行普通重启命令
            result1 = subprocess.run(["screen", "-S", "Phiranew", "-X", "quit"], capture_output=True, text=True)
            result2 = subprocess.run(["bash", "/root/startnew.sh"], capture_output=True, text=True)
            
            if result2.returncode == 0:
                await restart.send("重启Phira服务器成功")
            else:
                await restart.send(f"重启Phira服务器失败：{result2.stderr}")
            
    except Exception as e:
        await restart.send(f"出现致命错误（bushi）：{str(e)}")