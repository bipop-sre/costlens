#!/usr/bin/env python3
"""Standalone test to verify Bailian tracking pipeline works end-to-end."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

def test_pipeline():
    print("=" * 60)
    print("百炼 Token 追踪全链路诊断")
    print("=" * 60)

    # Step 1: Config
    print("\n[Step 1] 加载配置...")
    from costlens.config import get_settings
    settings = get_settings()
    print(f"  DB type: {settings.db_type}")
    print(f"  DB path: {getattr(settings, 'db_path', 'N/A')}")
    print(f"  OpenAI model: {settings.openai_model}")
    print(f"  OpenAI base URL: {settings.openai_base_url}")
    bailian_keys = settings.get_bailian_keys()
    print(f"  Bailian keys configured: {len(bailian_keys)}")
    for k in bailian_keys:
        print(f"    - alias={k.get('alias')}, prefix={k.get('prefix')}")
    if not bailian_keys:
        print("  ⚠️  没有配置 BAILIAN_API_KEYS!")
    print("  ✅ 配置加载成功")

    # Step 2: DB Backend
    print("\n[Step 2] 数据库后端...")
    from costlens.db import get_backend
    backend = get_backend()
    print(f"  Backend type: {backend.db_type}")
    with backend.connect() as conn:
        row = conn.execute("SELECT 1 as test").fetchone()
        print(f"  Connection test: {row['test']}")
    print("  ✅ 数据库连接正常")

    # Step 3: Check tables
    print("\n[Step 3] 检查百炼表...")
    tables_ok = True
    with backend.connect() as conn:
        for table in ["bailian_api_keys", "bailian_usage_records"]:
            try:
                sql = f"SELECT COUNT(*) as cnt FROM {table}"
                row = conn.execute(sql).fetchone()
                print(f"  {table}: {row['cnt']} rows ✅")
            except Exception as exc:
                print(f"  {table}: ❌ 表不存在! ({exc})")
                tables_ok = False
    if not tables_ok:
        print("  ⚠️  表不存在，尝试创建...")
        from costlens.bailian.tracker import get_bailian_tracker
        tracker = get_bailian_tracker()
        print("  ✅ Tracker._ensure_tables() 已执行")
        # Re-check
        with backend.connect() as conn:
            for table in ["bailian_api_keys", "bailian_usage_records"]:
                try:
                    row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
                    print(f"  {table}: {row['cnt']} rows ✅")
                except Exception as exc:
                    print(f"  {table}: ❌ 仍然不存在! ({exc})")

    # Step 4: Tracker
    print("\n[Step 4] BailianUsageTracker...")
    from costlens.bailian.tracker import get_bailian_tracker
    tracker = get_bailian_tracker()
    keys = tracker.list_api_keys(active_only=False)
    print(f"  Registered keys: {len(keys)}")
    for k in keys:
        print(f"    - {k.key_alias} (active={k.is_active})")
    print("  ✅ Tracker 初始化成功")

    # Step 5: Register key
    print("\n[Step 5] 注册 test key...")
    tracker.add_api_key("test-key", "sk-test", "诊断测试 key")
    keys = tracker.list_api_keys(active_only=False)
    print(f"  Keys after register: {len(keys)}")
    print("  ✅ Key 注册成功")

    # Step 6: Write test record
    print("\n[Step 6] 写入测试记录...")
    from datetime import date
    record = tracker.record_usage(
        key_alias="test-key",
        model_name="qwen-max",
        input_tokens=1000,
        output_tokens=500,
        usage_date=date.today(),
        request_id=f"diag-{date.today().isoformat()}",
    )
    print(f"  Recorded: {record.total_tokens} tokens, ¥{record.estimated_cost}")
    print("  ✅ 写入成功")

    # Step 7: Read back
    print("\n[Step 7] 读回验证...")
    with backend.connect() as conn:
        sql = backend.adapt_sql("SELECT COUNT(*) as cnt FROM bailian_usage_records WHERE key_alias = ?")
        row = conn.execute(sql, ("test-key",)).fetchone()
        count = row["cnt"]
        print(f"  test-key records: {count}")
        assert count > 0, "写入后读回为0!"
    print("  ✅ 读回验证成功")

    # Step 8: track_openai_response simulation
    print("\n[Step 8] 模拟 track_openai_response...")
    from costlens.bailian.integration import track_openai_response

    class FakeUsage:
        prompt_tokens = 200
        completion_tokens = 100
        total_tokens = 300
        def model_dump(self):
            return {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300}

    class FakeResponse:
        id = "fake-resp-001"
        model = "qwen-max"
        usage = FakeUsage()

    result = track_openai_response("test-key", FakeResponse(), "qwen-max")
    print(f"  Result: {result}")
    if result["status"] == "ok":
        print("  ✅ track_openai_response 工作正常")
    else:
        print(f"  ❌ track_openai_response 返回异常: {result}")

    # Step 9: Check all records
    print("\n[Step 9] 全表统计...")
    with backend.connect() as conn:
        row = conn.execute("SELECT COUNT(*) as cnt FROM bailian_usage_records").fetchone()
        total = row["cnt"]
        print(f"  Total usage records: {total}")
        if total > 0:
            row = conn.execute(
                "SELECT SUM(total_tokens) as tokens, SUM(estimated_cost) as cost FROM bailian_usage_records"
            ).fetchone()
            print(f"  Total tokens: {row['tokens']}")
            print(f"  Total cost: ¥{row['cost']}")

    # Step 10: Cleanup
    print("\n[Step 10] 清理测试数据...")
    with backend.connect() as conn:
        sql = backend.adapt_sql("DELETE FROM bailian_usage_records WHERE key_alias = ?")
        conn.execute(sql, ("test-key",))
        sql2 = backend.adapt_sql("DELETE FROM bailian_api_keys WHERE key_alias = ?")
        conn.execute(sql2, ("test-key",))
        conn.commit()
    print("  ✅ 清理完成")

    # Step 11: Check if agent/core.py has tracking
    print("\n[Step 11] 检查 agent/core.py 追踪代码...")
    import inspect
    from costlens.agent.core import CostLensAgent
    source = inspect.getsource(CostLensAgent.chat)
    has_tracking = "track_openai_response" in source
    print(f"  chat() has tracking: {'✅' if has_tracking else '❌'}")
    source2 = inspect.getsource(CostLensAgent.stream_chat)
    has_tracking2 = "track_openai_response" in source2
    print(f"  stream_chat() has tracking: {'✅' if has_tracking2 else '❌'}")
    if not has_tracking or not has_tracking2:
        print("  ⚠️  追踪代码未注入! 当前运行的是旧版代码!")

    print("\n" + "=" * 60)
    print("诊断完成!")
    print("=" * 60)

if __name__ == "__main__":
    test_pipeline()
