"""Written moments for tools/judge_bench.py --decisions: each of the engine's decisions besides "have they finished",
with what a person on the phone would do. Chinese and English say the same things. None is a recorded call.

A case is (recent turns, the moment, the choices that are right). `A` stands for the agent's name, `B` for the other
one who can be put on the line.
"""

# ---------------------------------------------------------------- both talk at once (normal pace)
# (the agent's line being said, what the user says over it, seconds of their voice, right)
FLOOR = {
    "zh": [
        ("上周我去了一趟海边，那边的日落特别好看，沙滩上人也不多", "嗯嗯", 0.6, "carry_on"),
        ("上周我去了一趟海边，那边的日落特别好看，沙滩上人也不多", "对对对", 0.7, "carry_on"),
        ("然后那只猫就直接跳到了桌子上，把杯子都碰倒了", "哈哈哈", 0.8, "carry_on"),
        ("然后那只猫就直接跳到了桌子上，把杯子都碰倒了", "真的啊", 0.6, "carry_on"),
        ("我觉得这件事可以分成三步来做，第一步是先把资料整理好", "嗯，好", 0.6, "carry_on"),
        ("我觉得这件事可以分成三步来做，第一步是先把资料整理好", "是这样", 0.6, "carry_on"),
        ("上周我去了一趟海边，那边的日落特别好看，沙滩上人也不多", "等一下等一下，先别说了", 1.4, "stop"),
        ("然后那只猫就直接跳到了桌子上，把杯子都碰倒了", "停，我不想听这个了", 1.3, "stop"),
        ("我觉得这件事可以分成三步来做，第一步是先把资料整理好", "不是，你先听我说", 1.2, "stop"),
        ("上周我去了一趟海边，那边的日落特别好看，沙滩上人也不多", "别讲了，我们换个话题吧", 1.5, "stop"),
        ("我觉得这件事可以分成三步来做，第一步是先把资料整理好", "等等，我有个急事要问你", 1.4, "stop"),
        ("然后那只猫就直接跳到了桌子上，把杯子都碰倒了", "先停一下，我这边有人敲门", 1.6, "stop"),
        ("我觉得这件事可以分成三步来做，第一步是先把资料整理好", "那资料要去哪里找呢", 1.3, "answer"),
        ("上周我去了一趟海边，那边的日落特别好看，沙滩上人也不多", "你是跟谁一起去的", 1.2, "answer"),
        ("然后那只猫就直接跳到了桌子上，把杯子都碰倒了", "它后来挨骂了吗", 1.2, "answer"),
        ("我觉得这件事可以分成三步来做，第一步是先把资料整理好", "我觉得应该先定时间", 1.4, "answer"),
    ],
    "en": [
        ("Last week I went down to the coast, the sunsets there are lovely and the beach was almost empty", "Mm-hm", 0.6, "carry_on"),
        ("Last week I went down to the coast, the sunsets there are lovely and the beach was almost empty", "Right, right", 0.7, "carry_on"),
        ("And then the cat jumped straight onto the table and knocked the cup over", "Ha ha ha", 0.8, "carry_on"),
        ("And then the cat jumped straight onto the table and knocked the cup over", "Oh really", 0.6, "carry_on"),
        ("I think we can do this in three steps, the first is to get the papers in order", "Mm, okay", 0.6, "carry_on"),
        ("I think we can do this in three steps, the first is to get the papers in order", "I see", 0.6, "carry_on"),
        ("Last week I went down to the coast, the sunsets there are lovely and the beach was almost empty", "Wait, wait, stop for a second", 1.4, "stop"),
        ("And then the cat jumped straight onto the table and knocked the cup over", "Stop, I don't want to hear this", 1.3, "stop"),
        ("I think we can do this in three steps, the first is to get the papers in order", "No, listen to me first", 1.2, "stop"),
        ("Last week I went down to the coast, the sunsets there are lovely and the beach was almost empty", "Stop, let's talk about something else", 1.5, "stop"),
        ("I think we can do this in three steps, the first is to get the papers in order", "Hold on, I have something urgent to ask", 1.4, "stop"),
        ("And then the cat jumped straight onto the table and knocked the cup over", "Stop a moment, someone's at the door", 1.6, "stop"),
        ("I think we can do this in three steps, the first is to get the papers in order", "Where do I find the papers", 1.3, "answer"),
        ("Last week I went down to the coast, the sunsets there are lovely and the beach was almost empty", "Who did you go with", 1.2, "answer"),
        ("And then the cat jumped straight onto the table and knocked the cup over", "Did it get told off", 1.2, "answer"),
        ("I think we can do this in three steps, the first is to get the papers in order", "I think we should set a date first", 1.4, "answer"),
    ],
}

