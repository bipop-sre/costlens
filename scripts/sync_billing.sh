#!/bin/bash
# 每小时同步云厂商账单数据（月度 + 日粒度 + 余额）
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$PROJECT_DIR/logs/billing_sync.log"
PYTHON="$PROJECT_DIR/.venv/bin/python"

mkdir -p "$PROJECT_DIR/logs"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting billing sync..." >> "$LOG_FILE"

cd "$PROJECT_DIR"
$PYTHON -c "
import asyncio, sys, logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
sys.path.insert(0, '$PROJECT_DIR')
from costlens.scheduler import BillingScheduler

async def main():
    scheduler = BillingScheduler()
    result = await scheduler.sync_billing_data()
    for p, d in result.get('providers', {}).items():
        monthly = d.get('monthly_records', 0)
        daily = d.get('daily_records', 0)
        cost = d.get('monthly_cost', 0) + d.get('daily_cost', 0)
        print(f'  {p}: monthly={monthly} daily={daily} cost={cost:.2f}')
    print(f'Total: {result[\"total_records\"]} records, {result[\"total_cost\"]:.2f} CNY')
    await scheduler._analyzer.close()

asyncio.run(main())
" >> "$LOG_FILE" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Done" >> "$LOG_FILE"
echo "---" >> "$LOG_FILE"
