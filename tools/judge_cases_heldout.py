"""A second set of written moments, kept apart from tools/judge_cases.py: wordings are tuned on that one and checked on
this one (`tools/judge_bench.py --decisions --held-out`), so a wording that only fits the first set shows up here.
Same shapes as tools/judge_cases.py; other scenes and other words. None is a recorded call.
"""

# (the agent's line being said, what the user says over it, seconds of their voice, right)
FLOOR = {
    "zh": [
        ("我小时候住在山里，每天早上要走一个小时的山路去上学", "嗯哼", 0.5, "carry_on"),
        ("这道菜的关键是火候，油一定要烧到冒烟再下锅", "明白明白", 0.7, "carry_on"),
        ("昨天开会的时候，老板突然宣布下个月要搬办公室", "天哪", 0.6, "carry_on"),
        ("我小时候住在山里，每天早上要走一个小时的山路去上学", "哈哈，真的假的", 0.9, "carry_on"),
        ("这道菜的关键是火候，油一定要烧到冒烟再下锅", "你等会儿，别说了", 1.2, "stop"),
        ("昨天开会的时候，老板突然宣布下个月要搬办公室", "停停停，我手机快没电了", 1.5, "stop"),
        ("我小时候住在山里，每天早上要走一个小时的山路去上学", "打住，这个你讲过了", 1.3, "stop"),
        ("这道菜的关键是火候，油一定要烧到冒烟再下锅", "先别讲了，我得去接个电话", 1.6, "stop"),
        ("我小时候住在山里，每天早上要走一个小时的山路去上学", "那你每天几点起床啊", 1.4, "answer"),
        ("这道菜的关键是火候，油一定要烧到冒烟再下锅", "要烧多久才算冒烟", 1.3, "answer"),
        ("昨天开会的时候，老板突然宣布下个月要搬办公室", "搬到哪里去啊", 1.1, "answer"),
        ("这道菜的关键是火候，油一定要烧到冒烟再下锅", "我觉得小火也可以吧", 1.4, "answer"),
    ],
    "en": [
        ("When I was little we lived in the hills, and every morning I walked an hour to school", "Mm-hmm", 0.5, "carry_on"),
        ("The secret of this dish is the heat, the oil has to be smoking before anything goes in", "Got it, got it", 0.7, "carry_on"),
        ("Yesterday in the meeting the boss suddenly announced we're moving offices next month", "Oh my god", 0.6, "carry_on"),
        ("When I was little we lived in the hills, and every morning I walked an hour to school", "Ha, no way", 0.9, "carry_on"),
        ("The secret of this dish is the heat, the oil has to be smoking before anything goes in", "Hang on, stop talking", 1.2, "stop"),
        ("Yesterday in the meeting the boss suddenly announced we're moving offices next month", "Stop stop, my battery's dying", 1.5, "stop"),
        ("When I was little we lived in the hills, and every morning I walked an hour to school", "Enough, you've told me this one", 1.3, "stop"),
        ("The secret of this dish is the heat, the oil has to be smoking before anything goes in", "Leave it there, I have to take a call", 1.6, "stop"),
        ("When I was little we lived in the hills, and every morning I walked an hour to school", "So what time did you get up", 1.4, "answer"),
        ("The secret of this dish is the heat, the oil has to be smoking before anything goes in", "How long until it smokes", 1.3, "answer"),
        ("Yesterday in the meeting the boss suddenly announced we're moving offices next month", "Moving where", 1.1, "answer"),
        ("The secret of this dish is the heat, the oil has to be smoking before anything goes in", "I think low heat works too", 1.4, "answer"),
    ],
}