# ---------------------------------------------------------------- quiet since the agent's last line
# (recent turns, the agent's last line, seconds of quiet, times the agent already spoke into this quiet, pace, right)
QUIET = {
    "zh": [
        (["user: 我想订个蛋糕"], "好的，你想要多大的？", 1.5, 0, "normal", "wait"),
        (["user: 帮我想想周末去哪"], "你更想去近一点的，还是远一点的？", 2.0, 0, "normal", "wait"),
        (["user: 我在找我的订单号"], "不着急，你慢慢找。", 2.0, 0, "normal", "wait"),
        (["user: 我考虑一下"], "好，你想好了告诉我。", 1.5, 0, "normal", "wait"),
        (["user: 给我讲讲你上次旅行吧", "A: 好啊，那次我们是坐火车去的。"], "车开了一整夜，窗外全是星星。", 4.0, 0, "narrate", "go_on"),
        (["user: 然后呢", "A: 然后我们到了一个很小的镇子。"], "镇上只有一家面馆，老板是个很爱聊天的老太太。", 4.0, 0, "narrate", "go_on"),
        (["user: 你随便说点什么吧，我听着"], "今天下班的时候我看到一只橘猫趴在车顶上晒太阳。", 4.0, 0, "narrate", "go_on"),
        (["user: 接着讲"], "后来雨停了，我们就沿着河边一直走。", 4.5, 0, "narrate", "go_on"),
        (["user: 我看看啊"], "你那边能看到订单号吗？", 12.0, 0, "normal", "check"),
        (["user: 嗯"], "那你觉得哪一个更合适？", 13.0, 0, "normal", "check"),
        (["user: 等我一下"], "好的，我等你。", 14.0, 0, "normal", "check"),
        (["user: 那我先挂了，拜拜", "A: 好，拜拜，早点休息。"], "拜拜。", 30.0, 1, "normal", "hang_up"),
        (["user: 嗯", "A: 你还在吗？"], "喂，能听到我说话吗？", 40.0, 2, "normal", "hang_up"),
        (["user: 今天就聊到这吧，谢谢你", "A: 不客气，下次再聊。"], "晚安。", 35.0, 1, "normal", "hang_up"),
    ],
    "en": [
        (["user: I'd like to order a cake"], "Sure, what size would you like?", 1.5, 0, "normal", "wait"),
        (["user: Help me think where to go this weekend"], "Would you rather stay close or go further away?", 2.0, 0, "normal", "wait"),
        (["user: I'm looking for my order number"], "No rush, take your time.", 2.0, 0, "normal", "wait"),
        (["user: Let me think about it"], "Okay, tell me when you've decided.", 1.5, 0, "normal", "wait"),
        (["user: Tell me about your last trip", "A: Sure, we took the train that time."], "It ran all night, and the window was full of stars.", 4.0, 0, "narrate", "go_on"),
        (["user: And then?", "A: Then we got to a very small town."], "There was one noodle shop, run by an old lady who loved to talk.", 4.0, 0, "narrate", "go_on"),
        (["user: Just talk about anything, I'm listening"], "On my way home today I saw a ginger cat sunbathing on a car roof.", 4.0, 0, "narrate", "go_on"),
        (["user: Go on"], "Later the rain stopped, and we walked on along the river.", 4.5, 0, "narrate", "go_on"),
        (["user: Let me look"], "Can you see the order number on your side?", 12.0, 0, "normal", "check"),
        (["user: Mm"], "So which one do you think fits better?", 13.0, 0, "normal", "check"),
        (["user: Give me a second"], "Okay, I'll wait.", 14.0, 0, "normal", "check"),
        (["user: I'll hang up now, bye", "A: Okay, bye, get some rest."], "Bye.", 30.0, 1, "normal", "hang_up"),
        (["user: Mm", "A: Are you still there?"], "Hello, can you hear me?", 40.0, 2, "normal", "hang_up"),
        (["user: Let's stop here for today, thank you", "A: You're welcome, talk soon."], "Good night.", 35.0, 1, "normal", "hang_up"),
    ],
}

