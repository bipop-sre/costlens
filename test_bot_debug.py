#!/usr/bin/env python3
"""Debug script to see raw message structure from WeChat Bot."""

import asyncio
import sys
import json
from wecom_aibot_sdk import WSClient, WSClientOptions

BOT_ID = "aibriQF96EC4CIG78qegvLabSLnAqHxesmn"
SECRET = "iTht7j808FaBMos74DebqIQSHP76Vy6M8qPi30THf1Q"

async def main():
    print("=" * 60)
    print("WeChat Bot Debug - Raw Message Structure")
    print("=" * 60)
    
    options = WSClientOptions(
        bot_id=BOT_ID,
        secret=SECRET,
        max_reconnect_attempts=3,
        reconnect_interval=2000,
    )
    
    client = WSClient(options)
    
    async def handle_message(frame):
        print("\n" + "=" * 60)
        print("📨 MESSAGE RECEIVED")
        print("=" * 60)
        print(f"Frame headers: {frame.headers}")
        print(f"Frame cmd: {frame.cmd}")
        print(f"Frame body type: {type(frame.body)}")
        print(f"Frame body (raw): {json.dumps(frame.body, ensure_ascii=False, indent=2)}")
        
        # Try to parse
        body = frame.body
        if isinstance(body, dict):
            print(f"\nbody.get('content'): {body.get('content')}")
            print(f"body.get('text'): {body.get('text')}")
            print(f"body.get('chatid'): {body.get('chatid')}")
            print(f"body.get('from'): {body.get('from')}")
            print(f"body.get('from_userid'): {body.get('from_userid')}")
        
        # Try to reply
        try:
            await client.reply(
                frame.headers,
                {"msgtype": "markdown", "markdown": {"content": "✅ 收到消息！"}},
                "aibot_respond_msg",
            )
            print("✅ Reply sent successfully")
        except Exception as e:
            print(f"❌ Reply failed: {e}")
    
    async def handle_enter(frame):
        print("\n" + "=" * 60)
        print("👤 USER ENTERED CHAT")
        print("=" * 60)
        print(f"Frame body: {json.dumps(frame.body, ensure_ascii=False, indent=2)}")
    
    client.on("message.text", handle_message)
    client.on("event.enter_chat", handle_enter)
    
    try:
        print("\nConnecting...")
        await client.connect_async()
        await asyncio.sleep(2)
        
        if client.is_authenticated:
            print("✅ Connected and authenticated!")
            print("\n请发送消息到机器人，查看消息结构...")
            print("按 Ctrl+C 退出\n")
            
            while True:
                await asyncio.sleep(1)
        else:
            print("❌ Authentication failed")
            return 1
    except KeyboardInterrupt:
        print("\n\nStopping...")
    finally:
        await client.disconnect()
    
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
