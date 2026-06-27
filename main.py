"""信息精选系统 v2.0 - 主流程编排
用法:
  python main.py              # 完整流程
  python main.py collect      # 只采集
  python main.py process      # 只AI处理
  python main.py digest       # 只生成Digest
  python main.py send         # 推送最近Digest
  python main.py reprocess    # 全部重新处理"""
import sys
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import collector
import local_collector
import processor
import digest_builder
import delivery


def run_full(period="morning"):
    print("=" * 50)
    print("📡 信息精选系统 v2.0")
    print("=" * 50)

    print("\n🔄 Step 1a: 在线采集...")
    n = collector.collect_all()

    print("\n📁 Step 1b: 本地文件...")
    n2 = local_collector.collect_inbox()

    print("\n🤖 Step 2: AI 处理（两阶段）...")
    n = processor.process_unsummarized(limit=50)

    print("\n📝 Step 3: 聚类 + Digest...")
    digest = digest_builder.build_digest(period=period)

    if digest:
        print("\n📤 Step 4: 推送飞书...")
        ok = delivery.send_digest(digest)
        print(f"\n{'✅' if ok else '⚠️'} {'全流程完成' if ok else '推送失败'}")
    else:
        print("\n⚠️ 没有足够高质量内容")

    return digest


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "full"
    if cmd == "collect":
        collector.collect_all()
    elif cmd == "process":
        processor.process_unsummarized(limit=50)
    elif cmd == "reprocess":
        processor.reprocess_all(limit=50)
    elif cmd == "digest":
        d = digest_builder.build_digest()
        if d: print(d["body"])
    elif cmd == "send":
        d = digest_builder.build_digest()
        if d: delivery.send_digest(d)
    else:
        run_full()