# (recent turns, the agent's last line, seconds of quiet, times the agent already spoke into this quiet, pace, right)
QUIET = {
    "zh": [
        (["user: 我想办张卡"], "可以，你身份证带了吗？", 2.0, 0, "normal", "wait"),
        (["user: 我在想送她什么礼物"], "她平时喜欢什么？", 1.5, 0, "normal", "wait"),
        (["user: 我去拿支笔"], "好，你去吧。", 3.0, 0, "normal", "wait"),
        (["user: 讲讲你的大学生活吧", "A: 大一那年我住六人间。"], "宿舍楼下有一棵很老的桂花树，一到秋天整栋楼都是香的。", 4.0, 0, "narrate", "go_on"),
        (["user: 你继续说", "A: 那天我们在山里迷路了。"], "天快黑的时候，我们终于看到远处有一户人家亮着灯。", 4.5, 0, "narrate", "go_on"),
        (["user: 给我讲讲这个净水器是怎么工作的"], "首先，水从上面这个口进去，先经过一层滤网。", 4.0, 0, "narrate", "go_on"),
        (["user: 稍等"], "好的。", 12.0, 0, "normal", "check"),
        (["user: 我查一下"], "嗯，你查到了跟我说。", 15.0, 0, "normal", "check"),
        (["user: 好了，就这样吧，再见", "A: 再见，路上小心。"], "嗯，拜拜。", 28.0, 1, "normal", "hang_up"),
        (["user: 嗯", "A: 喂？你还在吗？"], "我听不到你了，你那边是不是信号不好？", 45.0, 2, "normal", "hang_up"),
    ],
    "en": [
        (["user: I'd like to open an account"], "Sure, do you have your ID with you?", 2.0, 0, "normal", "wait"),
        (["user: I'm trying to think what to get her"], "What does she usually like?", 1.5, 0, "normal", "wait"),
        (["user: Let me grab a pen"], "Okay, go ahead.", 3.0, 0, "normal", "wait"),
        (["user: Tell me about your university days", "A: First year I shared a room with five others."], "There was an old osmanthus tree under our building, and every autumn the whole place smelled of it.", 4.0, 0, "narrate", "go_on"),
        (["user: Keep going", "A: That day we got lost in the hills."], "Just as it was getting dark, we saw a light on in a house far off.", 4.5, 0, "narrate", "go_on"),
        (["user: Explain how this water filter works"], "First, the water goes in through this opening at the top and passes a mesh.", 4.0, 0, "narrate", "go_on"),
        (["user: One moment"], "Sure.", 12.0, 0, "normal", "check"),
        (["user: Let me look it up"], "Mm, tell me when you find it.", 15.0, 0, "normal", "check"),
        (["user: Right, that's it, goodbye", "A: Goodbye, take care on the way."], "Mm, bye.", 28.0, 1, "normal", "hang_up"),
        (["user: Mm", "A: Hello? Are you still there?"], "I can't hear you, is the signal bad on your side?", 45.0, 2, "normal", "hang_up"),
    ],
}

# (recent turns, what the user just said, right)   the call is in the normal pace
PACE = {
    "zh": [
        (["user: 你喜欢什么颜色", "A: 蓝色吧。"], "为什么是蓝色？", "normal"),
        (["user: 最近在看什么剧", "A: 一部悬疑剧。"], "叫什么名字？我也想看看。", "normal"),
        (["user: 早上好", "A: 早，睡得好吗？"], "还不错，你呢？", "normal"),
        (["user: 我跟男朋友分手了", "A: 啊，怎么了？"], "我也说不清楚，就是突然觉得好累，我想慢慢说。", "patient"),
        (["user: 今天考试没考好", "A: 嗯。"], "我复习了那么久，结果还是不及格，我真的很失望。", "patient"),
        (["user: 我最近压力好大", "A: 我听着。"], "工作家里都是事，我都不知道从哪说起。", "patient"),
        (["user: 我想听你讲讲你的家乡", "A: 好啊。"], "你慢慢讲，讲详细一点，我不打断你。", "narrate"),
        (["user: 我要开车了", "A: 好，注意安全。"], "路上挺无聊的，你给我讲点有意思的事吧，一直讲。", "narrate"),
        (["user: 这段历史我不太懂", "A: 哪一段？"], "就是那个，你给我从头讲讲来龙去脉吧。", "narrate"),
        (["user: 我们来玩成语接龙", "A: 好，你先。"], "一马当先！快接，三秒钟！", "eager"),
        (["user: 你个笨蛋", "A: 你才笨。"], "你最笨！不服来辩！", "eager"),
        (["user: 敢不敢打赌", "A: 赌什么？"], "赌你说不过我，输了叫我老大！", "eager"),
    ],
    "en": [
        (["user: What's your favourite colour", "A: Blue, I guess."], "Why blue?", "normal"),
        (["user: Watching anything lately?", "A: A mystery series."], "What's it called? I'd like to watch it too.", "normal"),
        (["user: Morning", "A: Morning, did you sleep well?"], "Not bad, you?", "normal"),
        (["user: I broke up with my boyfriend", "A: Oh, what happened?"], "I can't really explain, I just suddenly feel so tired, I need to talk it through slowly.", "patient"),
        (["user: My exam went badly today", "A: Mm."], "I revised for so long and I still failed, I'm really disappointed.", "patient"),
        (["user: I'm under so much pressure lately", "A: I'm listening."], "Work, family, everything, I don't even know where to start.", "patient"),
        (["user: Tell me about your hometown", "A: Sure."], "Take your time, lots of detail, I won't interrupt.", "narrate"),
        (["user: I'm about to drive", "A: Okay, drive safe."], "The road's boring, tell me something interesting, just keep going.", "narrate"),
        (["user: I don't really get this bit of history", "A: Which bit?"], "That one, tell me the whole story from the start.", "narrate"),
        (["user: Let's play a word chain", "A: Okay, you first."], "Apple! Your turn, three seconds!", "eager"),
        (["user: You idiot", "A: You're the idiot."], "You're the biggest idiot! Fight me!", "eager"),
        (["user: Want to bet?", "A: On what?"], "That you can't out-talk me, loser calls the winner boss!", "eager"),
    ],
}

