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
  取樣率：200,000 Hz/通道（單通道診斷模式），每 0.1s 觸發一次 DataReady
  enter_diag_mode 會自動查詢 AiFeatures.convertClockRange 並 clamp 至硬體上限
"""

import sys
import os

# 嘗試匯入 DAQNavi SDK（Automation package）
try:
    from Automation.BDaq.InstantDiCtrl import InstantDiCtrl
    from Automation.BDaq.InstantAiCtrl import InstantAiCtrl
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
        self._wfm_ctrl      = None   # WaveformAiCtrl（高速 AI 串流，診斷用）
        self._instant_ai    = None   # InstantAiCtrl（即時 AI 輪詢，監控用）
        self._di_ctrl       = None   # InstantDiCtrl（即時 DI）
        self._connected     = False
        self._simulation_mode = not DAQNAVI_AVAILABLE
        self._diag_mode     = False  # 診斷模式中（InstantAI 已釋放）

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
            # 初始化 InstantAiCtrl（即時 AI 輪詢，穩定可靠）
            self._instant_ai = InstantAiCtrl(self.device_description)
            if self._instant_ai is None:
                raise RuntimeError("無法建立 InstantAiCtrl")

            # 初始化 DI 控制器（即時 DI）
            self._di_ctrl = InstantDiCtrl(self.device_description)
            if self._di_ctrl is None:
                raise RuntimeError("無法建立 DI 控制器")

            self._connected = True
            self._diag_mode = False
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
            self._diag_mode = False
            print("[模擬模式] 已中斷連線")
            return

        try:
            if self._instant_ai:
                try:
                    self._instant_ai.dispose()
                except Exception:
                    pass
                self._instant_ai = None
            if self._wfm_ctrl:
                try:
                    self._wfm_ctrl.stop()
                except Exception:
                    pass
                try:
                    self._wfm_ctrl.dispose()
                except Exception:
                    pass
                self._wfm_ctrl = None
            if self._di_ctrl:
                try:
                    self._di_ctrl.Dispose()
                except Exception:
                    pass
                self._di_ctrl = None
            self._connected = False
            self._diag_mode = False
            print("[DAQ] 已釋放裝置資源")
        except Exception as e:
            print(f"[警告] 釋放資源時發生錯誤: {e}")

    def get_instant_ai_ctrl(self):
        """取得 InstantAiCtrl 實例（供 AIReader 使用）"""
        return self._instant_ai

    def get_wfm_ai_ctrl(self):
        """取得 WaveformAiCtrl 實例（診斷用）"""
        return self._wfm_ctrl

    @property
    def is_diag_mode(self) -> bool:
        """是否正在診斷模式（InstantAI 已釋放）"""
        return self._diag_mode

    def enter_diag_mode(self) -> bool:
        """
        進入診斷模式：釋放 InstantAiCtrl，建立 WaveformAiCtrl
        診斷期間 InstantAI 輪詢必須先停止，才能呼叫此方法

        自動查詢 AiFeatures.convertClockRange 取得硬體支援的取樣率上限，
        並將設定值 clamp 在此範圍內，避免超規導致 prepare() 失敗。

        Returns:
            bool: 成功進入診斷模式
        """
        if self._simulation_mode:
            self._diag_mode = True
            print("[模擬模式] 進入診斷模式")
            return True

        if not self._connected:
            print("[DAQ] 裝置未連線，無法進入診斷模式")
            return False

        try:
            # 釋放 InstantAiCtrl（讓 WaveformAiCtrl 可獨占 AI 硬體）
            if self._instant_ai:
                try:
                    self._instant_ai.dispose()
                except Exception:
                    pass
                self._instant_ai = None
                print("[DAQ] InstantAiCtrl 已釋放（診斷模式）")

            # 建立 WaveformAiCtrl
            self._wfm_ctrl = WaveformAiCtrl(self.device_description)
            if self._wfm_ctrl is None:
                raise RuntimeError("無法建立 WaveformAiCtrl")

            # ── 查詢硬體取樣率上限並記錄 ────────────────────────────────────
            self._hw_max_clock_rate = self._query_hw_max_clock_rate()

            self._diag_mode = True
            print(
                f"[DAQ] WaveformAiCtrl 已建立，進入診斷模式 | "
                f"硬體取樣率上限: {self._hw_max_clock_rate:,.0f} Hz"
            )
            return True

        except Exception as e:
            print(f"[DAQ] 進入診斷模式失敗: {e}")
            self._diag_mode = False
            return False

    def _query_hw_max_clock_rate(self) -> float:
        """
        查詢 WaveformAiCtrl 硬體支援的最高取樣率（convertClockRange.max）

        Returns:
            float: 硬體最高取樣率 (Hz)；查詢失敗時回傳設定檔預設值
        """
        from config.thresholds import HW_MAX_SAMPLE_RATE
        fallback = float(HW_MAX_SAMPLE_RATE)

        if self._wfm_ctrl is None:
            return fallback

        try:
            features = self._wfm_ctrl.features
            clock_range = features.convertClockRange  # MathInterval
            hw_max = float(clock_range.max)
            hw_min = float(clock_range.min)
            print(
                f"[DAQ] 硬體取樣率範圍: {hw_min:,.0f} ~ {hw_max:,.0f} Hz"
            )
            return hw_max if hw_max > 0 else fallback
        except Exception as e:
            print(f"[DAQ] 查詢 convertClockRange 失敗（使用預設值 {fallback:,.0f} Hz）: {e}")
            return fallback

    def clamp_clock_rate(self, requested_rate: float) -> float:
        """
        將請求的取樣率 clamp 至硬體支援範圍內

        Args:
            requested_rate: 請求的取樣率 (Hz)

        Returns:
            float: clamp 後的取樣率 (Hz)
        """
        hw_max = getattr(self, "_hw_max_clock_rate", None)
        if hw_max is None:
            # 尚未查詢過（非診斷模式），直接回傳
            return requested_rate

        clamped = min(requested_rate, hw_max)
        if clamped != requested_rate:
            print(
                f"[DAQ] 取樣率 clamp: {requested_rate:,.0f} → {clamped:,.0f} Hz"
                f"（硬體上限 {hw_max:,.0f} Hz）"
            )
        return clamped

    def exit_diag_mode(self) -> bool:
        """
        離開診斷模式：釋放 WaveformAiCtrl，重建 InstantAiCtrl
        診斷完成後呼叫，恢復正常監控模式

        Returns:
            bool: 成功離開診斷模式
        """
        if self._simulation_mode:
            self._diag_mode = False
            print("[模擬模式] 離開診斷模式")
            return True

        if not self._connected:
            self._diag_mode = False
            return False

        try:
            # 釋放 WaveformAiCtrl
            if self._wfm_ctrl:
                try:
                    self._wfm_ctrl.stop()
                except Exception:
                    pass
                try:
                    self._wfm_ctrl.dispose()
                except Exception:
                    pass
                self._wfm_ctrl = None
                print("[DAQ] WaveformAiCtrl 已釋放")

            # 重建 InstantAiCtrl
            self._instant_ai = InstantAiCtrl(self.device_description)
            if self._instant_ai is None:
                raise RuntimeError("無法重建 InstantAiCtrl")

            self._diag_mode = False
            print("[DAQ] InstantAiCtrl 已重建，離開診斷模式")
            return True

        except Exception as e:
            print(f"[DAQ] 離開診斷模式失敗: {e}")
            self._diag_mode = False
            return False

    def read_ai_channels(self, channel_start: int, channel_count: int) -> list:
        """
        即時讀取多個 AI 通道電壓值
        Args:
            channel_start: 起始通道編號
            channel_count: 通道數量
        Returns:
            list: 各通道電壓值 [V]，讀取失敗時返回全 0
        """
        if self._simulation_mode or self._instant_ai is None:
            return [0.0] * channel_count

        try:
            ret, data = self._instant_ai.readAny(channel_start, channel_count)
            if DAQNAVI_AVAILABLE and BioFailed(ret):
                return [0.0] * channel_count
            return list(data) if data else [0.0] * channel_count
        except Exception:
            return [0.0] * channel_count

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
        """
        模擬 DI 數位讀取（用於無硬體時測試）

        依 CHANNEL_CONFIG 目前的 DI 通道對應設定各 bit，支援使用者自訂通道。
        """
        import math
        import time
        from config.channel_config import CHANNEL_CONFIG

        t = time.time()
        result = 0
        # Hall U/V/W：模擬三相 Hall 訊號，三相相差 120 度
        for i, sig in enumerate(("U", "V", "W")):
            if math.sin(2 * math.pi * 2 * t + i * 2.094) > 0:
                result |= (1 << CHANNEL_CONFIG.hall_di(sig))
        # Encoder A：模擬正交訊號
        if math.sin(2 * math.pi * 10 * t) > 0:
            result |= (1 << CHANNEL_CONFIG.encoder_di("A"))
        # Encoder B：與 A 相差 90 度
        if math.sin(2 * math.pi * 10 * t - math.pi / 2) > 0:
            result |= (1 << CHANNEL_CONFIG.encoder_di("B"))
        return result

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
