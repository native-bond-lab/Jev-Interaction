# jev-interaction

[English](README.md) · **中文**

一个全双工语音框架：**轮次交互不是一个要训练的模型，而是一组用自然语言写的决策。**

常见的语音助手在"识别 → 大模型 → 合成"上加一个端点模型，专门猜"用户说完没"。人在电话里会做的其他事情，比如边听边"嗯嗯"、等对方想词、被打断就停、冷场时接一句、聊完了挂电话，都交给计时器和阈值。

jev-interaction 把这些都拆成明确的决策：每个决策是一道给 [Jev](https://typesafe.ai) 的选择题，Jev 给每个选项一个概率，通常不到 100 毫秒；再由一个策略把概率变成动作。

![架构](docs/architecture.svg)

可交互的版本在 [docs/architecture.html](docs/architecture.html)：同一个时刻，分别按"陪伴"和"客服"两种任务来判断。本地打开即可，公开后可以放到 GitHub Pages。

## 带来什么

1. **不用训练端点模型。** 新增一种行为就是新写一道题；Jev 变强，所有决策一起变好。
2. **延迟可以换掉。** 交互决策只要几十毫秒，回话慢主要慢在大模型写第一句。换一个更快的模型，整通电话就快了，决策不用动。
3. **每个业务有自己的策略。** 同一套题，不同读法：陪伴按概率抽签，同一个时刻每次反应不完全一样；客服只在有把握时才动作。
4. **每种任务有自己的交互习惯。** 任务配置里的"交互习惯"会给 Jev 看，所以爱聊的陪伴、克制的客服、耐心的家教、面试官，对同一个时刻会做出不同判断。只听声音的端点模型做不到这一点。
5. **可迭代、看得见。** 每个决策都连同 Jev 看到的完整状态记下来。改一道题的措辞，用真实通话重问一遍（`tools/replay.py`），确认变好再上线。

## 决策一览

| 什么时候 | 题目 | 选项 |
|---|---|---|
| 用户停顿 | turn | 说完了 / 还要说、再等多久、要回话 / 只是个声音、当前节奏 |
| 用户还在说 | listen | 接续的声 / 有感触的反应 / 重复关键词追问 / 不出声 / 该回答了 |
| 两人同时说话 | floor | 继续 / 让路 / 说完这句 / 把话头拿回来 / 立刻接话 / 简短回应 |
| 由角色主导时 | cut_in | 插话 / 让对方说完 |
| 冷场 | quiet | 接着说 / 问问还在不在 / 等着 / 挂电话 |

节奏（normal、patient、narrate、eager）表示谁掌握话头。各节奏的等待时间按 Jev 给的概率加权混合，不在最大的那个上硬切。题目都在 `jev_interaction/judge/questions.py`，参数在 `config.py`。

## 任务配置

```yaml
name: Sam
task: 宽带公司的客服，尽快把来电者的问题讲清楚、解决掉。
prompt: >            # 给大模型
  简明清楚，先复述确认，再一步一步带对方操作。
manner: >            # 给 Jev
  对方停顿很久也等他说完（可能在念号码）。被打断立刻停。
policies:
  end_of_turn: {type: threshold, default: 0.7}
  quiet: argmax
```

`examples/profiles/` 里有陪伴、客服、语言家教、面试官四个例子。

## 运行

```bash
pip install -e ".[server]"
cp .env.example .env          # JEV_API_KEY、兼容 OpenAI 接口的大模型、ELEVENLABS_API_KEY / VOICE_ID
uvicorn server.app:app --port 8080
```

打开 http://localhost:8080，选一个任务配置，点 Call。自带的是简单的能量 VAD，建议戴耳机。

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
  session.py        一通电话：输入、决策、说话
  judge/            Jev 客户端、题目、状态文本
  policy.py         抽签 / 阈值 / 取最大
  profile.py        任务配置
  config.py         节奏、时间参数、默认策略
  ledger.py         通话记录
  recorder.py       每个事件一行 JSON，供回放
  adapters/         VAD、识别、大模型、合成
  prompts/system.md 大模型默认系统提示
server/app.py       WebSocket 通话服务和音频路由
web/                最简网页客户端
tools/replay.py     用改过的题重问记录下来的决策
```

## 状态

0.1，从一个仍在开发中的陪伴电话系统里抽出来。交互决策层是测过的部分；网页客户端和能量 VAD 还很简单。Jev 是托管 API（`JEV_API_KEY`）。许可证在公开前确定。jev-interaction 是基于 Jev 的独立项目，与 TypeSafe 无关联、未获其背书。