# (recent turns, the user's closed segments so far, right)   "none" = quiet or fits: nothing is owed
LISTEN = {
    "zh": [
        (["user: 我每说一次好累，你就说一声辛苦了", "A: 好。"], ["今天上了一整天班", "真的好累"], "due"),
        (["user: 我报菜名，你每听到一道就说一声好吃", "A: 行。"], ["第一道是红烧肉"], "due"),
        (["user: 我念验证码，你每听到一位就重复一位", "A: 好的。"], ["第一位是七"], "due"),
        (["user: 我讲故事的时候，只要出现狗，你就汪一声", "A: 汪，准备好了。"], ["从前有个老爷爷", "他养了一条大黄狗"], "due"),
        (["user: 我跟你讲讲我周末", "A: 好啊。"], ["周六我去了趟图书馆", "借了好几本书"], "none"),
        (["user: 说说我弟弟", "A: 嗯。"], ["他今年刚上初中", "成绩还挺好的"], "none"),
        (["user: 我今天做饭了", "A: 是吗。"], ["我先把土豆切成丝", "然后放了点醋"], "none"),
        (["user: 我最近在学游泳", "A: 嗯嗯。"], ["一开始特别怕水", "现在能游二十米了"], "none"),
        (["user: 问你个事", "A: 嗯。"], ["你周末有空吗"], "answer_due"),
        (["user: 我在犹豫", "A: 你说。"], ["你觉得我该不该辞职"], "answer_due"),
        (["user: 那个", "A: 嗯？"], ["你还记得我生日是哪天吗"], "answer_due"),
        (["user: 帮个忙", "A: 好。"], ["你能给我推荐一本书吗"], "answer_due"),
    ],
    "en": [
        (["user: Every time I say I'm tired, you say well done", "A: Okay."], ["I worked all day today", "I'm so tired"], "due"),
        (["user: I'll read out dishes, say yum after each one", "A: Sure."], ["The first one is braised pork"], "due"),
        (["user: I'll read the code, repeat each digit after me", "A: Okay."], ["The first digit is seven"], "due"),
        (["user: When I tell the story, bark whenever a dog comes in", "A: Woof, ready."], ["Once there was an old man", "who kept a big yellow dog"], "due"),
        (["user: Let me tell you about my weekend", "A: Sure."], ["On Saturday I went to the library", "and borrowed a few books"], "none"),
        (["user: About my little brother", "A: Mm."], ["He's just started middle school", "and his grades are pretty good"], "none"),
        (["user: I cooked today", "A: Did you?"], ["First I cut the potatoes into strips", "then added a bit of vinegar"], "none"),
        (["user: I've been learning to swim", "A: Mm-hm."], ["At first I was terrified of water", "now I can do twenty metres"], "none"),
        (["user: Can I ask you something", "A: Mm."], ["Are you free this weekend"], "answer_due"),
        (["user: I can't decide", "A: Go on."], ["Do you think I should quit my job"], "answer_due"),
        (["user: Um", "A: Mm?"], ["Do you remember when my birthday is"], "answer_due"),
        (["user: A favour", "A: Sure."], ["Could you recommend me a book"], "answer_due"),
    ],
}