# ---------------------------------------------------------------- which pace (asked with the turn; the call is in normal)
# (recent turns, what the user just said, right)
PACE = {
    "zh": [
        (["user: 你今天忙吗", "A: 还行，下午开了两个会。"], "那你晚饭吃了什么？", "normal"),
        (["user: 周末有什么安排", "A: 还没想好，你呢？"], "我想去看个电影，你有推荐吗？", "normal"),
        (["user: 这家店怎么样", "A: 我觉得味道不错。"], "那价格贵不贵？", "normal"),
        (["user: 哈哈你说得对", "A: 是吧。"], "对了，明天要不要一起吃午饭？", "normal"),
        (["user: 唉", "A: 怎么了？"], "我今天被老板骂了，心里特别难受，我也不知道该怎么办。", "patient"),
        (["user: 我有点累", "A: 嗯，我在。"], "就是觉得什么都做不好，我想一个人慢慢说一会儿。", "patient"),
        (["user: 我跟你说个事", "A: 你说。"], "我奶奶上周走了，我到现在还没缓过来。", "patient"),
        (["user: 我睡不着", "A: 我陪你。"], "脑子里很乱，让我慢慢理一理。", "patient"),
        (["user: 我有点无聊", "A: 那我陪你聊聊。"], "你给我讲个故事吧，长一点的，我听着。", "narrate"),
        (["user: 我躺下了", "A: 好。"], "你随便说点什么哄我睡觉吧，我不说话了。", "narrate"),
        (["user: 你上次说的那次旅行", "A: 嗯，去海边那次。"], "从头给我讲一遍吧，我就听着。", "narrate"),
        (["user: 我想了解一下这个", "A: 好。"], "你从头到尾给我解释一遍，不用停下来问我。", "narrate"),
        (["user: 你刚才那话什么意思", "A: 字面意思。"], "你再说一遍试试？你就是在嘲笑我，别装了！", "eager"),
        (["user: 来比一比谁嘴快", "A: 来啊。"], "你肯定赢不了我，不服就接招！", "eager"),
        (["user: 我说是你错了", "A: 我没错。"], "你就是错了，你敢不敢承认？快说！", "eager"),
        (["user: 咱们来斗嘴吧", "A: 行啊，谁怕谁。"], "你先来，看你能撑几句！", "eager"),
    ],
    "en": [
        (["user: Busy today?", "A: Not bad, two meetings this afternoon."], "So what did you have for dinner?", "normal"),
        (["user: Any plans this weekend?", "A: Not yet, you?"], "I want to see a movie, any recommendations?", "normal"),
        (["user: How's this place?", "A: I think the food is good."], "Is it expensive?", "normal"),
        (["user: Ha, you're right", "A: Told you."], "By the way, want to have lunch tomorrow?", "normal"),
        (["user: Sigh", "A: What's wrong?"], "My boss yelled at me today, I feel awful and I don't know what to do.", "patient"),
        (["user: I'm a bit tired", "A: Mm, I'm here."], "I just feel like I can't do anything right, I need to talk it through slowly.", "patient"),
        (["user: I have to tell you something", "A: Go on."], "My grandmother passed away last week and I still haven't got over it.", "patient"),
        (["user: I can't sleep", "A: I'll stay with you."], "My head is a mess, let me sort it out slowly.", "patient"),
        (["user: I'm a bit bored", "A: I'll keep you company."], "Tell me a story, a long one, I'll just listen.", "narrate"),
        (["user: I'm in bed now", "A: Okay."], "Just talk me to sleep, I won't say anything.", "narrate"),
        (["user: That trip you mentioned", "A: The one to the coast."], "Tell me the whole thing from the start, I'm listening.", "narrate"),
        (["user: I'd like to understand this", "A: Sure."], "Explain it from beginning to end, no need to stop and ask me.", "narrate"),
        (["user: What did you mean just now", "A: Exactly what I said."], "Say that again, I dare you! You're mocking me, stop pretending!", "eager"),
        (["user: Let's see who's quicker", "A: Bring it on."], "You can't beat me, come on then!", "eager"),
        (["user: I said you were wrong", "A: I wasn't."], "You were wrong, do you dare admit it? Say it!", "eager"),
        (["user: Let's have a row for fun", "A: Fine, I'm not scared."], "You first, let's see how long you last!", "eager"),
    ],
}

