# Claude & Codex 对话系统

## 📋 工作流程

### 1️⃣ 初始化
- 运行 `start.bat` 启动管理器
- 选择"新建对话"开始

### 2️⃣ 对话流程

#### Step 1: Claude 回应
```
1. 打开 VS Code，找一个聊天窗口
2. 输入你的问题：
   "请分析这个代码的性能问题..."
3. 等待 Claude 生成完整回应
4. 复制整个回应
5. 回到管理器，选择"1"
6. 粘贴内容，输入 END
```

#### Step 2: Codex 回应
```
1. 复制管理器中显示的 Claude 最后回应
2. 打开 Codex 桌面端
3. 粘贴问题，让 Codex 继续分析/改进
4. 复制 Codex 的完整回应
5. 回到管理器，选择"2"
6. 粘贴内容，输入 END
```

#### Step 3: 继续对话
- 重复 Step 1-2，直到对话结束

### 3️⃣ 查看结果

运行后，你会自动获得：

**dialogue_log.json** - 结构化日志
```json
[
  {
    "timestamp": "2026-05-15T...",
    "model": "Claude",
    "content": "..."
  },
  ...
]
```

**dialogue.md** - 易读的 Markdown 版本
- 可在任何 Markdown 查看器中打开
- 自动记录时间戳

## 📂 文件结构

```
d:\AI对话\
├── start.bat                # 启动脚本
├── dialogue_manager.py      # 核心管理器
├── dialogue_log.json        # 结构化日志
├── dialogue.md              # Markdown 日志
└── current_turn.txt         # 当前轮次（可选）
```

## 🎯 优势

✓ **无需 API** - 纯文件交互  
✓ **离线运行** - 本地文件系统  
✓ **自动记录** - 完整的对话历史  
✓ **易于导出** - JSON + Markdown 双格式  
✓ **灵活扩展** - 可添加更多模型  

## 💡 使用技巧

1. **快速查看** - 选择"3"随时查看完整对话
2. **导出分享** - dialogue.md 可直接分享
3. **批量导入** - 修改 dialogue_log.json 手动导入历史
4. **多人协作** - 共享对话文件夹实现团队协作

## 🔧 高级用法

### 添加自己的模型
编辑 `dialogue_manager.py`，在 `main()` 中添加：
```python
elif choice == '3':
    print("\n💬 请从你的模型复制回应")
    # ... 类似的输入流程
    manager.add_message("YourModel", content)
```

### 导入现有对话
直接编辑 `dialogue_log.json`，按格式添加条目

---

**开始对话吧！** 🚀
