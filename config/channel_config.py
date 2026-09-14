"""
硬體通道對應設定模組（可由使用者自行調整）

功能：
  - 從 config/channel_map.json 載入使用者自訂的硬體通道對應
  - 提供 Hall U/V/W、Encoder A/B 對應到 AI / DI 通道的查詢介面
  - 提供 AI 量程（ValueRange）與診斷 Y 軸範圍設定
  - 支援執行期修改並存回 JSON（供 UI 通道設定對話框使用）

設計理念：
  舊版將通道硬編碼為 AI0~4 / DI0~4，散佈於 thresholds、ai_reader、di_reader、
  diagnostic_scanner 等多處。本模組將所有通道對應集中管理，讓使用者可透過
  UI 對話框或直接編輯 JSON 靈活調整硬體端接線，不需修改程式碼。

JSON 結構：
  {
    "hall":    {"U": {"ai": 0, "di": 0}, "V": {...}, "W": {...}},
    "encoder": {"A": {"ai": 3, "di": 3}, "B": {...}},
    "value_range": {"hall": "V_0To5", "encoder": "V_0To10"},
    "y_range":     {"hall": [-0.2, 3.8], "encoder": [-0.5, 6.0]},
    "di_port": 0
  }
"""

import json
import copy
import sys
from pathlib import Path


# ─── 預設通道對應（JSON 不存在或損毀時的 fallback）─────────────────────────────
DEFAULT_CHANNEL_MAP = {
    "hall": {
        "U": {"ai": 0, "di": 0},
        "V": {"ai": 1, "di": 1},
        "W": {"ai": 2, "di": 2},
    },
    "encoder": {
        "A": {"ai": 3, "di": 3},
        "B": {"ai": 4, "di": 4},
    },
    "value_range": {
        "hall": "V_0To5",
        "encoder": "V_0To10",
    },
    "y_range": {
        "hall": [-0.2, 3.8],
        "encoder": [-0.5, 6.0],
    },
    "di_port": 0,
}


def _get_config_path() -> Path:
    """
    取得 channel_map.json 的路徑（支援打包執行檔模式）

    Returns:
        Path: JSON 設定檔完整路徑
    """
    if getattr(sys, "frozen", False):
        # PyInstaller 打包模式：設定檔放在執行檔同層
        base = Path(sys.executable).parent
        return base / "channel_map.json"
    # 開發模式：與本檔案同目錄
    return Path(__file__).parent / "channel_map.json"


