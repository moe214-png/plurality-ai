# 四模型 API 对话指南

这个模式会让 Claude、ChatGPT、DeepSeek、Gemini 按顺序自动接力讨论。

## 1. 初始化配置

```bat
python api_dialogue.py --init-config
```

会生成 `models_config.json`。你可以在里面修改模型名、顺序、每轮输出长度和系统提示词。

`continue_on_error` 为 `true` 时，某个模型调用失败会写入日志并继续调用后面的模型。

某个模型暂时不可用时，可以把它的 `enabled` 改成 `false`，脚本会跳过它。

## 2. 设置 API Key

推荐新建一个本地 `.env` 文件，不要把真实 key 发到聊天里。

复制 `.env.example` 为 `.env`，然后填写：

```text
TOKENFREE_API_KEY=你的 tokenfree key
DEEPSEEK_API_KEY=你的 DeepSeek key
```

当前配置里 Claude、ChatGPT、Gemini 都走：

```text
https://api.tokenfree.shop/v1/chat/completions
```

所以它们共用 `TOKENFREE_API_KEY`。

也可以临时在 PowerShell 里设置：

```powershell
$env:TOKENFREE_API_KEY="你的 tokenfree key"
$env:DEEPSEEK_API_KEY="你的 DeepSeek key"
```

如果想长期保存，可以用 Windows 用户环境变量设置。

## 3. 开始一轮四模型对话

### 网页端

双击 `start_panel.bat`，或者运行：

```bat
python panel.py
```

然后打开：

```text
http://127.0.0.1:5000
```

网页端可以输入初始提示词、选择轮数和对话频率、开启或关闭模型，并直接编辑每个 AI 的人格设定。

发言方式有两种：

- `固定顺序`：按配置里的模型顺序依次发言。
- `自然抢话`：每一步先让各个 AI 用很短回复判断自己是否想发言，再选择意愿最强的一位正式发言。这个模式更像真人群聊，但会增加额外 API 调用。

`连续发言上限` 用来避免同一个 AI 一直抢话。默认是 `1`，表示自然抢话模式下同一个 AI 不能连续发言。

`自我记忆条数` 控制每个 AI 在发言前能看到自己最近几次发言。它会把这些内容明确标为“你自己此前说过的话”，让同一个 AI 更像一个连续的人，而不是每次重新开始。

自然抢话有两种选择策略：

- `快速裁判`：只调用一个裁判模型选择下一位发言者，速度更快，默认用 DeepSeek。
- `逐个询问`：分别询问每个 AI 是否想说话，更像“每个人自己决定”，但明显更慢。

自然模式默认开启软发言均衡：最近说得少的 AI 会获得额外权重，但不会强制轮流。`natural_balance_strength` 越高越平均，越低越自然。

自然模式也默认开启沉默兜底：如果没有 AI 主动想说，系统会从可发言者里选一个最近说得较少的 AI 接话，避免对话突然停住。

自然模式默认使用加权抽样：不会总选最高分，而是在合适候选里按分数抽一个，因此比固定最高分更像真人群聊。`natural_pick_strategy` 可设为 `sample` 或 `max`。

每个模型还有 `发言权重`。权重越高，越容易在自然模式里被选中。DeepSeek 默认设为 `1.5`，用于改善它过于安静的问题；其他模型默认是 `1.0`。

### 命令行

```bat
python api_dialogue.py --reset --rounds 1 --prompt "请讨论这个项目如何实现多个 AI 自动对话"
```

多轮：

```bat
python api_dialogue.py --reset --rounds 3 --prompt "围绕一个小说设定进行头脑风暴"
```

你想参与对话时，加 `--interactive`。每个 AI 回答后，脚本会停下来等你输入；直接回车继续，输入文字就是插入你的发言，输入 `/q` 结束。

```bat
python api_dialogue.py --reset --rounds 2 --interactive --prompt "讨论我的项目下一步怎么做"
```

从文件读取初始问题：

```bat
python api_dialogue.py --reset --rounds 2 --prompt-file question.txt
```

## 4. 输出文件

- `api_dialogue_log.json`：结构化日志
- `api_dialogue.md`：Markdown 版本
- `models_config.json`：模型和流程配置

## 5. 长度控制

`API token 上限` 是接口层面的最大输出 token，主要防止模型失控输出太长。

`发言最少字数` 和 `发言最多字数` 是网页可见长度标准，会写进每个 AI 的提示词里，让不同模型尽量按相近的中文字数发言。通常建议把 token 上限设得比字数范围宽松一些，例如字数范围 `160-220`，token 上限 `500`。

## 6. 模型名

默认模型名只是起步配置：

- Claude: `claude-sonnet-4-6`
- ChatGPT: `gpt-5.5`
- DeepSeek: `deepseek-v4-flash`
- Gemini: `gemini-3.5-flash`

如果你的账号后台显示不同模型名，直接改 `models_config.json` 里的 `model` 字段即可。
