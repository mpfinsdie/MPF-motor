"""
馬達量測參數 Profile 管理模組（可由使用者自行儲存多組具名設定）

功能：
  - 從 config/motor_profiles.json 載入多組具名的馬達量測參數 profile
  - 提供 list / get / save / delete profile 的介面
  - 記憶上次使用的 active profile，程式啟動時自動帶入
  - 缺漏欄位自動以預設值補齊
  - 支援打包執行檔（PyInstaller frozen）模式的設定檔路徑

設計理念：
  沿用 config/channel_config.py 的單例 + JSON 持久化模式，將量測參數
  （Hall 週期/轉、Encoder 解析度/PPR、Hall/Encoder 電壓閾值、比值容差）
  儲存成具名 profile，讓使用者可為不同馬達型號建立各自的設定，
  下次開啟自動套用上次使用的 profile，不需每次重設。

JSON 結構：
  {
    "active_profile": "預設",
    "profiles": {
      "預設": {
        "hall_pulses_per_rev": 90,
        "hall_vh_min": 2.0,
        "hall_vl_max": 0.8,
        "resolution_bits": 11,
        "ppr": 512,
        "enc_vh_min": 3.5,
        "enc_vl_max": 1.5,
        "ratio_tolerance": 0.15
      },
      "馬達型號A": { ... }
    }
  }
"""

import json
import copy
import sys
from pathlib import Path


# ─── 單一 profile 的預設欄位（缺漏時的 fallback）─────────────────────────────────
DEFAULT_PROFILE = {
    "hall_pulses_per_rev": 90,     # Hall 每相每轉週期數
    "hall_vh_min":         2.0,    # Hall 高電位最低閾值 (V)
    "hall_vl_max":         0.8,    # Hall 低電位最高閾值 (V)
    "resolution_bits":     11,     # Encoder 解析度位元數
    "ppr":                 512,    # Encoder 每相每轉脈波數
    "enc_vh_min":          3.5,    # Encoder 高電位最低閾值 (V)
    "enc_vl_max":          1.5,    # Encoder 低電位最高閾值 (V)
    "ratio_tolerance":     0.15,   # Hall/Encoder 比值交叉驗證容差（比例）
}

# 預設 profile 名稱
DEFAULT_PROFILE_NAME = "預設"

# ─── 整份設定檔的預設結構 ──────────────────────────────────────────────────────
DEFAULT_STORE = {
    "active_profile": DEFAULT_PROFILE_NAME,
    "profiles": {
        DEFAULT_PROFILE_NAME: copy.deepcopy(DEFAULT_PROFILE),
    },
}


def _get_config_path() -> Path:
    """
    取得 motor_profiles.json 的路徑（支援打包執行檔模式）

    Returns:
        Path: JSON 設定檔完整路徑
    """
    if getattr(sys, "frozen", False):
        # PyInstaller 打包模式：設定檔放在執行檔同層
        base = Path(sys.executable).parent
        return base / "motor_profiles.json"
    # 開發模式：與本檔案同目錄
    return Path(__file__).parent / "motor_profiles.json"


