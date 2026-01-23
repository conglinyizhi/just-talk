"""全局快捷键监听器线程"""

import sys
import threading
import time
from typing import Dict, Optional, Set

from PyQt6.QtCore import QThread, pyqtSignal

from hotkey.config import GlobalHotkeySettings

# macOS 平台检测
_IS_MACOS = sys.platform == "darwin"


class HotkeyListenerThread(QThread):
    """在独立线程中运行pynput监听器"""

    # Qt信号用于线程安全通信
    hotkey_pressed = pyqtSignal(str, str)  # (hotkey_id, action: "press"/"release"/"toggle")
    mouse_button_event = pyqtSignal(str, str)  # (button_id, action: "press"/"release")
    snippet_triggered = pyqtSignal(str, str)  # (snippet_id, text)
    listener_error = pyqtSignal(str)

    def __init__(self, config: GlobalHotkeySettings) -> None:
        super().__init__()
        self._config = config
        self._stop_event = threading.Event()
        self._keyboard_listener: Optional[object] = None
        self._mouse_listener: Optional[object] = None

        # 状态跟踪
        self._pressed_keys: Set[str] = set()
        self._active_combos: Dict[str, bool] = {}  # 正在激活的组合键

    def stop(self) -> None:
        """请求停止监听器"""
        self._stop_event.set()
        if self._keyboard_listener:
            try:
                self._keyboard_listener.stop()
            except Exception:
                pass
        if self._mouse_listener:
            try:
                self._mouse_listener.stop()
            except Exception:
                pass

    def run(self) -> None:
        """主线程循环 - 运行pynput监听器"""
        try:
            from pynput import keyboard, mouse

            # 创建键盘监听器
            self._keyboard_listener = keyboard.Listener(
                on_press=self._on_key_press, on_release=self._on_key_release
            )

            # 创建鼠标监听器
            self._mouse_listener = mouse.Listener(on_click=self._on_mouse_click)

            # 启动监听器
            self._keyboard_listener.start()
            self._mouse_listener.start()

            # 等待停止信号
            while not self._stop_event.is_set():
                time.sleep(0.1)

        except ImportError as e:
            self.listener_error.emit(f"无法导入pynput库: {e}\n请运行: pip install pynput")
        except Exception as e:
            error_msg = str(e)
            # macOS 辅助功能权限错误的特殊处理
            if _IS_MACOS and ("accessibility" in error_msg.lower() or "trusted" in error_msg.lower()):
                self.listener_error.emit(
                    "全局快捷键需要辅助功能权限。\n\n"
                    "请打开「系统设置 → 隐私与安全性 → 辅助功能」，\n"
                    "然后允许本应用控制您的电脑。"
                )
            else:
                self.listener_error.emit(f"启动监听器失败: {e}")
        finally:
            # 清理
            if self._keyboard_listener:
                try:
                    self._keyboard_listener.stop()
                except Exception:
                    pass
            if self._mouse_listener:
                try:
                    self._mouse_listener.stop()
                except Exception:
                    pass

    def _normalize_key(self, key) -> str:
        """将pynput按键转换为标准字符串"""
        try:
            from pynput import keyboard

            # 特殊键映射
            special_map = {
                keyboard.Key.ctrl_l: "ctrl",
                keyboard.Key.ctrl: "ctrl",  # 通用Ctrl
                keyboard.Key.ctrl_r: "right_ctrl",
                keyboard.Key.cmd: "super",  # Linux/Mac/Windows
                keyboard.Key.cmd_l: "super",
                keyboard.Key.cmd_r: "right_super",
                keyboard.Key.alt_l: "alt",
                keyboard.Key.alt: "alt",
                keyboard.Key.alt_r: "right_alt",
                keyboard.Key.shift: "shift",
                keyboard.Key.shift_l: "shift",
                keyboard.Key.shift_r: "right_shift",
                keyboard.Key.space: "space",
                keyboard.Key.enter: "enter",
                keyboard.Key.tab: "tab",
                keyboard.Key.esc: "esc",
                keyboard.Key.backspace: "backspace",
                keyboard.Key.delete: "delete",
                keyboard.Key.home: "home",
                keyboard.Key.end: "end",
                keyboard.Key.page_up: "page_up",
                keyboard.Key.page_down: "page_down",
                keyboard.Key.up: "up",
                keyboard.Key.down: "down",
                keyboard.Key.left: "left",
                keyboard.Key.right: "right",
            }

            # 检查特殊键
            if key in special_map:
                return special_map[key]

            # 字母数字键
            if hasattr(key, "char") and key.char:
                return key.char.lower()

            # 功能键
            key_str = str(key).lower()
            if key_str.startswith("key."):
                return key_str[4:]  # 移除"key."前缀

            return key_str

        except Exception:
            return str(key).lower()

    @staticmethod
    def _modifier_keys() -> Set[str]:
        return {
            "ctrl",
            "right_ctrl",
            "super",
            "right_super",
            "alt",
            "right_alt",
            "shift",
            "right_shift",
        }

    def _on_key_press(self, key) -> None:
        """处理按键按下"""
        try:
            key_name = self._normalize_key(key)
            self._pressed_keys.add(key_name)

            # 检查所有配置的快捷键
            for hotkey_id, config in self._config.keyboard_hotkeys.items():
                if not config.enabled:
                    continue

                required_keys = set(config.keys)
                if required_keys.issubset(self._pressed_keys):
                    # 组合键匹配！
                    if hotkey_id not in self._active_combos:
                        self._active_combos[hotkey_id] = True

                        if config.mode == "hold":
                            # 按住模式 - 发送press事件
                            self.hotkey_pressed.emit(hotkey_id, "press")
                        else:
                            # toggle模式 - 发送toggle事件
                            self.hotkey_pressed.emit(hotkey_id, "toggle")

            # 检查文本片段快捷键
            for snip_id, snip_config in self._config.text_snippets.items():
                if not snip_config.enabled:
                    continue

                required_keys = set(snip_config.keys)
                # 精确匹配：按下的键必须完全等于配置的键
                if required_keys == self._pressed_keys:
                    # 片段快捷键触发（一次性，不需要跟踪active状态）
                    snip_key = f"snippet:{snip_id}"
                    if snip_key not in self._active_combos:
                        self._active_combos[snip_key] = True
                        self.snippet_triggered.emit(snip_id, snip_config.text)

        except Exception as e:
            self.listener_error.emit(f"按键处理错误: {e}")

    def _on_key_release(self, key) -> None:
        """处理按键释放"""
        try:
            key_name = self._normalize_key(key)
            modifier_keys = self._modifier_keys()

            # 检查是否释放了激活的组合键
            for hotkey_id, config in self._config.keyboard_hotkeys.items():
                if hotkey_id in self._active_combos and key_name in config.keys:
                    if config.mode == "hold":
                        non_modifier_keys = {k for k in config.keys if k not in modifier_keys}
                        if non_modifier_keys:
                            # 只允许非修饰键触发release，避免修饰键被清理导致误触发
                            if key_name not in non_modifier_keys:
                                continue
                            remaining = set(self._pressed_keys)
                            remaining.discard(key_name)
                            if remaining.intersection(non_modifier_keys):
                                continue
                    # 释放了组合键的一部分
                    del self._active_combos[hotkey_id]

                    if config.mode == "hold":
                        # 按住模式 - 发送release事件
                        self.hotkey_pressed.emit(hotkey_id, "release")

            # 清理片段快捷键的 active 状态
            for snip_id, snip_config in self._config.text_snippets.items():
                snip_key = f"snippet:{snip_id}"
                if snip_key in self._active_combos and key_name in snip_config.keys:
                    del self._active_combos[snip_key]

            self._pressed_keys.discard(key_name)

        except Exception as e:
            self.listener_error.emit(f"按键释放处理错误: {e}")

    def _on_mouse_click(self, x: int, y: int, button, pressed: bool) -> None:
        """处理鼠标点击"""
        try:
            from pynput import mouse

            # 只处理鼠标中键
            if button != mouse.Button.middle:
                return  # 忽略其他按钮

            button_name = "middle"

            # 检查配置的鼠标按键
            for mb_id, config in self._config.mouse_hotkeys.items():
                if not config.enabled or config.button != button_name:
                    continue

                if pressed:
                    # 按下
                    if config.mode == "hold":
                        self.mouse_button_event.emit(mb_id, "press")
                    else:
                        # toggle模式
                        self.mouse_button_event.emit(mb_id, "toggle")
                else:
                    # 释放
                    if config.mode == "hold":
                        self.mouse_button_event.emit(mb_id, "release")

        except Exception as e:
            self.listener_error.emit(f"鼠标点击处理错误: {e}")
