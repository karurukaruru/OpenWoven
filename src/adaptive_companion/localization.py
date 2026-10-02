"""Local runtime messages; original user text is never machine-translated."""
from __future__ import annotations

LANGUAGES = ("Simplified Chinese", "Traditional Chinese", "Japanese", "American English")
STRINGS = {
    "proactive_opening": ("最近怎么样？", "最近怎麼樣？", "最近どう？", "How's it going?"),
    "casual_checkin": ("上次聊的那件事，有空再接着聊呀。", "上次聊的那件事，有空再接著聊呀。", "この前の話、また時間があるときに続けましょう。", "We can pick up our last conversation whenever you feel like it."),
    "exam": ("你今天那个考试后来怎么样？", "你今天那個考試後來怎麼樣？", "今日の試験はどうでしたか？", "How did your exam go today?"),
    "interview": ("你今天的面试后来还顺利吗？", "你今天的面試後來還順利嗎？", "今日の面接はうまくいきましたか？", "How did your interview go today?"),
    "technical": ("我会直接抓核心问题：先确认输入、状态变化和失败边界，再用最小复现验证。", "我會直接抓核心問題：先確認輸入、狀態變化與失敗邊界，再用最小重現驗證。", "まず入力・状態の変化・失敗条件を確認し、最小限の再現例で検証します。", "Start with the inputs, state changes and failure boundaries, then check a minimal reproduction."),
    "emotional": ("听起来这件事确实很消耗人。先不用急着解决，缓一下也完全合理。", "聽起來這件事確實很消耗人。先不用急著解決，緩一下也完全合理。", "かなり疲れることだったんですね。すぐ解決しようとせず、ひと息ついても大丈夫です。", "That sounds draining. You don't have to solve it right away; taking a moment is okay."),
    "news": ("这很棒，值得认真开心一下。你为它投入的那些力气没有白费。", "這很棒，值得認真開心一下。你的努力沒有白費。", "よかったですね。頑張ってきたことが実を結んだんですね。", "That's worth celebrating. Your effort paid off."),
    "advice": ("我的建议是先选成本最低、可逆的一步，验证后再扩大投入。", "我的建議是先選成本最低、可逆的一步，確認後再擴大投入。", "まず負担が少なく、やり直せる一歩を試し、確かめてから広げるのがおすすめです。", "Try a low-cost, reversible step first, then build on what you learn."),
    "bored": ("那就来点不费劲的：挑一件十分钟内能完成、但平时总拖着的小事。", "那就來點不費勁的：挑一件十分鐘內能完成、但平時總拖著的小事。", "気軽にできることにしましょう。後回しにしていた、10分でできる小さなことを一つ。", "Try something easy: one small task you keep putting off that takes under ten minutes."),
    "ack": ("我记下了。{text}", "我記下了。{text}", "覚えておきます。{text}", "I'll keep that in mind. {text}"),
    "continuity": ("我明白你的重点，也会把这段上下文接到后面的对话里。", "我明白你的重點，也會讓後面的對話延續這段脈絡。", "大事な点はわかりました。次の会話にもこの流れをつなげます。", "I understand your point and will keep this context for our next conversation."),
    "detail": (" 我会结合我们之前聊过的内容，但不会把无关历史一股脑塞进当前回答。", " 我會結合先前聊過的內容，但不會塞入無關歷史。", " 過去の会話も参考にしますが、関係のない情報は持ち込みません。", " I'll use relevant earlier context without pulling in unrelated history."),
    "question": (" 你更想先从哪一部分开始？", " 你比較想先從哪部分開始？", " まずどの部分から始めたいですか？", " Which part would you like to start with?"),
    "scheduled": ("提醒已安排：{when}{note}。手机休眠时可能延后。", "提醒已安排：{when}{note}。手機休眠時可能延後。", "リマインダーを設定しました：{when}{note}。端末の休眠で遅れる場合があります。", "Reminder scheduled: {when}{note}. Device sleep may delay delivery."),
    "quiet_note": ("（已避开免打扰时段）", "（已避開勿擾時段）", "（おやすみ時間を避けました）", " (moved outside quiet hours)"),
    "remind": ("你之前让我提醒你：{text}", "你之前讓我提醒你：{text}", "頼まれたリマインダーです：{text}", "You asked me to remind you: {text}"),
    "exam_day": ("{title}是哪天、几点结束？", "{title}是哪天、幾點結束？", "{title}は何日で、何時に終わりますか？", "On what day, and at what time, does {title} end?"),
    "exam_time": ("那{title}大概几点结束？", "那{title}大概幾點結束？", "{title}は何時ごろ終わりますか？", "About what time does {title} end?"),
}


def local_text(language: str, key: str, **args: str) -> str:
    index = LANGUAGES.index(language) if language in LANGUAGES else 0
    return STRINGS[key][index].format(**args)