class MotorProfileManager:
    """
    馬達量測參數 Profile 管理器（單例）

    使用方式：
        from config.motor_profiles import MOTOR_PROFILES
        names   = MOTOR_PROFILES.list_profiles()       # ["預設", "馬達型號A", ...]
        active  = MOTOR_PROFILES.get_active_name()      # "預設"
        params  = MOTOR_PROFILES.get_profile("預設")    # {...}
        MOTOR_PROFILES.save_profile("馬達型號A", params) # 新增/更新並存檔
        MOTOR_PROFILES.delete_profile("馬達型號A")       # 刪除並存檔
        MOTOR_PROFILES.set_active("馬達型號A")           # 設定 active 並存檔
    """

    def __init__(self):
        self._path = _get_config_path()
        self._store = copy.deepcopy(DEFAULT_STORE)
        self.load()

    # ─── 載入 / 儲存 ────────────────────────────────────────────────────────────

    def load(self) -> bool:
        """
        從 JSON 載入 profiles。檔案不存在或格式錯誤時使用預設值。

        Returns:
            bool: True = 成功從 JSON 載入，False = 使用預設值
        """
        try:
            if self._path.exists():
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._store = self._merge_defaults(data)
                print(f"[MotorProfiles] 已載入量測參數 profile: {self._path}")
                return True
            else:
                print(f"[MotorProfiles] 找不到 {self._path}，使用預設 profile")
                # 首次執行自動產生預設檔案，方便使用者編輯
                self.save()
                return False
        except Exception as e:
            print(f"[MotorProfiles] 載入失敗（使用預設值）: {e}")
            self._store = copy.deepcopy(DEFAULT_STORE)
            return False

    def save(self) -> bool:
        """
        將目前 profiles 存回 JSON。

        Returns:
            bool: True = 儲存成功
        """
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._store, f, ensure_ascii=False, indent=2)
            print(f"[MotorProfiles] 量測參數 profile 已儲存: {self._path}")
            return True
        except Exception as e:
            print(f"[MotorProfiles] 儲存失敗: {e}")
            return False

    def _merge_defaults(self, data: dict) -> dict:
        """
        將載入的資料與預設結構合併，確保欄位完整。

        Args:
            data: 從 JSON 載入的字典

        Returns:
            dict: 合併後的完整設定結構
        """
        merged = copy.deepcopy(DEFAULT_STORE)
        if not isinstance(data, dict):
            return merged

        # ── profiles ──────────────────────────────────────────────────────────
        profiles = data.get("profiles")
        if isinstance(profiles, dict) and profiles:
            merged_profiles = {}
            for name, params in profiles.items():
                merged_profiles[str(name)] = self._merge_profile(params)
            merged["profiles"] = merged_profiles
        # 若載入後沒有任何 profile，補回預設 profile
        if not merged["profiles"]:
            merged["profiles"] = {
                DEFAULT_PROFILE_NAME: copy.deepcopy(DEFAULT_PROFILE)
            }

        # ── active_profile ──────────────────────────────────────────────────────
        active = data.get("active_profile")
        if isinstance(active, str) and active in merged["profiles"]:
            merged["active_profile"] = active
        else:
            # active 不存在或不在 profiles 中 → 取第一個 profile
            merged["active_profile"] = next(iter(merged["profiles"]))

        return merged

    def _merge_profile(self, params: dict) -> dict:
        """
        將單一 profile 與 DEFAULT_PROFILE 合併，補齊缺漏欄位並轉型。

        Args:
            params: 單一 profile 的參數字典

        Returns:
            dict: 補齊後的 profile
        """
        merged = copy.deepcopy(DEFAULT_PROFILE)
        if not isinstance(params, dict):
            return merged

        int_keys   = ("hall_pulses_per_rev", "resolution_bits", "ppr")
        float_keys = ("hall_vh_min", "hall_vl_max",
                      "enc_vh_min", "enc_vl_max", "ratio_tolerance")

        for k in int_keys:
            if k in params:
                try:
                    merged[k] = int(params[k])
                except (ValueError, TypeError):
                    pass
        for k in float_keys:
            if k in params:
                try:
                    merged[k] = float(params[k])
                except (ValueError, TypeError):
                    pass

        return merged

    # ─── Profile 查詢 ──────────────────────────────────────────────────────────

    def list_profiles(self) -> list:
        """回傳所有 profile 名稱（依插入順序）"""
        return list(self._store["profiles"].keys())

    def has_profile(self, name: str) -> bool:
        """判斷指定名稱的 profile 是否存在"""
        return name in self._store["profiles"]

    def get_profile(self, name: str) -> dict:
        """
        取得指定 profile 的參數（深拷貝，補齊缺漏欄位）。
        名稱不存在時回傳 DEFAULT_PROFILE 的深拷貝。
        """
        if name in self._store["profiles"]:
            return copy.deepcopy(self._store["profiles"][name])
        return copy.deepcopy(DEFAULT_PROFILE)

    def get_active_name(self) -> str:
        """取得目前 active profile 名稱"""
        return self._store.get("active_profile", DEFAULT_PROFILE_NAME)

    def get_active_profile(self) -> dict:
        """取得目前 active profile 的參數（深拷貝）"""
        return self.get_profile(self.get_active_name())

    # ─── Profile 修改 ──────────────────────────────────────────────────────────

    def save_profile(self, name: str, params: dict,
                     set_active: bool = True, save: bool = True) -> bool:
        """
        新增或更新指定名稱的 profile。

        Args:
            name:       profile 名稱（非空字串）
            params:     參數字典（會與 DEFAULT_PROFILE 合併補齊）
            set_active: 是否同時設為 active profile
            save:       是否同時存回 JSON

        Returns:
            bool: True = 成功
        """
        name = (name or "").strip()
        if not name:
            print("[MotorProfiles] save_profile 失敗：名稱不可為空")
            return False

        self._store["profiles"][name] = self._merge_profile(params)
        if set_active:
            self._store["active_profile"] = name
        if save:
            return self.save()
        return True

    def delete_profile(self, name: str, save: bool = True) -> bool:
        """
        刪除指定 profile。至少保留一組 profile（不可刪光）。
        若刪除的是 active profile，active 會自動切換到剩餘的第一組。

        Args:
            name: 要刪除的 profile 名稱
            save: 是否同時存回 JSON

        Returns:
            bool: True = 成功刪除
        """
        if name not in self._store["profiles"]:
            return False
        if len(self._store["profiles"]) <= 1:
            print("[MotorProfiles] delete_profile 失敗：至少需保留一組 profile")
            return False

        del self._store["profiles"][name]

        # 若刪除的是 active，切換到剩餘的第一組
        if self._store.get("active_profile") == name:
            self._store["active_profile"] = next(iter(self._store["profiles"]))

        if save:
            return self.save()
        return True

    def set_active(self, name: str, save: bool = True) -> bool:
        """
        設定 active profile。

        Args:
            name: profile 名稱（需已存在）
            save: 是否同時存回 JSON

        Returns:
            bool: True = 成功
        """
        if name not in self._store["profiles"]:
            return False
        self._store["active_profile"] = name
        if save:
            return self.save()
        return True


# ─── 單例 ──────────────────────────────────────────────────────────────────────
MOTOR_PROFILES = MotorProfileManager()
