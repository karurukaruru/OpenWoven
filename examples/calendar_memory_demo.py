"""Synthetic three-month recall demo. No API key, network or real user data."""
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime

from adaptive_companion import CompanionCore


def main():
    with TemporaryDirectory() as directory:
        with CompanionCore(Path(directory) / 'demo.db', learning_enabled=False,
                           memory_utc_offset_minutes=480, memory_zone_name='Asia/Shanghai') as core:
            core.wait_for_learning()
            samples = [
                ('2026-01-01', '今天开始记录生活，给这个计划取名为樱花计划。'),
                ('2026-01-10', '我们给猫取名叫龙眼，后来去了南门咖啡店。'),
                ('2026-01-20', '今天买了一个新的花盆，准备种薄荷。'),
                ('2026-02-12', '樱花计划已经完成，今天整理好了所有旅行照片。'),
                ('2026-03-18', '今天想起来一月份给猫取名字的那次聊天。'),
            ]
            target = None
            for day, text in samples:
                message = core.store.save_message('demo', 'user', text, learning_status='disabled',
                    timestamp=day + 'T12:00:00+08:00')
                if day == '2026-01-10':
                    target = message
            counts = core.memory.maintain(datetime.fromisoformat('2026-04-02T12:00:00+08:00'))
            print(f"合成归档：{counts['daily']} 个日、{counts['weekly']} 个周、{counts['monthly']} 个月")
            query = '第一个月的第二周的第三天 龙眼'
            print('三个月后问：' + query)
            results = core.retriever.retrieve(query)
            match = next(item for item in results if item['source_message_id'] == target.id)
            print('定位日期：' + match['local_day'])
            detail = core.memory.archives.detail(match['archive_id'])
            original = next(m for m in detail['messages'] if m['id'] == target.id)
            print('找到原话：' + original['content'])
            assert original['content'] == target.content
            core.delete_message(target.id)
            core.memory.maintain(datetime.fromisoformat('2026-04-02T12:00:00+08:00'))
            assert not core.retriever.retrieve('龙眼')
            print('删除后再次搜索：没有残留原话或派生摘要。')
            print('这只验证归档和检索，不代表真实 LLM 聊天质量。')


if __name__ == '__main__':
    main()
