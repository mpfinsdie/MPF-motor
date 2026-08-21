"""
DAQ 控制器模組
負責管理 Advantech USB-4716 裝置的初始化、連線與資源釋放

DAQNavi SDK 結構：
  專案根目錄/
  └── Automation/          ← 從 C:\Advantech\DAQNavi\Examples\Python\Automation\ 複製
      ├── __init__.py
      └── BDaq/
          ├── __init__.py  ← 含 ErrorCode, Scenario, ValueRange 等
          ├── InstantAiCtrl.py
          ├── InstantDiCtrl.py
          ├── WaveformAiCtrl.py
          └── ...

複製指令（PowerShell）：
  Copy-Item -Path "C:\Advantech\DAQNavi\Examples\Python\Automation" `
            -Destination "<專案根目錄>\Automation" -Recurse

AI 取樣架構（WaveformAiCtrl）：
  硬體 ADC → DMA → 環形緩衝區 → DataReady 事件 → Python 回呼
  取樣率：10,000 Hz/通道，每 0.1s 觸發一次 DataReady
"""

import sys
import os

# 嘗試匯入 DAQNavi SDK（Automation package）
try:
    from Automation.BDaq.InstantDiCtrl import InstantDiCtrl
    from Automation.BDaq.WaveformAiCtrl import WaveformAiCtrl
    from Automation.BDaq import ErrorCode, ValueRange
    from Automation.BDaq.BDaqApi import BioFailed
    DAQNAVI_AVAILABLE = True
except ImportError:
    DAQNAVI_AVAILABLE = False
    print("[警告] DAQNavi SDK (Automation package) 未找到，將使用模擬模式運行")
    print("       請將 C:\\Advantech\\DAQNavi\\Examples\\Python\\Automation\\ 複製到專案根目錄")


