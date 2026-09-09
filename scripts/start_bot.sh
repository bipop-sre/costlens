#!/bin/bash
cd /Users/lixiaosong/costlens
source .venv/bin/activate
mkdir -p logs
nohup python -m costlens.main wechat-bot >> logs/bot.log 2>&1 &
echo $!
