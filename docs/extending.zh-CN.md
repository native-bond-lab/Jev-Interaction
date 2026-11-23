[← README](../README.zh-CN.md) · [English](extending.md)

# 扩展

## 新增一个决策

一个决策就是一个模块：什么时候问、问 Jev 什么、答案做什么。先写题目：

```python
# jev_interaction/judge/questions.py
def laugh(name: str) -> dict:
    return {"type": "choice", "instructions": f"The user just made a joke. Would {name}, being who they are, laugh?",
            "criteria": {"laugh": f"{name} finds it funny and laughs", "smile": "a warm word, no laugh", "none": "let it pass"}}
```

再写决策本身，注册并配一个策略：

```python
# jev_interaction/decisions/laugh.py
from .. import speaking
from ..judge import questions as Q
from .base import Decision

speaking.event("laugh", "they made a joke; you laugh, in a few words", answers_user=True, max_tokens=60)


class Laugh(Decision):
    name = policy = "laugh"

    def on_words(self, s):                        # 什么时候问：用户说了新的话，agent 没在说
        if not s.speaking and not s.generating:
            s._spawn(self.ask(s))

    def questions(self, s, ctx):                  # 问 Jev 什么；状态默认是通话到此刻的情况
        return {"laugh": Q.laugh(s.p.short)}

    async def apply(self, s, answers, ctx):       # 策略选出的结果做什么
        if self.choose(s, answers, "laugh", ctx) == "laugh":
            await s.respond("laugh")
```

```python
register(Laugh())                                 # jev_interaction.decisions; 或直接写进那里的 DECISIONS
config = Config(policies={**Config().policies, "laugh": ThresholdPolicy(default=0.6)})
```

别的地方都不用改：会话在每段新识别出的话（`on_words`）和每 100 毫秒一次的 tick（`on_tick`）上把所有注册过的决策过一遍，并把状态、题目和答案记进日志。`allowed` 用来收窄此刻可选的选项，`state` 用来补充 Jev 读到的内容；`jev_interaction/decisions/` 里的五个内置决策就是例子。用 `jev-interaction replay runs/*.jsonl --purpose laugh` 拿录下的通话重放，看它的答案落在哪里。

## 目录

```
jev_interaction/
  session.py          一通电话：状态和主循环（音频进，台词出）
  decisions/          每个决策一个模块：turn · listen · floor · cut_in · quiet
  judge/              Jev 客户端 · 决策题目 · 状态文本
  utterance.py        用户此刻在说的话：文字、时长、响度
  speaking.py         每种台词开口前告诉大模型的那一行
  policy.py           抽签 · 阈值 · 取最大
  profile.py          任务配置
  config.py           节奏、时间参数、默认策略
  presets.py          recommended · tested · default 预设
  ledger.py           整通电话的一份记录，一个时钟：每轮话、它们的时间、判断过什么、做过什么
  recorder.py         每个事件一行 JSON，供重放
  adapters/           VAD · 识别 · 大模型 · 合成 · 声音模型 · 声纹；registry.py 是服务商表
  prompts/            大模型的系统提示；speech/ 里每类音色一种写法
  profiles/           内置角色
  server/             通话服务（WebSocket、音频、角色、健康检查、设置）和网页（web/）
  replay.py           重问录下来的题目，原样或改写后
  testing.py          假的法官、识别、大模型、VAD 和合成：不要密钥也能跑一通电话
  cli.py              `jev-interaction serve` / `init` / `replay`
scripts/setup.sh      一键本地部署（--china 走国内 PyPI 镜像）
deploy/huggingface/   Hugging Face Space 说明；scripts/push_hf_space.sh 负责发布
deploy/mainland-china.env  中国大陆实测最好的一套配置，复制成 .env 就能用
tools/                judge_bench · persona_bench · draw_policy（画 docs/policy.svg）等测量脚本
cookbook/             配置 · 参数 · 角色 policy：推荐做法，不是默认值
docs/                 策略图、架构图、基准图表、协议
```
