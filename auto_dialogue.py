#!/usr/bin/env python3
"""
完全自动化 AI 对话系统 - 文件监控版
支持不同模型通过文件系统自动交互
"""

import os
import json
import time
from datetime import datetime
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class DialogueFileHandler(FileSystemEventHandler):
    def __init__(self, manager):
        self.manager = manager
    
    def on_modified(self, event):
        """文件修改时触发"""
        if event.is_directory:
            return
        
        # 检测到新的 Claude 回应
        if event.src_path.endswith("claude_response.txt"):
            self.manager.process_claude_response()
        
        # 检测到新的 Codex 回应
        elif event.src_path.endswith("codex_response.txt"):
            self.manager.process_codex_response()


class AutoDialogueManager:
    def __init__(self, folder_path="d:\\AI对话"):
        self.folder = Path(folder_path)
        self.folder.mkdir(exist_ok=True)
        
        # 定义所有文件路径
        self.files = {
            'log': self.folder / "dialogue_log.json",
            'md': self.folder / "dialogue.md",
            'claude_input': self.folder / "awaiting_claude.txt",
            'claude_output': self.folder / "claude_response.txt",
            'codex_input': self.folder / "awaiting_codex.txt",
            'codex_output': self.folder / "codex_response.txt",
            'status': self.folder / "status.txt",
        }
        
        self.load_log()
        self.update_status()
    
    def load_log(self):
        """加载对话日志"""
        if self.files['log'].exists():
            with open(self.files['log'], 'r', encoding='utf-8') as f:
                self.log = json.load(f)
        else:
            self.log = []
    
    def save_log(self):
        """保存对话日志"""
        with open(self.files['log'], 'w', encoding='utf-8') as f:
            json.dump(self.log, f, ensure_ascii=False, indent=2)
        self.export_markdown()
    
    def add_message(self, model, content):
        """添加消息到日志"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "model": model,
            "content": content
        }
        self.log.append(entry)
        self.save_log()
        print(f"✓ [{datetime.now().strftime('%H:%M:%S')}] {model} 的回应已记录")
    
    def process_claude_response(self):
        """处理 Claude 的回应"""
        claude_file = self.files['claude_output']
        if not claude_file.exists():
            return
        
        with open(claude_file, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        
        if not content or content == "PROCESSING...":
            return
        
        # 记录 Claude 回应
        self.add_message("Claude", content)
        
        # 自动为 Codex 准备输入
        last_message = self.log[-2]['content'] if len(self.log) > 1 else "无"
        prompt = f"Claude 的前一个回应：\n\n{content}\n\n请您继续改进或扩展这个回应。"
        
        with open(self.files['codex_input'], 'w', encoding='utf-8') as f:
            f.write(prompt)
        
        # 清空 Claude 输出文件为占位符
        with open(self.files['claude_output'], 'w', encoding='utf-8') as f:
            f.write("WAITING_FOR_CODEX")
        
        print(f"⏳ 已为 Codex 准备输入，等待回应...")
        self.update_status("WAITING_CODEX")
    
    def process_codex_response(self):
        """处理 Codex 的回应"""
        codex_file = self.files['codex_output']
        if not codex_file.exists():
            return
        
        with open(codex_file, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        
        if not content or content == "PROCESSING...":
            return
        
        # 记录 Codex 回应
        self.add_message("Codex", content)
        
        # 为 Claude 准备下一个输入
        prompt = f"Codex 的最新回应：\n\n{content}\n\n请您基于这个回应继续讨论。"
        
        with open(self.files['claude_input'], 'w', encoding='utf-8') as f:
            f.write(prompt)
        
        # 清空 Codex 输出文件为占位符
        with open(self.files['codex_output'], 'w', encoding='utf-8') as f:
            f.write("WAITING_FOR_CLAUDE")
        
        print(f"⏳ 已为 Claude 准备输入，等待回应...")
        self.update_status("WAITING_CLAUDE")
    
    def export_markdown(self):
        """导出为 Markdown"""
        with open(self.files['md'], 'w', encoding='utf-8') as f:
            f.write("# 🤖 AI 对话记录（自动化）\n\n")
            f.write(f"_最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_\n\n")
            
            for i, entry in enumerate(self.log, 1):
                f.write(f"## [{i}] {entry['model']}\n")
                f.write(f"**时间**: {entry['timestamp']}\n\n")
                f.write(f"{entry['content']}\n\n")
                f.write("---\n\n")
    
    def update_status(self, state="IDLE"):
        """更新状态文件"""
        status = {
            "state": state,
            "timestamp": datetime.now().isoformat(),
            "total_messages": len(self.log),
            "last_model": self.log[-1]['model'] if self.log else None,
        }
        
        with open(self.files['status'], 'w', encoding='utf-8') as f:
            f.write(f"状态: {state}\n")
            f.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"总消息: {len(self.log)}\n")
            if self.log:
                f.write(f"最后发言者: {self.log[-1]['model']}\n")
    
    def start_watching(self):
        """启动文件监控"""
        print("\n" + "="*50)
        print("🔍 启动自动化对话系统...")
        print("="*50)
        print(f"📁 监控文件夹: {self.folder}")
        print(f"\n文件位置:")
        print(f"  Claude 输入: {self.files['claude_input']}")
        print(f"  Claude 输出: {self.files['claude_output']}")
        print(f"  Codex 输入: {self.files['codex_input']}")
        print(f"  Codex 输出: {self.files['codex_output']}")
        print(f"\n状态文件: {self.files['status']}")
        print(f"日志文件: {self.files['log']}")
        print("="*50)
        
        # 初始化文件
        for file_key in ['claude_input', 'claude_output', 'codex_input', 'codex_output']:
            if not self.files[file_key].exists():
                with open(self.files[file_key], 'w', encoding='utf-8') as f:
                    f.write("")
        
        # 启动文件监控
        event_handler = DialogueFileHandler(self)
        observer = Observer()
        observer.schedule(event_handler, str(self.folder), recursive=False)
        observer.start()
        
        print("\n✅ 系统已启动，监听文件变化...")
        print("⚠️  按 Ctrl+C 停止\n")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n⏹️  正在停止...")
            observer.stop()
            observer.join()
            print("✓ 系统已停止")


def main():
    manager = AutoDialogueManager()
    
    print("\n欢迎使用自动化对话系统！\n")
    print("选项:")
    print("1. 启动自动化监控")
    print("2. 查看完整对话")
    print("3. 新建对话")
    print("4. 查看当前状态")
    print("5. 手动输入初始问题")
    print("6. 退出")
    
    choice = input("\n选择 (1-6): ").strip()
    
    if choice == '1':
        manager.start_watching()
    
    elif choice == '2':
        print("\n" + "="*50)
        for i, entry in enumerate(manager.log, 1):
            print(f"\n[{i}] {entry['model']} ({entry['timestamp']})")
            print("-" * 40)
            print(entry['content'])
        print("\n" + "="*50)
    
    elif choice == '3':
        manager.log = []
        manager.save_log()
        print("✓ 已创建新对话")
    
    elif choice == '4':
        with open(manager.files['status'], 'r', encoding='utf-8') as f:
            print("\n" + f.read())
    
    elif choice == '5':
        question = input("\n输入初始问题:\n> ")
        with open(manager.files['claude_input'], 'w', encoding='utf-8') as f:
            f.write(question)
        print("✓ 已保存问题，等待 Claude 回应...")
    
    elif choice == '6':
        print("👋 再见！")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 错误: {e}")
