#!/usr/bin/env python3
"""
修复 9 月数据重复问题

根因：已 revert 的资源级特性（7707ca7）曾将 instance_id 加入唯一键，
导致同一 (provider, service, date, ...) 下因 instance_id 不同而产生重复记录。
代码已不再写入 instance_id，但 OceanBase 表唯一键仍包含它。

修复步骤：
1. 删除所有 instance_id 非空的资源级记录（聚合记录已覆盖所有组）
2. 修正唯一键：去掉 instance_id
"""

import sys
import pymysql

conn = pymysql.connect(
    host='10.71.143.96',
    port=3306,
    user='costlens',
    password='RcC+R*k^)lzyO4MmgtG!pd',
    database='costlens',
    charset='utf8mb4',
    autocommit=False,
)

def main():
    dry_run = '--dry-run' in sys.argv
    if dry_run:
        print("[DRY RUN] 不会实际修改数据\n")

    cursor = conn.cursor()

    # ── Step 1: Stats ──
    print("=" * 60)
    print("Step 1: 统计")
    print("=" * 60)

    cursor.execute("SELECT COUNT(*) FROM cost_records WHERE record_date >= '2026-09-01' AND record_date < '2026-10-01'")
    total = cursor.fetchone()[0]
    print(f"9月总记录数: {total}")

    cursor.execute("SELECT COUNT(*) FROM cost_records WHERE record_date >= '2026-09-01' AND record_date < '2026-10-01' AND instance_id IS NOT NULL AND instance_id != ''")
    resource_count = cursor.fetchone()[0]
    print(f"资源级记录数（将删除）: {resource_count}")
    print(f"修复后预计记录数: {total - resource_count}")

    # ── Step 2: Delete resource-level records ──
    print()
    print("=" * 60)
    print("Step 2: 删除资源级记录（保留聚合记录）")
    print("=" * 60)

    if dry_run:
        print(f"[DRY RUN] 将删除 {resource_count} 条 instance_id 非空的记录")
    else:
        cursor.execute("DELETE FROM cost_records WHERE instance_id IS NOT NULL AND instance_id != ''")
        deleted = cursor.rowcount
        print(f"已删除 {deleted} 条资源级记录")
        conn.commit()

    # ── Step 3: Fix unique key ──
    print()
    print("=" * 60)
    print("Step 3: 修正唯一键（去掉 instance_id）")
    print("=" * 60)

    alter_sqls = [
        "ALTER TABLE cost_records DROP INDEX uk_cost_record",
        """ALTER TABLE cost_records ADD UNIQUE KEY uk_cost_record
           (provider, account_id, service_name, region, record_date,
            granularity, subscription_type)""",
    ]

    for sql in alter_sqls:
        if dry_run:
            print(f"[DRY RUN] {sql}")
        else:
            try:
                cursor.execute(sql)
                conn.commit()
                print(f"OK: {sql[:80]}...")
            except Exception as e:
                print(f"ERROR: {e}")
                conn.rollback()

    # ── Step 4: Verify ──
    print()
    print("=" * 60)
    print("Step 4: 验证")
    print("=" * 60)

    if not dry_run:
        cursor.execute("SELECT COUNT(*) FROM cost_records WHERE record_date >= '2026-09-01' AND record_date < '2026-10-01'")
        final_total = cursor.fetchone()[0]
        print(f"9月最终记录数: {final_total}")

        cursor.execute("""
            SELECT COUNT(*) FROM (
                SELECT provider, account_id, service_name, region, record_date, granularity, subscription_type, COUNT(*) as cnt
                FROM cost_records
                WHERE record_date >= '2026-09-01' AND record_date < '2026-10-01'
                GROUP BY provider, account_id, service_name, region, record_date, granularity, subscription_type
                HAVING cnt > 1
            ) t
        """)
        remaining_dups = cursor.fetchone()[0]
        print(f"剩余重复组数: {remaining_dups}")

        cursor.execute("SELECT COUNT(*) FROM cost_records WHERE instance_id IS NOT NULL AND instance_id != ''")
        remaining_res = cursor.fetchone()[0]
        print(f"剩余资源级记录: {remaining_res}")

        cursor.execute("SHOW INDEX FROM cost_records WHERE Key_name = 'uk_cost_record'")
        print("\n修正后的唯一键列:")
        for row in cursor.fetchall():
            print(f"  Seq {row[3]}: {row[4]}")

    cursor.close()
    conn.close()
    print("\n完成！" if not dry_run else "\nDry run 完成，不带 --dry-run 执行实际修复")


if __name__ == '__main__':
    main()