class DAQController:
    """
    Advantech USB-4716 DAQ 裝置控制器
    管理裝置生命週期與提供 WaveformAI / DI 存取介面

    AI 讀取：使用 WaveformAiCtrl（硬體緩衝串流，10 kHz/通道）
    DI 讀取：使用 InstantDiCtrl.readAny(portStart, portCount) → (ErrorCode, [int])
             使用 InstantDiCtrl.readBit(port, bit) → (ErrorCode, int)
    """

    DEVICE_DESCRIPTION = "USB-4716,BID#0"  # 裝置描述字串，BID#0 為第一個裝置

    def __init__(self, device_description: str = None):
        self.device_description = device_description or self.DEVICE_DESCRIPTION
        self._wfm_ctrl  = None   # WaveformAiCtrl（高速 AI 串流）
        self._di_ctrl   = None   # InstantDiCtrl（即時 DI）
        self._connected = False
        self._simulation_mode = not DAQNAVI_AVAILABLE

        if self._simulation_mode:
            print("[模擬模式] DAQNavi SDK 不可用，使用模擬資料")

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_simulation(self) -> bool:
        return self._simulation_mode

    def connect(self) -> tuple:
        """
        連線到 USB-4716 裝置
        Returns:
            tuple: (success: bool, error_msg: str | None)
                   success=True 且 error_msg=None  → 真實硬體連線成功
                   success=False 且 error_msg=str  → 連線失敗，error_msg 為原因
        """
        if self._simulation_mode:
            self._connected = True
            print(f"[模擬模式] 已連線到模擬裝置: {self.device_description}")
            return True, None

        try:
            # 初始化 WaveformAiCtrl（高速 AI 串流）
            self._wfm_ctrl = WaveformAiCtrl(self.device_description)
            if self._wfm_ctrl is None:
                raise RuntimeError("無法建立 WaveformAiCtrl")

            # 初始化 DI 控制器（即時 DI）
            self._di_ctrl = InstantDiCtrl(self.device_description)
            if self._di_ctrl is None:
                raise RuntimeError("無法建立 DI 控制器")

            self._connected = True
            print(f"[DAQ] 已成功連線到裝置: {self.device_description}")
            return True, None

        except Exception as e:
            print(f"[警告] 裝置連線失敗: {e}")
            self._connected = False
            return False, str(e)

    def disconnect(self):
        """釋放 DAQ 裝置資源"""
        if self._simulation_mode:
            self._connected = False
            print("[模擬模式] 已中斷連線")
            return

        try:
            if self._wfm_ctrl:
                try:
                    self._wfm_ctrl.stop()
                except Exception:
                    pass
                self._wfm_ctrl.dispose()
                self._wfm_ctrl = None
            if self._di_ctrl:
                self._di_ctrl.Dispose()
                self._di_ctrl = None
            self._connected = False
            print("[DAQ] 已釋放裝置資源")
        except Exception as e:
            print(f"[警告] 釋放資源時發生錯誤: {e}")

    def get_wfm_ai_ctrl(self):
        """取得 WaveformAiCtrl 實例（供 AIReader 使用）"""
        return self._wfm_ctrl

    def get_di_ctrl(self):
        """取得 DI 控制器實例"""
        return self._di_ctrl

    # ─── DI 讀取方法（供 DIReader 使用）────────────────────────────────────────

    def read_di_port(self, port: int = 0) -> int:
        """
        讀取 DI Port 的數位狀態（8-bit）
        使用 InstantDiCtrl.readAny(portStart, portCount)
        Args:
            port: DI Port 編號（USB-4716 只有 Port 0）
        Returns:
            int: 8-bit 數位值，bit0=DI0, bit1=DI1, ...
        """
        if self._simulation_mode:
            return self._simulate_di()

        if not self._connected or self._di_ctrl is None:
            raise RuntimeError("裝置未連線")

        ret, data = self._di_ctrl.readAny(port, 1)
        if DAQNAVI_AVAILABLE:
            if BioFailed(ret):
                raise RuntimeError(f"DI 讀取失敗，Port {port}，錯誤碼: 0x{ret.value:X}")
        return data[0] if data else 0

    def read_di_bit(self, port: int, bit: int) -> bool:
        """
        讀取單一 DI 通道狀態
        使用 InstantDiCtrl.readBit(port, bit)
        Args:
            port: DI Port 編號（USB-4716 為 0）
            bit: DI bit 編號 (0~7)
        Returns:
            bool: True=High, False=Low
        """
        if self._simulation_mode:
            port_data = self._simulate_di()
            return bool((port_data >> bit) & 0x01)

        if not self._connected or self._di_ctrl is None:
            raise RuntimeError("裝置未連線")

        ret, data = self._di_ctrl.readBit(port, bit)
        if DAQNAVI_AVAILABLE:
            if BioFailed(ret):
                raise RuntimeError(f"DI bit 讀取失敗，Port {port} Bit {bit}，錯誤碼: 0x{ret.value:X}")
        return bool(data)

    def read_di_channels(self, channels: list) -> dict:
        """
        批次讀取多個 DI 通道狀態（透過讀取整個 Port 再解析）
        Args:
            channels: DI 通道編號列表 (0~7)
        Returns:
            dict: {channel: bool} 各通道狀態
        """
        port_data = self.read_di_port(0)
        return {ch: bool((port_data >> ch) & 0x01) for ch in channels}

    # ─── 模擬模式輔助方法 ───────────────────────────────────────────────────────

    def _simulate_di(self) -> int:
        """模擬 DI 數位讀取（用於無硬體時測試）"""
        import math
        import time
        t = time.time()
        result = 0
        # Hall U/V/W (bit0~2): 模擬三相 Hall 訊號
        for i in range(3):
            if math.sin(2 * math.pi * 2 * t + i * 2.094) > 0:
                result |= (1 << i)
        # Encoder A (bit3): 模擬正交訊號
        if math.sin(2 * math.pi * 10 * t) > 0:
            result |= (1 << 3)
        # Encoder B (bit4): 相差 90 度
        if math.sin(2 * math.pi * 10 * t - math.pi / 2) > 0:
            result |= (1 << 4)
        return result

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
