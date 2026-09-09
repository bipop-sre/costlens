#!/usr/bin/env python3
"""
Test script for WeChat Work intelligent bot connection.

Usage:
    python test_wechat_bot.py

This will:
1. Connect to WeChat Work via WebSocket
2. Wait for messages from users
3. Reply with a test message

If you see "Authenticated: True", the connection is working.
Then try sending a message to the bot in WeChat Work.
"""
import asyncio
import sys
from wecom_aibot_sdk import WSClient, WSClientOptions

# Your bot credentials
BOT_ID = "aibriQF96EC4CIG78qegvLabSLnAqHxesmn"
SECRET = "R9KNFfptaiL2xbe6d6hWMTYBBekhbVccAnTowQTbvjX"

async def main():
    print("=" * 60)
    print("WeChat Work Intelligent Bot Connection Test")
    print("=" * 60)
    print(f"Bot ID: {BOT_ID[:20]}...")
    print(f"Secret: {SECRET[:20]}...")
    print()
    
    options = WSClientOptions(
        bot_id=BOT_ID,
        secret=SECRET,
        max_reconnect_attempts=3,
        reconnect_interval=2000,
    )
    
    client = WSClient(options)
    
    async def handle_message(frame):
        body = frame.body
        chatid = body.get("chatid", "unknown")
        content = body.get("content", "")
        print(f"\n✅ Received message from {chatid}: {content}")
        
        try:
            await client.reply(
                frame.headers,
                {
                    "msgtype": "markdown",
                    "markdown": {
                        "content": "## ✅ 连接成功\n\nCostLens AI Agent 已成功连接到企业微信智能机器人！"
                    }
                },
                "aibot_respond_msg",
            )
            print("✅ Reply sent successfully")
        except Exception as e:
            print(f"❌ Failed to reply: {e}")
    
    async def handle_enter(frame):
        chatid = frame.body.get("chatid", "unknown")
        print(f"\n✅ User entered chat: {chatid}")
    
    client.on("message.text", handle_message)
    client.on("event.enter_chat", handle_enter)
    
    try:
        print("Connecting to WeChat Work...")
        await client.connect_async()
        
        await asyncio.sleep(2)
        
        print(f"Connected: {client.is_connected}")
        print(f"Authenticated: {client.is_authenticated}")
        print()
        
        if client.is_authenticated:
            print("✅✅✅ SUCCESS! Bot is ready and authenticated.")
            print()
            print("Now go to WeChat Work and send a message to the bot.")
            print("The bot will reply with a test message.")
            print()
            print("Press Ctrl+C to stop...")
            print()
            
            # Keep running indefinitely
            while True:
                await asyncio.sleep(1)
        else:
            print("❌ FAILED! Authentication failed.")
            print()
            print("Please check:")
            print("1. Bot ID and Secret are correct")
            print("2. Bot is configured in '长连接' (long connection) mode")
            print("3. Bot is properly created in WeChat Work admin console")
            return 1
        
    except KeyboardInterrupt:
        print("\n\nStopping...")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        await client.disconnect()
        print("Disconnected")
    
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
