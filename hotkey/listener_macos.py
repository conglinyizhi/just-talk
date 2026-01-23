"""macOS 全局快捷键监听器 - 使用 Quartz CGEventTap"""

import logging
import threading
from typing import Dict, Optional, Set

from PyQt6.QtCore import QThread, pyqtSignal

from hotkey.config import GlobalHotkeySettings

LOG = logging.getLogger(__name__)

# 全局权限检查标志：程序启动后只在第一次调用时检查权限
_accessibility_checked = False
_accessibility_granted = False


def check_accessibility_permission() -> bool:
    """检查是否有辅助功能权限"""
    try:
        from ApplicationServices import AXIsProcessTrusted
        return AXIsProcessTrusted()
    except ImportError:
        # 如果无法导入，假设没有权限
        return False


def request_accessibility_permission() -> bool:
    """请求辅助功能权限（会弹出系统对话框）"""
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions
        from Foundation import NSDictionary

        # kAXTrustedCheckOptionPrompt = True 会弹出系统对话框
        options = NSDictionary.dictionaryWithObject_forKey_(
            True, "AXTrustedCheckOptionPrompt"
        )
        return AXIsProcessTrustedWithOptions(options)
    except ImportError:
        return False


def check_accessibility_once() -> bool:
    """检查辅助功能权限（仅在程序启动后第一次调用时检查）

    使用全局 flag 缓存结果，避免重复检查。
    """
    global _accessibility_checked, _accessibility_granted
    if not _accessibility_checked:
        _accessibility_granted = check_accessibility_permission()
        _accessibility_checked = True
        if not _accessibility_granted:
            LOG.warning("Accessibility permission not granted")
    return _accessibility_granted