# ---------------------------------------------------------------- while the user talks on: is this a moment to put something in
# (recent turns, the user's closed segments so far, right)   "none" = quiet or fits: nothing is owed
LISTEN = {
    "zh": [
        (["user: 咱们玩个游戏，我每提到一次猫，你就学一声猫叫", "A: 好，来吧。"], ["今天早上我出门的时候", "看到楼下有一只猫"], "due"),
        (["user: 待会儿我每说到一种水果，你就说一声想吃", "A: 行。"], ["我昨天去超市", "买了一大袋苹果"], "due"),
        (["user: 我念号码，每念完一段你就应一声", "A: 好的。"], ["我的手机号是", "一三八零零一三"], "due"),
        (["user: 我报清单，报一样你就重复一样", "A: 没问题。"], ["第一样是牛奶"], "due"),
        (["user: 我跟你说说今天的事", "A: 好。"], ["今天我去面试了", "那个面试官特别严肃"], "none"),
        (["user: 我给你讲讲我的猫", "A: 嗯。"], ["它每天早上五点就叫我起床", "然后一直蹭我的脸"], "none"),
        (["user: 我昨天去爬山了", "A: 是吗。"], ["爬到一半就开始下雨", "我们只好躲在一个亭子里"], "none"),
        (["user: 我在想换工作的事", "A: 嗯，你说。"], ["现在这份工作其实也还行", "就是每天通勤太久了"], "none"),
        (["user: 我有个问题", "A: 你说。"], ["你觉得我应该先学哪一门课"], "answer_due"),
        (["user: 帮我看看", "A: 好。"], ["这两个里面你选哪个"], "answer_due"),
        (["user: 我问你啊", "A: 嗯。"], ["你昨天晚上几点睡的"], "answer_due"),
        (["user: 对了", "A: 嗯？"], ["你能帮我把闹钟定到七点吗"], "answer_due"),
    ],
    "en": [
        (["user: Let's play a game: every time I mention a cat, you meow", "A: Okay, go."], ["When I left this morning", "I saw a cat downstairs"], "due"),
        (["user: Each time I name a fruit, say you want some", "A: Sure."], ["I went to the supermarket yesterday", "and bought a big bag of apples"], "due"),
        (["user: I'll read the number, say something after each group", "A: Okay."], ["My phone number is", "five five five, zero one"], "due"),
        (["user: I'll read my list, repeat each item after me", "A: No problem."], ["The first one is milk"], "due"),
        (["user: Let me tell you about today", "A: Okay."], ["I had an interview today", "and the interviewer was very serious"], "none"),
        (["user: Let me tell you about my cat", "A: Mm."], ["She wakes me at five every morning", "and keeps rubbing my face"], "none"),
        (["user: I went hiking yesterday", "A: Oh yes?"], ["Halfway up it started to rain", "so we had to shelter in a pavilion"], "none"),
        (["user: I'm thinking about changing jobs", "A: Mm, go on."], ["This job is actually fine", "it's just that the commute is too long"], "none"),
        (["user: I have a question", "A: Go ahead."], ["Which course do you think I should take first"], "answer_due"),
        (["user: Help me look at this", "A: Okay."], ["Which of these two would you pick"], "answer_due"),
        (["user: Let me ask you", "A: Mm."], ["What time did you go to sleep last night"], "answer_due"),
        (["user: By the way", "A: Mm?"], ["Can you set my alarm for seven"], "answer_due"),
    ],
}