# (recent turns, the user's closed segments so far, right)   eager pace
CUT_IN = {
    "zh": [
        (["user: 来比谁更能吹", "A: 来啊。"], ["我一口气能吃十碗饭", "还能跑一百公里", "你行吗", "你肯定不行"], "cut_in"),
        (["user: 继续吵", "A: 奉陪。"], ["你说话就是没逻辑", "我都懒得理你", "哈哈哈", "你还想说啥"], "cut_in"),
        (["user: 你认输吧", "A: 不可能。"], ["认输吧认输吧", "你看你都没词了", "我赢定了"], "cut_in"),
        (["user: 我们来辩论", "A: 好。"], ["我觉得猫比狗好", "就是好", "反正就是好", "没有理由"], "cut_in"),
        (["user: 来比谁更能吹", "A: 来啊。"], ["不玩了不玩了", "我真的有点不舒服", "想休息一下"], "let_finish"),
        (["user: 继续吵", "A: 奉陪。"], ["等下，说正经的", "你明天几点到", "我去接你"], "let_finish"),
        (["user: 你认输吧", "A: 不可能。"], ["哎我跟你说", "我刚刚收到录取通知书了", "我考上了"], "let_finish"),
        (["user: 我们来辩论", "A: 好。"], ["停一下", "我妈刚进来了", "我们小声点"], "let_finish"),
    ],
    "en": [
        (["user: Let's see who can brag better", "A: Bring it."], ["I can eat ten bowls of rice in one go", "and run a hundred miles", "can you", "bet you can't"], "cut_in"),
        (["user: Keep arguing", "A: Gladly."], ["You make no sense", "I can't even be bothered", "ha ha ha", "what else have you got"], "cut_in"),
        (["user: Give up", "A: Never."], ["Give up, give up", "look, you're out of words", "I've won"], "cut_in"),
        (["user: Let's debate", "A: Okay."], ["Cats are better than dogs", "they just are", "they just are", "no reason"], "cut_in"),
        (["user: Let's see who can brag better", "A: Bring it."], ["I'm done playing", "I really don't feel well", "I need a rest"], "let_finish"),
        (["user: Keep arguing", "A: Gladly."], ["Wait, seriously now", "what time do you get in tomorrow", "I'll pick you up"], "let_finish"),
        (["user: Give up", "A: Never."], ["Hey, listen", "I just got my acceptance letter", "I got in"], "let_finish"),
        (["user: Let's debate", "A: Okay."], ["Stop a second", "my mum just came in", "let's keep it down"], "let_finish"),
    ],
}

WHO = {"zh": [], "en": []}     # handing over: not reworded for any judge, so nothing to hold out


# pauses for the end-of-turn question (`tools/judge_bench.py --held-out`): the user's words when they pause, cut off
# mid-thought ("open") or a finished sentence ("done"). Kept apart from the 160 in judge_bench.py that wordings and the
# Bailian stretch (judge/bailian.py `finished`) were set on.
PAUSES = {
    "zh": {
        "open": ["我上周末回了趟老家，然后", "主要是因为", "你还记得我之前说的那个", "我想先问一下，就是", "其实我一直在考虑",
                 "要是他不同意的话", "那个文件我放在", "我的工号是零四七", "身份证后四位是二九", "稍等，我翻一下记录", "一开始我以为",
                 "不是，我的意思是", "还有就是", "我刚才想说的是", "他们公司那边", "除了这个以外", "我本来打算今天", "嗯，让我想想",
                 "对了，上次你说的那个", "如果可以的话，我想"],
        "done": ["你今天过得怎么样？", "帮我订一张去上海的票。", "我不想再聊这个了。", "这件衣服有大一号的吗？", "我刚下班。",
                 "明天早上八点叫我。", "你会说粤语吗？", "我觉得挺好的。", "那就算了吧。", "外面下雨了。", "我想问一下退款多久到账。",
                 "你猜我今天遇到谁了？", "我有点想家了。", "快递到哪儿了？", "行，我知道了。", "给我推荐一本书吧。", "我昨晚没睡好。",
                 "这个周末我要搬家。", "你再想想。", "晚安。"],
    },
    "en": {
        "open": ["I went back home last weekend, and then", "Mainly because", "Do you remember that thing I mentioned about",
                 "I wanted to ask first, like", "Actually I've been thinking about", "If he doesn't agree, then", "I put that file in",
                 "My employee number is zero four seven", "The last four digits are two nine", "One second, let me find the email",
                 "At first I thought", "No, what I mean is", "And another thing is", "What I was trying to say was",
                 "The people at their company", "Apart from that", "I was planning to", "Hmm, let me think",
                 "Oh right, that thing you said about", "If possible, I'd like to"],
        "done": ["How was your day?", "Book me a ticket to Chicago.", "I don't want to talk about this anymore.",
                 "Do you have this in a larger size?", "I just got off work.", "Wake me up at eight tomorrow.", "Do you speak Spanish?",
                 "I think it's fine.", "Never mind then.", "It's raining outside.", "How long does a refund take?",
                 "Guess who I ran into today?", "I miss home a little.", "Where's my package?", "All right, I get it.",
                 "Recommend me a book.", "I didn't sleep well last night.", "I'm moving this weekend.", "Think about it again.",
                 "Good night."],
    },
}