class MacOSHotkeyListenerThread(QThread):
    """macOS 专用的全局快捷键监听器，使用 Quartz CGEventTap

    修饰键映射 (内部键名 -> macOS 键名):
    - ctrl -> Control (⌃)
    - super -> Command (⌘)
    - alt -> Option (⌥)
    - shift -> Shift (⇧)
    """

    # Qt信号用于线程安全通信
    hotkey_pressed = pyqtSignal(str, str)  # (hotkey_id, action: "press"/"release"/"toggle")
    mouse_button_event = pyqtSignal(str, str)  # (button_id, action: "press"/"release")
    snippet_triggered = pyqtSignal(str, str)  # (snippet_id, text)
    listener_error = pyqtSignal(str)

    def __init__(self, config: GlobalHotkeySettings) -> None:
        super().__init__()
        self._config = config
        self._stop_event = threading.Event()
        self._tap = None

    def update_config(self, config: GlobalHotkeySettings) -> None:
        """更新配置"""
        self._config = config

    def stop(self) -> None:
        """请求停止监听器"""
        self._stop_event.set()

    def _convert_keys_to_macos(self, keys: list) -> Set[str]:
        """将内部键名转换为 macOS 键名

        内部键名: ctrl, super, alt, shift
        macOS 键名: control, command, option, shift
        """
        key_map = {
            "ctrl": "control",
            "super": "command",
            "alt": "option",
            "shift": "shift",
        }
        return {key_map.get(k, k) for k in keys}

    def run(self) -> None:
        """主线程循环 - 运行 Quartz 事件监听"""
        # 检查辅助功能权限（仅在程序启动后第一次调用时检查，使用全局缓存）
        check_accessibility_once()

        try:
            import Quartz
            from Quartz import (
                CGEventTapCreate,
                CGEventTapEnable,
                CGEventTapIsEnabled,
                CFMachPortCreateRunLoopSource,
                CFRunLoopGetCurrent,
                CFRunLoopAddSource,
                kCGSessionEventTap,
                kCGHeadInsertEventTap,
                kCGEventTapOptionListenOnly,
                kCGEventKeyDown,
                kCGEventKeyUp,
                kCGEventFlagsChanged,
                kCGEventOtherMouseDown,
                kCGEventOtherMouseUp,
                kCFRunLoopCommonModes,
            )
        except ImportError as e:
            self.listener_error.emit(
                f"无法导入 Quartz 库: {e}\n"
                "请运行: pip install pyobjc-framework-Quartz"
            )
            return

        # 状态跟踪
        pressed_keys: Set[str] = set()
        active_combos: Dict[str, bool] = {}
        last_modifiers: Set[str] = set()

        def get_modifier_names(flags: int) -> Set[str]:
            """从 Quartz 标志位获取修饰键名称

            使用 macOS 原生名称：control, command, option, shift
            """
            modifiers = set()
            if flags & Quartz.kCGEventFlagMaskControl:
                modifiers.add("control")
            if flags & Quartz.kCGEventFlagMaskCommand:
                modifiers.add("command")
            if flags & Quartz.kCGEventFlagMaskAlternate:
                modifiers.add("option")
            if flags & Quartz.kCGEventFlagMaskShift:
                modifiers.add("shift")
            return modifiers

        def keycode_to_name(keycode: int) -> Optional[str]:
            """将 macOS 虚拟键码转换为键名"""
            keycode_map = {
                0: "a", 1: "s", 2: "d", 3: "f", 4: "h", 5: "g", 6: "z", 7: "x",
                8: "c", 9: "v", 11: "b", 12: "q", 13: "w", 14: "e", 15: "r",
                16: "y", 17: "t", 18: "1", 19: "2", 20: "3", 21: "4", 22: "6",
                23: "5", 24: "=", 25: "9", 26: "7", 27: "-", 28: "8", 29: "0",
                31: "o", 32: "u", 34: "i", 35: "p", 37: "l", 38: "j", 40: "k",
                45: "n", 46: "m",
                36: "enter", 48: "tab", 49: "space", 51: "backspace", 53: "esc",
                122: "f1", 120: "f2", 99: "f3", 118: "f4", 96: "f5", 97: "f6",
                98: "f7", 100: "f8", 101: "f9", 109: "f10", 103: "f11", 111: "f12",
            }
            return keycode_map.get(keycode)

        def check_hotkeys(all_pressed: Set[str]) -> None:
            """检查是否触发了快捷键"""
            for hotkey_id, config in self._config.keyboard_hotkeys.items():
                if not config.enabled:
                    continue

                # 将配置的键名转换为 macOS 格式
                required_keys = self._convert_keys_to_macos(config.keys)

                if required_keys.issubset(all_pressed):
                    if hotkey_id not in active_combos:
                        active_combos[hotkey_id] = True
                        LOG.debug(f"Hotkey triggered: {hotkey_id}, keys={required_keys}")

                        if config.mode == "hold":
                            self.hotkey_pressed.emit(hotkey_id, "press")
                        else:
                            self.hotkey_pressed.emit(hotkey_id, "toggle")

            # 检查文本片段
            for snip_id, snip_config in self._config.text_snippets.items():
                if not snip_config.enabled:
                    continue

                required_keys = self._convert_keys_to_macos(snip_config.keys)
                snip_key = f"snippet:{snip_id}"

                if required_keys == all_pressed:
                    if snip_key not in active_combos:
                        active_combos[snip_key] = True
                        self.snippet_triggered.emit(snip_id, snip_config.text)

        def check_releases(released: Set[str], current: Set[str]) -> None:
            """检查是否释放了快捷键"""
            to_remove = []

            for hotkey_id, config in self._config.keyboard_hotkeys.items():
                if hotkey_id not in active_combos:
                    continue

                required_keys = self._convert_keys_to_macos(config.keys)

                # 如果释放的键是快捷键的一部分
                if not released.isdisjoint(required_keys):
                    to_remove.append(hotkey_id)
                    LOG.debug(f"Hotkey released: {hotkey_id}")

                    if config.mode == "hold":
                        self.hotkey_pressed.emit(hotkey_id, "release")

            # 检查文本片段释放
            for snip_id in list(active_combos.keys()):
                if snip_id.startswith("snippet:"):
                    real_id = snip_id[8:]
                    snip_config = self._config.text_snippets.get(real_id)
                    if snip_config:
                        required_keys = self._convert_keys_to_macos(snip_config.keys)
                        if not released.isdisjoint(required_keys):
                            to_remove.append(snip_id)

            for hk_id in to_remove:
                if hk_id in active_combos:
                    del active_combos[hk_id]

        def event_callback(proxy, event_type, event, refcon):
            nonlocal last_modifiers, pressed_keys

            try:
                if event_type == kCGEventFlagsChanged:
                    # 修饰键状态变化
                    flags = Quartz.CGEventGetFlags(event)
                    current_modifiers = get_modifier_names(flags)

                    # 检测新按下和释放的修饰键
                    newly_pressed = current_modifiers - last_modifiers
                    released = last_modifiers - current_modifiers
                    last_modifiers = current_modifiers.copy()

                    # 处理释放的修饰键
                    if released:
                        check_releases(released, current_modifiers)

                    # 更新按下的修饰键状态
                    pressed_keys -= {"control", "command", "option", "shift"}
                    pressed_keys |= current_modifiers

                    # 如果有新按下的修饰键，检查快捷键
                    if newly_pressed:
                        all_pressed = pressed_keys | current_modifiers
                        check_hotkeys(all_pressed)

                elif event_type == kCGEventKeyDown:
                    # 普通按键按下
                    keycode = Quartz.CGEventGetIntegerValueField(
                        event, Quartz.kCGKeyboardEventKeycode
                    )
                    key_name = keycode_to_name(keycode)
                    if key_name:
                        pressed_keys.add(key_name)
                        flags = Quartz.CGEventGetFlags(event)
                        modifiers = get_modifier_names(flags)
                        check_hotkeys(pressed_keys | modifiers)

                elif event_type == kCGEventKeyUp:
                    # 普通按键释放
                    keycode = Quartz.CGEventGetIntegerValueField(
                        event, Quartz.kCGKeyboardEventKeycode
                    )
                    key_name = keycode_to_name(keycode)
                    if key_name:
                        flags = Quartz.CGEventGetFlags(event)
                        modifiers = get_modifier_names(flags)
                        check_releases({key_name}, modifiers)
                        pressed_keys.discard(key_name)

                elif event_type == kCGEventOtherMouseDown:
                    # 鼠标其他按键按下
                    button = Quartz.CGEventGetIntegerValueField(
                        event, Quartz.kCGMouseEventButtonNumber
                    )
                    if button == 2:  # 中键
                        for mb_id, cfg in self._config.mouse_hotkeys.items():
                            if cfg.enabled and cfg.button == "middle":
                                if cfg.mode == "hold":
                                    self.mouse_button_event.emit(mb_id, "press")
                                else:
                                    self.mouse_button_event.emit(mb_id, "toggle")

                elif event_type == kCGEventOtherMouseUp:
                    # 鼠标其他按键释放
                    button = Quartz.CGEventGetIntegerValueField(
                        event, Quartz.kCGMouseEventButtonNumber
                    )
                    if button == 2:
                        for mb_id, cfg in self._config.mouse_hotkeys.items():
                            if cfg.enabled and cfg.button == "middle" and cfg.mode == "hold":
                                self.mouse_button_event.emit(mb_id, "release")

            except Exception as e:
                LOG.error(f"Event callback error: {e}")

            return event

        # 创建事件掩码
        event_mask = (
            (1 << kCGEventKeyDown) |
            (1 << kCGEventKeyUp) |
            (1 << kCGEventFlagsChanged) |
            (1 << kCGEventOtherMouseDown) |
            (1 << kCGEventOtherMouseUp)
        )

        # 创建事件 tap
        self._tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionListenOnly,
            event_mask,
            event_callback,
            None
        )

        if self._tap is None:
            # 再次请求权限
            request_accessibility_permission()
            self.listener_error.emit(
                "无法创建全局键盘监听器。\n\n"
                "这通常是因为缺少「辅助功能」权限：\n"
                "1. 打开「系统设置 → 隐私与安全性 → 辅助功能」\n"
                "2. 如果通过 Terminal 运行，需要给 Terminal 授权\n"
                "3. 如果是打包的应用，需要给应用本身授权\n"
                "4. 如果已授权但仍不工作，请取消勾选后重新勾选\n"
                "5. 重启应用"
            )
            return

        # 创建 RunLoop source
        run_loop_source = CFMachPortCreateRunLoopSource(None, self._tap, 0)
        run_loop = CFRunLoopGetCurrent()
        CFRunLoopAddSource(run_loop, run_loop_source, kCFRunLoopCommonModes)
        CGEventTapEnable(self._tap, True)

        LOG.info("macOS Quartz hotkey listener started")

        # 主循环
        while not self._stop_event.is_set():
            # 运行 RunLoop 一小段时间
            Quartz.CFRunLoopRunInMode(Quartz.kCFRunLoopDefaultMode, 0.1, False)

            # 检查 event tap 是否被系统禁用，如果是则重新启用
            if self._tap and not CGEventTapIsEnabled(self._tap):
                LOG.warning("CGEventTap was disabled by system, re-enabling...")
                CGEventTapEnable(self._tap, True)

        LOG.info("macOS Quartz hotkey listener stopped")
