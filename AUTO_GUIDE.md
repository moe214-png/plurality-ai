# 自动化对话系统 - 快速指南

## 🎯 核心概念

系统通过 **文件监控** 自动管理对话流程，无需手动复制粘贴。

```
Claude 生成回应 
    ↓ (自动检测)
   文件: claude_response.txt
    ↓ (脚本自动处理)
生成 awaiting_codex.txt
    ↓ (Codex 自动读取)
   Codex 生成回应
    ↓ (自动检测)
文件: codex_response.txt
    ↓ (脚本自动处理)
生成 awaiting_claude.txt
    ↓ (循环)
```

## 📁 文件结构

启动后会在 `d:\AI对话\` 自动创建：

| 文件 | 用途 |
|------|------|
| `awaiting_claude.txt` | Claude 需要处理的内容 |
| `claude_response.txt` | Claude 的回应（由 Claude 写入） |
| `awaiting_codex.txt` | Codex 需要处理的内容 |
| `codex_response.txt` | Codex 的回应（由 Codex 写入） |
| `status.txt` | 当前系统状态 |
| `dialogue_log.json` | 完整对话日志 |
| `dialogue.md` | 漂亮的 Markdown 日志 |

## 🔧 配置 Codex 自动读写

由于 Codex 是桌面端，需要设置自动化流程。有几种选项：

### 选项 1: PowerShell 监控脚本（推荐）

在 `d:\AI对话\codex_auto.ps1` 创建：

```powershell
$folder = "d:\AI对话"
$inputFile = "$folder\awaiting_codex.txt"
$outputFile = "$folder\codex_response.txt"

while ($true) {
    # 检查输入文件是否有新内容
    if (Test-Path $inputFile) {
        $content = Get-Content $inputFile -Raw
        
        if ($content -and $content -ne "WAITING_FOR_CODEX") {
            Write-Host "📝 检测到新的输入: $content"
            
            # 这里需要手动步骤：
            # 1. 复制 $content 到 Codex
            # 2. 等待 Codex 生成回应
            # 3. 复制回应到 $outputFile
            
            Write-Host "✋ 请手动:"
            Write-Host "1. 复制上面的内容到 Codex"
            Write-Host "2. 得到回应后，粘贴到: $outputFile"
            Write-Host "3. 保存文件"
            
            # 等待用户输入完成
            Read-Host "按 Enter 继续..."
        }
    }
    
    Start-Sleep -Seconds 2
}
```

### 选项 2: 浏览器自动化（高级）

如果 Codex 是网页版，可以用 Selenium/Playwright 自动化。

### 选项 3: 手动指引工具

创建一个辅助脚本每隔几秒提醒：
```powershell
# 定期检查，如果有待处理内容，弹出提醒让用户处理
```

## 🚀 完整工作流

### 第一步：启动系统

```bash
cd d:\AI对话
python auto_dialogue.py
```

选择选项 `1` 启动自动化监控。

### 第二步：输入初始问题

编辑或创建 `awaiting_claude.txt`，写入你的问题：
```
分析这段代码的性能问题...
```

### 第三步：让 Claude 回应

1. 打开 VS Code 中的 Claude Code
2. 打开 `awaiting_claude.txt`
3. 让 Claude 帮你分析并编写回应
4. 将完整回应复制到 `claude_response.txt`
5. **保存文件** → 系统自动检测

### 第四步：让 Codex 回应

系统已自动在 `awaiting_codex.txt` 准备好 Claude 的回应。

1. 打开 Codex 桌面端
2. 从 `awaiting_codex.txt` 复制内容
3. 让 Codex 继续改进或分析
4. 将 Codex 的回应复制到 `codex_response.txt`
5. **保存文件** → 系统自动检测

### 第五步：继续对话

系统会自动：
- 保存所有回应到日志
- 为下一轮准备输入文件
- 更新状态文件

## 📊 监控对话进度

### 实时查看状态
```bash
# 打开并观看这个文件（会自动更新）
type d:\AI对话\status.txt
```

### 查看完整对话
```bash
# 随时可查看 Markdown 格式
notepad d:\AI对话\dialogue.md
```

### 检查 JSON 日志
```bash
# 结构化数据，用于进一步处理
type d:\AI对话\dialogue_log.json
```

## ⚙️ 自定义配置

编辑 `auto_dialogue.py` 的 `__init__` 方法修改：

```python
self.files = {
    'log': self.folder / "dialogue_log.json",
    # ... 修改文件名或路径
}
```

## 🔄 完全自动化（高级）

如果想完全自动化（包括 Codex），可以：

1. 编写 Codex 的自动化脚本（基于 Codex API 或浏览器自动化）
2. 创建一个协调脚本调用 Claude API + Codex 自动化
3. 完全由脚本控制整个对话流程

示例框架见 `advanced_automation.py`

## 🐛 故障排除

| 问题 | 解决方案 |
|------|--------|
| 系统无法检测文件变化 | 确保用编辑器**保存**文件，不只是修改 |
| 状态卡在某个地方 | 检查对应的输出文件是否有内容 |
| 日志不更新 | 检查文件权限，确保脚本可写入 |

---

**现在开始试试吧！** 🚀
