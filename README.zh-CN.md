<div align="center">

# jev-interaction

**语音助手的轮次交互：写出来的决策，而不是训练出来的模型。**

[English](README.md) · [可交互架构图](docs/architecture.html) · [任务配置](examples/profiles) · [决策题目](jev_interaction/judge/questions.py)

![python](https://img.shields.io/badge/python-3.10%2B-3776ab) ![status](https://img.shields.io/badge/status-alpha-f59e0b) ![judge](https://img.shields.io/badge/judge-Jev-0f766e) ![duplex](https://img.shields.io/badge/full--duplex-voice-6366f1)

</div>

![jev-interaction 架构](docs/architecture.svg)

常见的语音助手在"语音识别 → 大模型 → 语音合成"上加一个端点模型，专门猜**用户说完没**。人在电话里会做的其他事都交给计时器：边听边"嗯嗯"、等对方想词、被打断就停、冷场时接一句、聊完了挂电话。

**jev-interaction 把这些都拆成明确的决策。** 每个决策是一道用自然语言写的选择题；[Jev](https://typesafe.ai) 在几十毫秒内给每个选项一个概率；再由策略把概率变成动作。题目、策略和角色的交互习惯都是看得懂的文字，可以直接改，也可以拿真实通话重放验证。

## 为什么

| | 常见语音助手 | jev-interaction |
|---|---|---|
| 什么时候回话 | 训练好的端点模型，一个阈值 | 一道题，Jev 结合说的话、停顿时长和前文来判断 |
| 边听边应声 | 没有，或者固定音频 | 每次现判：接续的声、有感触的反应、重复关键词，或不出声 |
| 被打断 | 有声就停，或者从不停 | 继续、让路、说完这句、把话头拿回来、立刻接话 |
| 冷场 | 超时 | 接着说、问问还在不在、等着、挂电话，参考这位用户平时多久接话 |
| 不同产品 | 重新训练或调参 | 换一份任务配置：给 Jev 看的交互习惯，每类决策的策略 |
| 改行为 | 收数据、重训 | 改一句题目，用录下来的通话重放，上线 |

## 一个时刻是怎么判断的

用户讲到一半，停下来喘口气。系统把线上的情况写下来，然后提问：

```text
状态   Phone call between the user and Mara.
       Who Mara is: a companion character … On the call: a noisy, eager listener …
       Current pace of the call: normal.
       Recent call: …
       What the user has said so far: 0.6 s ago "and then my manager pulls me into a meeting"
       Right now the user has been quiet for 0.4 s.

提问   listen: continuer · feeling · echo · quiet · answer_due

Jev    feeling 0.46 · quiet 0.27 · continuer 0.22 · answer_due 0.05

策略   陪伴 → 按概率抽签        →  "feeling"  →  角色说一句 "Oh no."，用户接着讲
       客服 → 阈值 0.8           →  没有选项过线  →  不出声
```

同一道题、同样形状的答案，怎么读由任务配置决定。

## 决策一览

| 什么时候 | 题目 | 选项 |
|---|---|---|
| 用户停顿 | `turn` | 说完了 / 还要说 · 再等多久 · 要回话 / 只是个声音 · 当前节奏 |
| 用户还在说 | `listen` | 接续的声 · 有感触的反应 · 重复关键词 · 不出声 · 该回答了 |
| 两人同时说话 | `floor` | 继续 · 让路 · 说完这句 · 把话头拿回来 · 立刻接话 · 简短回应 |
| 由角色主导时 | `cut_in` | 插话 · 让对方说完 |
| 冷场 | `quiet` | 接着说 · 问问还在不在 · 等着 · 挂电话 |

**节奏**（normal、patient、narrate、eager）表示谁掌握话头。各节奏的等待时间按 Jev 给的概率加权混合，不在最大的那个上硬切：Jev 判断"六成普通、四成耐心"时，等待时间就落在两者之间。

## 任务配置

一套框架，多种产品。配置写明角色是干什么的、电话里是什么习惯、每类决策怎么读。

| 配置 | 应声 | 说到一半停顿 | 被打断 | 冷场 | 策略 |
|---|---|---|---|---|---|
| [陪伴](examples/profiles/companion.yaml) | 常有，花样多 | 很快接话 | 立刻停，很高兴 | 主动填上 | 抽签 |
| [客服](examples/profiles/support.yaml) | 简短一声"好" | 等着（对方可能在念号码） | 立刻停 | 等着，久了问一次 | 阈值 |
| [家教](examples/profiles/tutor.yaml) | 鼓励的声音 | 非常耐心 | 先讲完这句 | 给个提示 | 抽签 |
| [面试官](examples/profiles/interviewer.yaml) | 不出声 | 让对方想 | 跑题就打断 | 等回答 | 混合 |

```yaml
name: Sam
task: 宽带公司的客服，尽快把来电者的问题讲清楚、解决掉。
prompt: >            # 给大模型看
  简明清楚，先复述确认，再一步一步带对方操作。
manner: >            # 给 Jev 看
  对方停顿很久也等他说完（可能在念号码）。被打断立刻停。
policies:
  end_of_turn: {type: threshold, default: 0.7}
  quiet: argmax
```

## 快速开始

```bash
git clone https://github.com/yj972/jev-interaction && cd jev-interaction
pip install -e ".[server]"
cp .env.example .env     # JEV_API_KEY · 兼容 OpenAI 接口的大模型 · ELEVENLABS_API_KEY 和 VOICE_ID
uvicorn server.app:app --port 8080
```

打开 <http://localhost:8080>，选一个任务配置，点 **Call**。自带的是简单的能量 VAD，建议戴耳机。

### 在自己的代码里用

```python
from jev_interaction import Config, Profile
from jev_interaction.adapters import EnergyVAD
from jev_interaction.adapters.openai_compat import OpenAICompatResponder
from jev_interaction.adapters.scribe import ScribeRealtime
from jev_interaction.judge import JevClient
from jev_interaction.session import Session

session = Session(
    Profile.load("examples/profiles/support.yaml"),
    send=my_send,                       # 异步函数：把事件发给你的客户端
    judge=JevClient(),
    recognizer=ScribeRealtime(language="en"),
    responder=OpenAICompatResponder(),   # 任意兼容 OpenAI 接口的模型
    vad=EnergyVAD(),
    config=Config(language="en"),
)
await session.start()
await session.on_audio(frame)          # 每 200 毫秒一帧 16 kHz PCM16
await session.on_client({"type": "playback", "state": "idle"})
```

发给客户端的事件：`line`、`listen`、`hold`、`unhold`、`stop`、`finish_line`、`hangup`，以及用于展示的 `user`、`pace`、`decision`。客户端发回：`playback` 和 `heard`。

### 新增一个决策

```python
# jev_interaction/judge/questions.py
def laugh(name: str) -> dict:
    return {"type": "choice", "instructions": f"The user just made a joke. Would {name}, being who they are, laugh?",
            "criteria": {"laugh": f"{name} finds it funny and laughs", "smile": "a warm word, no laugh", "none": "let it pass"}}
```

在会话里合适的地方提问，在 `Config.policies` 里给它配一个策略，再用 `tools/replay.py` 拿录下的通话重放，看它的答案落在哪里。

## 初步结果

测的是这个框架所抽出的那套陪伴电话引擎（同一个决策层，识别和合成用 ElevenLabs），数据是 [Full-Duplex-Bench](https://github.com/DanielLin94144/Full-Duplex-Bench) v1.0，每类用固定随机种子抽 50 条。停顿两类用 gpt-4o-mini 当语言模型，插话用 grok-4.3。

| | 本引擎（样本数） | GPT-Realtime | Gemini 3.1 Flash Live（high / minimal） |
|---|---|---|---|
| 合成停顿被当成说完（越低越好） | 0.12（50） | 0.01 | 0.007 / 0.022 |
| 真人对话停顿被当成说完 | 0.18（50） | 0.12 | 0.10 / 0.15 |
| 被打断后接话 | 0.96（50） | 0.97 | 0.995 / 1.0 |
| 被打断后回话延迟（评测规则） | 平均 1.79 秒，中位 1.68 秒 | 1.50 秒 | 0.65 / 0.34 秒 |
| 回答相关度（0–5） | 4.35（grok 打分） | 3.85 | 4.12 / 3.58 |

插话这一项和商用系统同档，回答质量分也不错。停顿是短板：被算成"抢话"的 15 条里，9 条是角色以为线上没人说话、自己主动开口（测试音频开头没有接电话那一句，有些录音音量小，声音检测可能没听到用户），6 条是用户还没说完就答了，多数是答了多句话里的第一句。回话延迟主要花在语言模型写第一句上，决策本身只要几十毫秒。

### 案例：两个旋钮修好停顿

每个决策都连同 Jev 看到的状态记了下来，所以被算成"抢话"的 15 条停顿样本可以逐条追：9 条是用户还在说第一句、还没识别出字时，"安静了要不要开口"那道题被触发，角色自己开了口；4 条是应声超过了评测规定的 3 个词；2 条是用户说完一句完整的话就答了。改两个旋钮，在同样 100 条上测：

| | 合成停顿 | 真人对话停顿 |
|---|---|---|
| 改之前 | 0.12 | 0.18 |
| 用户声音还在继续时不问"要不要开口" | 0.06 | 0.12 |
| 再把应声限制在 3 个词以内 | **0.06** | **0.08** |

真人对话停顿已经好于上表里的商用系统（0.10–0.15）。这两个旋钮目前只在测试里验证过，还没改进引擎；整个过程没有重新训练任何模型。

第三个旋钮是"Jev 有 0.8 以上把握判断说完了才回答"。它把真人对话停顿降到 0.04，被打断后的回话也没变慢，但平常的回答慢了约 1 秒（中位从 0.8 秒到 1.8 秒）。所以先不开：代价看得见、量得出、随时能撤，这正是这套做法的意义。

## 可替换的部件

| 部件 | 接口 | 自带实现 |
|---|---|---|
| VAD | `is_voice(pcm) -> bool` | `EnergyVAD` |
| 语音识别 | 流式，按段输出 | `ScribeRealtime`（ElevenLabs） |
| 大模型 | `lines(messages)`，逐句流式 | `OpenAICompatResponder` |
| 语音合成 | `audio(text)`，流式字节 | `ElevenLabsTTS` |
| 法官 | `ask(questions, state)` | `JevClient` |
| 策略 | `choose(probs, allowed)`、`draw(p)` | 抽签、阈值、取最大 |

## 目录

```
jev_interaction/
  session.py          一通电话：输入、决策、说话
  judge/              Jev 客户端 · 决策题目 · 状态文本
  policy.py           抽签 · 阈值 · 取最大
  profile.py          任务配置
  config.py           节奏、时间参数、默认策略
  ledger.py           通话记录
  recorder.py         每个事件一行 JSON，供重放
  adapters/           VAD · 识别 · 大模型 · 合成
  prompts/system.md   大模型默认系统提示
server/app.py         WebSocket 通话服务和音频路由
web/                  最简网页客户端
tools/replay.py       用改过的题重问录下来的决策
docs/                 架构图和可交互演示
```

## 路线图

- 一句话写到句号就先送去合成，不等换行。
- 在现有接口后面接神经网络 VAD 和第二路识别。
- 任务配置评测：同一段音频、不同配置，量出行为差异。
- Full-Duplex-Bench v1.0 / v1.5 全量测试并公布数字。

## 常见问题

**一定要用 Jev 吗？** 法官只是一个接口（`ask(questions, state)`）。这个框架是用 Jev 搭建和测量的；其他能按选项给出概率的法官也能接进来。

**要快一定得用大模型吗？** 不用。决策只要几十毫秒，回话快慢取决于你接的语言模型。

**花费多少？** 按我们的测量，一分钟通话音频几美分，大头是语言模型。

## 状态

0.1，alpha，从一个仍在开发中的陪伴电话系统里抽出来。决策层是测过的部分；网页客户端和能量 VAD 还很简单。Jev 是托管 API（`JEV_API_KEY`）。许可证在仓库公开前确定。jev-interaction 是基于 Jev 的独立项目，与 TypeSafe 无关联、未获其背书。