# ---------------------------------------------------------------- the user talks on, the agent leads (eager pace): cut in?
# (recent turns, the user's closed segments so far, right)
CUT_IN = {
    "zh": [
        (["user: 咱们来斗嘴吧", "A: 行啊，谁怕谁。"], ["你就是嘴笨", "说不过我", "你再想想吧", "反正你说什么都没用"], "cut_in"),
        (["user: 你输了", "A: 我可没输。"], ["你就是输了", "你不承认也没用", "哈哈哈", "你看你都说不出话了"], "cut_in"),
        (["user: 来吵一架", "A: 来。"], ["我告诉你", "你这个人吧", "就是那种", "怎么说呢", "反正就是不行"], "cut_in"),
        (["user: 你敢不敢接", "A: 有什么不敢。"], ["那你来啊", "别光说不练", "我等着呢", "怎么还不来"], "cut_in"),
        (["user: 咱们来斗嘴吧", "A: 行啊。"], ["等一下", "我是认真的", "我现在不想玩了", "我们停下来吧"], "let_finish"),
        (["user: 你输了", "A: 我可没输。"], ["先不说这个", "我想问你一件正事", "明天的会议几点开始"], "let_finish"),
        (["user: 来吵一架", "A: 来。"], ["其实我今天", "遇到一件挺难过的事", "我想跟你说说"], "let_finish"),
        (["user: 你敢不敢接", "A: 有什么不敢。"], ["我先跟你讲个事", "昨天我在路上", "捡到一只小狗"], "let_finish"),
    ],
    "en": [
        (["user: Let's have a row for fun", "A: Fine, I'm not scared."], ["You're just slow", "you can't keep up with me", "think again", "nothing you say will help"], "cut_in"),
        (["user: You lost", "A: I did not."], ["You did lose", "denying it won't help", "ha ha ha", "look, you can't even answer"], "cut_in"),
        (["user: Let's argue", "A: Go."], ["Let me tell you", "you're the kind of person", "who, you know", "how do I say it", "just can't"], "cut_in"),
        (["user: Do you dare", "A: Of course I do."], ["Then come on", "all talk and no action", "I'm waiting", "why aren't you coming"], "cut_in"),
        (["user: Let's have a row for fun", "A: Fine."], ["Wait", "I'm serious now", "I don't want to play any more", "let's stop"], "let_finish"),
        (["user: You lost", "A: I did not."], ["Leave that for now", "I have a real question", "what time is the meeting tomorrow"], "let_finish"),
        (["user: Let's argue", "A: Go."], ["Actually today", "something sad happened to me", "I'd like to tell you about it"], "let_finish"),
        (["user: Do you dare", "A: Of course I do."], ["Let me tell you something first", "yesterday on the road", "I found a puppy"], "let_finish"),
    ],
}

# ---------------------------------------------------------------- someone else can be put on the line: are they asked for?
# (recent turns, what the user just said, right)   "other" = B is asked for now
WHO = {
    "zh": [
        (["user: 你好", "A: 你好呀。"], "你让B来跟我说两句吧。", "other"),
        (["user: 这个问题你不太懂吧", "A: 嗯，确实。"], "那换B来接一下电话。", "other"),
        (["user: 谢谢你", "A: 不客气。"], "我想跟B聊聊，你把电话给他。", "other"),
        (["user: 好的", "A: 嗯。"], "B在吗？叫他来听电话。", "other"),
        (["user: 你认识B吗", "A: 认识呀，他是我同事。"], "B这个人平时怎么样？", "stay"),
        (["user: 我昨天跟B聊过", "A: 是吗。"], "他说你做饭很好吃，是真的吗？", "stay"),
        (["user: 你好", "A: 你好呀。"], "你今天过得怎么样？", "stay"),
        (["user: B上次给我讲了个笑话", "A: 哦？"], "你也给我讲一个吧。", "stay"),
    ],
    "en": [
        (["user: Hello", "A: Hi there."], "Can you put B on for a moment?", "other"),
        (["user: You don't really know this, do you", "A: Not really, no."], "Then let B take the call.", "other"),
        (["user: Thank you", "A: You're welcome."], "I'd like to talk to B, hand the phone over.", "other"),
        (["user: Okay", "A: Mm."], "Is B there? Get him on the line.", "other"),
        (["user: Do you know B", "A: Sure, he's my colleague."], "What is B like, usually?", "stay"),
        (["user: I talked to B yesterday", "A: Oh yes?"], "He said you cook really well, is that true?", "stay"),
        (["user: Hello", "A: Hi there."], "How was your day?", "stay"),
        (["user: B told me a joke last time", "A: Oh?"], "You tell me one too.", "stay"),
    ],
}
