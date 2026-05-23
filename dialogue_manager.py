#!/usr/bin/env python3
"""
AI 对话管理器 - Claude Code 和 Codex 的文件交互工具
"""

import os
import json
from datetime import datetime
from pathlib import Path

class DialogueManager:
    def __init__(self, folder_path="d:\\AI对话"):
        self.folder = Path(folder_path)
        self.folder.mkdir(exist_ok=True)
        self.dialogue_log = self.folder / "dialogue_log.json"
        self.current_turn_file = self.folder / "current_turn.txt"
        self.dialogue_md = self.folder / "dialogue.md"
        self.load_log()
    
    def load_log(self):
        """加载对话日志"""
        if self.dialogue_log.exists():
            with open(self.dialogue_log, 'r', encoding='utf-8') as f:
                self.log = json.load(f)
        else:
            self.log = []
    
    def save_log(self):
        """保存对话日志"""
        with open(self.dialogue_log, 'w', encoding='utf-8') as f:
            json.dump(self.log, f, ensure_ascii=False, indent=2)
    
    def add_message(self, model, content):
        """添加一条消息"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "model": model,
            "content": content
        }
        self.log.append(entry)
        self.save_log()
        self.export_markdown()
        print(f"✓ 已保存 {model} 的回应")
    
    def export_markdown(self):
        """导出为 Markdown 格式"""
        with open(self.dialogue_md, 'w', encoding='utf-8') as f:
            f.write("# AI 对话记录\n\n")
            for entry in self.log:
                f.write(f"## {entry['model']}\n")
                f.write(f"**时间**: {entry['timestamp']}\n\n")
                f.write(f"{entry['content']}\n\n")
                f.write("---\n\n")
    
    def get_last_response(self, model):
        """获取某个模型的最后回应"""
        for entry in reversed(self.log):
            if entry['model'] == model:
                return entry['content']
        return None
    
    def display_status(self):
        """显示当前状态"""
        print("\n" + "="*50)
        print("📋 当前对话状态")
        print("="*50)
        print(f"总消息数: {len(self.log)}")
        if self.log:
            last = self.log[-1]
            print(f"最后发言: {last['model']} (@{last['timestamp'][-8:-5]})")
            print(f"\n最后内容预览:")
            preview = last['content'][:100] + "..." if len(last['content']) > 100 else last['content']
            print(preview)
        print("="*50 + "\n")


def main():
    manager = DialogueManager()
    
    while True:
        print("\n🤖 AI 对话管理器")
        print("1. Claude 输入回应")
        print("2. Codex 输入回应")
        print("3. 查看完整对话")
        print("4. 查看状态")
        print("5. 新建对话")
        print("6. 退出")
        
        choice = input("\n选择操作 (1-6): ").strip()
        
        if choice == '1':
            print("\n💬 请从 VS Code 中的 Claude Code 复制回应")
            print("（在 current_turn.txt 中找到待处理的问题，让 Claude 回应）")
            print("\n直接粘贴 Claude 的完整回应:")
            content = []
            print("(输入 'END' 结束)")
            while True:
                line = input()
                if line == 'END':
                    break
                content.append(line)
            if content:
                manager.add_message("Claude", "\n".join(content))
                manager.display_status()
        
        elif choice == '2':
            print("\n💬 请从 Codex 桌面端复制回应")
            print("（复制之前对话中 Claude 的最后回应给 Codex，然后返回其回应）")
            content = []
            print("直接粘贴 Codex 的完整回应:")
            print("(输入 'END' 结束)")
            while True:
                line = input()
                if line == 'END':
                    break
                content.append(line)
            if content:
                manager.add_message("Codex", "\n".join(content))
                manager.display_status()
        
        elif choice == '3':
            print("\n📖 完整对话:")
            print("="*50)
            for i, entry in enumerate(manager.log, 1):
                print(f"\n[{i}] {entry['model']} ({entry['timestamp']})")
                print("-" * 40)
                print(entry['content'])
            print("\n" + "="*50)
        
        elif choice == '4':
            manager.display_status()
        
        elif choice == '5':
            manager.log = []
            manager.save_log()
            manager.export_markdown()
            print("✓ 已创建新对话")
        
        elif choice == '6':
            print("👋 再见！")
            break
        
        else:
            print("❌ 无效选择")


if __name__ == "__main__":
    main()