class ChannelConfig:
    """
    硬體通道對應設定管理器（單例）

    使用方式：
        from config.channel_config import CHANNEL_CONFIG
        ai_ch = CHANNEL_CONFIG.hall_ai("U")   # → 0
        di_ch = CHANNEL_CONFIG.encoder_di("A") # → 3
        CHANNEL_CONFIG.set_map(new_map)        # 更新並存檔
    """

    def __init__(self):
        self._path = _get_config_path()
        self._map = copy.deepcopy(DEFAULT_CHANNEL_MAP)
        self.load()

    # ─── 載入 / 儲存 ────────────────────────────────────────────────────────────

    def load(self) -> bool:
        """
        從 JSON 載入通道對應。檔案不存在或格式錯誤時使用預設值。

        Returns:
            bool: True = 成功從 JSON 載入，False = 使用預設值
        """
        try:
            if self._path.exists():
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._map = self._merge_defaults(data)
                print(f"[ChannelConfig] 已載入通道對應: {self._path}")
                return True
            else:
                print(f"[ChannelConfig] 找不到 {self._path}，使用預設通道對應")
                # 首次執行自動產生預設檔案，方便使用者編輯
                self.save()
                return False
        except Exception as e:
            print(f"[ChannelConfig] 載入失敗（使用預設值）: {e}")
            self._map = copy.deepcopy(DEFAULT_CHANNEL_MAP)
            return False

    def save(self) -> bool:
        """
        將目前通道對應存回 JSON。

        Returns:
            bool: True = 儲存成功
        """
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._map, f, ensure_ascii=False, indent=2)
            print(f"[ChannelConfig] 通道對應已儲存: {self._path}")
            return True
        except Exception as e:
            print(f"[ChannelConfig] 儲存失敗: {e}")
            return False

    def _merge_defaults(self, data: dict) -> dict:
        """
        將載入的資料與預設值合併，確保缺漏欄位有預設值。

        Args:
            data: 從 JSON 載入的字典

        Returns:
            dict: 合併後的完整通道對應
        """
        merged = copy.deepcopy(DEFAULT_CHANNEL_MAP)
        if not isinstance(data, dict):
            return merged

        for group in ("hall", "encoder"):
            if group in data and isinstance(data[group], dict):
                for sig, chs in data[group].items():
                    if sig in merged[group] and isinstance(chs, dict):
                        merged[group][sig].update({
                            k: int(v) for k, v in chs.items()
                            if k in ("ai", "di")
                        })

        if "value_range" in data and isinstance(data["value_range"], dict):
            merged["value_range"].update(data["value_range"])
        if "y_range" in data and isinstance(data["y_range"], dict):
            for k, v in data["y_range"].items():
                if isinstance(v, (list, tuple)) and len(v) == 2:
                    merged["y_range"][k] = [float(v[0]), float(v[1])]
        if "di_port" in data:
            try:
                merged["di_port"] = int(data["di_port"])
            except (ValueError, TypeError):
                pass

        return merged

    # ─── 通道查詢 ──────────────────────────────────────────────────────────────

    def hall_ai(self, sig: str) -> int:
        """取得 Hall 訊號（U/V/W）對應的 AI 通道"""
        return self._map["hall"][sig]["ai"]

    def hall_di(self, sig: str) -> int:
        """取得 Hall 訊號（U/V/W）對應的 DI 通道"""
        return self._map["hall"][sig]["di"]

    def encoder_ai(self, sig: str) -> int:
        """取得 Encoder 訊號（A/B）對應的 AI 通道"""
        return self._map["encoder"][sig]["ai"]

    def encoder_di(self, sig: str) -> int:
        """取得 Encoder 訊號（A/B）對應的 DI 通道"""
        return self._map["encoder"][sig]["di"]

    def hall_ai_channels(self) -> dict:
        """回傳 {U: ai, V: ai, W: ai}"""
        return {s: self._map["hall"][s]["ai"] for s in ("U", "V", "W")}

    def hall_di_channels(self) -> dict:
        """回傳 {U: di, V: di, W: di}"""
        return {s: self._map["hall"][s]["di"] for s in ("U", "V", "W")}

    def encoder_ai_channels(self) -> dict:
        """回傳 {A: ai, B: ai}"""
        return {s: self._map["encoder"][s]["ai"] for s in ("A", "B")}

    def encoder_di_channels(self) -> dict:
        """回傳 {A: di, B: di}"""
        return {s: self._map["encoder"][s]["di"] for s in ("A", "B")}

    def all_ai_channels(self) -> list:
        """回傳所有 AI 通道編號（Hall U/V/W + Encoder A/B），依訊號順序排列"""
        return [
            self.hall_ai("U"), self.hall_ai("V"), self.hall_ai("W"),
            self.encoder_ai("A"), self.encoder_ai("B"),
        ]

    def all_di_channels(self) -> list:
        """回傳所有 DI 通道編號（Hall U/V/W + Encoder A/B），依訊號順序排列"""
        return [
            self.hall_di("U"), self.hall_di("V"), self.hall_di("W"),
            self.encoder_di("A"), self.encoder_di("B"),
        ]

    def di_port(self) -> int:
        """取得 DI 讀取的 Port 編號"""
        return self._map.get("di_port", 0)

    # ─── 診斷通道清單 ──────────────────────────────────────────────────────────

    def diagnostic_channels(self) -> list:
        """
        建立診斷用通道清單（供 DiagnosticScanner / DIAGNOSTIC["channels"] 使用）

        每個項目：
          {
            "ch":        int,     AI 通道編號
            "name":      str,     訊號名稱（如 "Hall U"）
            "kind":      str,     "hall" 或 "encoder"（決定量程與判斷閾值）
            "vh_min":    None,    由 thresholds 動態填入
            "vl_max":    None,
            "y_range":   tuple,   繪圖 Y 軸範圍
          }

        Returns:
            list[dict]: 依 Hall U/V/W → Encoder A/B 順序排列
        """
        hall_y = tuple(self._map["y_range"]["hall"])
        enc_y  = tuple(self._map["y_range"]["encoder"])
        chans = []
        for sig in ("U", "V", "W"):
            chans.append({
                "ch": self.hall_ai(sig), "name": f"Hall {sig}",
                "kind": "hall", "vh_min": None, "vl_max": None,
                "y_range": hall_y,
            })
        for sig in ("A", "B"):
            chans.append({
                "ch": self.encoder_ai(sig), "name": f"Encoder {sig}",
                "kind": "encoder", "vh_min": None, "vl_max": None,
                "y_range": enc_y,
            })
        return chans

    def channel_names(self) -> dict:
        """
        回傳 {ai_channel: 顯示名稱} 對照（供 AIReader.CHANNEL_NAMES 使用）
        """
        names = {}
        for sig in ("U", "V", "W"):
            names[self.hall_ai(sig)] = f"Hall {sig}"
        for sig in ("A", "B"):
            names[self.encoder_ai(sig)] = f"Encoder {sig}"
        return names

    # ─── 量程 ──────────────────────────────────────────────────────────────────

    def value_range_name(self, kind: str) -> str:
        """
        取得指定類型（hall/encoder）的 ValueRange 名稱字串

        Args:
            kind: "hall" 或 "encoder"

        Returns:
            str: ValueRange 枚舉名稱（如 "V_0To5"）
        """
        return self._map["value_range"].get(kind, "V_0To5")

    def value_range(self, kind: str):
        """
        取得指定類型的 ValueRange 枚舉值（供 DAQNavi SDK 使用）

        Args:
            kind: "hall" 或 "encoder"

        Returns:
            ValueRange 枚舉值；SDK 不可用時回傳名稱字串
        """
        name = self.value_range_name(kind)
        try:
            from Automation.BDaq import ValueRange
            return getattr(ValueRange, name)
        except Exception:
            return name

    def y_range(self, kind: str) -> tuple:
        """取得指定類型的繪圖 Y 軸範圍"""
        return tuple(self._map["y_range"].get(kind, [-0.5, 6.0]))

    # ─── 執行期更新 ────────────────────────────────────────────────────────────

    def get_map(self) -> dict:
        """取得目前通道對應的深拷貝（供 UI 編輯用，不影響內部狀態）"""
        return copy.deepcopy(self._map)

    def set_map(self, new_map: dict, save: bool = True) -> bool:
        """
        更新通道對應（供 UI 對話框套用）

        Args:
            new_map: 新的通道對應字典（可為部分欄位，會與現有值合併）
            save:    是否同時存回 JSON

        Returns:
            bool: True = 更新成功
        """
        self._map = self._merge_defaults(new_map)
        if save:
            return self.save()
        return True


# ─── 單例 ──────────────────────────────────────────────────────────────────────
CHANNEL_CONFIG = ChannelConfig()
