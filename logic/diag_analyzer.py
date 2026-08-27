"""
高速波形診斷分析器模組

功能：
  - 對 DiagnosticScanner 採集的高速波形（200kHz）做 PASS/FAIL 判斷
  - 每通道分析項目：
      1. H/L 準位比例（佔全部樣本的比例，判斷訊號是否正常切換）
      2. 不定態（X 準位）比例（介於 VL_max 與 VH_min 之間，判斷訊號品質）
      3. 邊緣偵測與計數（上升沿 + 下降沿，判斷訊號是否有在切換）
      4. 主頻率估算（過零率法，判斷訊號頻率是否在合理範圍）
  - 整體結果彙整：所有通道（所有輪次）都 PASS 才算整體 PASS

架構：
  DiagnosticScanner 採集完成後，由 MainWindow._on_diag_done 呼叫：
    analyzer = DiagAnalyzer()
    result = analyzer.analyze_all(raw_results, channels, sample_rate)
    # result.overall_pass → True/False
    # result.channel_results → List[DiagChannelResult]

輸入資料格式（來自 DiagnosticScanner._results）：
  raw_results[round_idx][ch_idx] = np.ndarray (float32) 或 None
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from config.thresholds import DIAGNOSTIC, HALL_THRESHOLDS, ENCODER_THRESHOLDS


# ─── 結果資料類別 ─────────────────────────────────────────────────────────────

@dataclass
class DiagChannelResult:
    """
    單一通道（單輪）的診斷分析結果

    Attributes:
        ch_idx:          通道索引（0~4）
        ch_name:         通道名稱（如 "Hall U"）
        round_idx:       輪次索引（0-based）
        sample_count:    有效樣本數
        vh_min:          H 準位閾值 (V)
        vl_max:          L 準位閾值 (V)
        h_ratio:         H 準位樣本比例（0.0~1.0）
        l_ratio:         L 準位樣本比例（0.0~1.0）
        x_ratio:         不定態樣本比例（0.0~1.0）
        edge_count:      邊緣總數（上升沿 + 下降沿）
        freq_hz:         估算主頻率 (Hz)，0 表示無法估算
        pass_hl_ratio:   H/L 比例是否 PASS
        pass_x_ratio:    不定態比例是否 PASS
        pass_edges:      邊緣數量是否 PASS
        pass_freq:       頻率範圍是否 PASS（不限制時恆為 True）
        overall_pass:    此通道此輪是否整體 PASS
        fail_reasons:    FAIL 原因列表（空列表表示 PASS）
    """
    ch_idx:       int
    ch_name:      str
    round_idx:    int
    sample_count: int       = 0
    vh_min:       float     = 0.0
    vl_max:       float     = 0.0
    h_ratio:      float     = 0.0
    l_ratio:      float     = 0.0
    x_ratio:      float     = 0.0
    edge_count:   int       = 0
    freq_hz:      float     = 0.0
    pass_hl_ratio: bool     = False
    pass_x_ratio:  bool     = False
    pass_edges:    bool     = False
    pass_freq:     bool     = True
    overall_pass:  bool     = False
    fail_reasons:  List[str] = field(default_factory=list)


@dataclass
class DiagOverallResult:
    """
    整體診斷分析結果（所有通道 × 所有輪次）

    Attributes:
        channel_results:  各通道各輪次的分析結果列表
        ch_summary:       各通道彙整（跨輪次）：{ch_name: {"pass": bool, "rounds": [DiagChannelResult]}}
        overall_pass:     整體 PASS/FAIL（所有通道所有輪次都 PASS 才算 PASS）
        pass_count:       PASS 的（通道 × 輪次）數量
        total_count:      總（通道 × 輪次）數量
        summary_text:     人類可讀的摘要文字（供對話框顯示）
    """
    channel_results: List[DiagChannelResult] = field(default_factory=list)
    ch_summary:      Dict[str, Any]          = field(default_factory=dict)
    overall_pass:    bool                    = False
    pass_count:      int                     = 0
    total_count:     int                     = 0
    summary_text:    str                     = ""


# ─── 診斷分析器 ───────────────────────────────────────────────────────────────

class DiagAnalyzer:
    """
    高速波形診斷分析器

    使用方式：
        analyzer = DiagAnalyzer()
        result = analyzer.analyze_all(
            raw_results=scanner._results,   # List[List[Optional[np.ndarray]]]
            channels=scanner.channels,       # List[Dict]（含 ch, name, vh_min, vl_max）
            sample_rate=200_000
        )
        print(result.overall_pass)
        print(result.summary_text)
    """

    def __init__(self):
        self._cfg = DIAGNOSTIC.get("analysis", {})

    # ─── 公開介面 ──────────────────────────────────────────────────────────────

    def analyze_all(
        self,
        raw_results: List[List[Optional[np.ndarray]]],
        channels: List[Dict[str, Any]],
        sample_rate: int = 200_000
    ) -> DiagOverallResult:
        """
        分析所有通道 × 所有輪次的高速波形

        Args:
            raw_results:  raw_results[round_idx][ch_idx] = np.ndarray 或 None
            channels:     通道定義列表（含 ch, name, vh_min, vl_max）
            sample_rate:  取樣率 (Hz)

        Returns:
            DiagOverallResult: 整體分析結果
        """
        result = DiagOverallResult()
        rounds = len(raw_results)
        ch_count = len(channels)

        # 逐輪逐通道分析
        for round_idx in range(rounds):
            for ch_idx, ch_def in enumerate(channels):
                data = None
                if round_idx < len(raw_results) and ch_idx < len(raw_results[round_idx]):
                    data = raw_results[round_idx][ch_idx]

                ch_result = self.analyze_channel(
                    data=data,
                    ch_idx=ch_idx,
                    ch_name=ch_def.get("name", f"CH{ch_idx}"),
                    round_idx=round_idx,
                    vh_min=ch_def.get("vh_min") or self._get_vh_min(ch_idx),
                    vl_max=ch_def.get("vl_max") or self._get_vl_max(ch_idx),
                    sample_rate=sample_rate,
                    is_encoder=(ch_idx >= 3)
                )
                result.channel_results.append(ch_result)

        # 統計 PASS/FAIL
        result.total_count = len(result.channel_results)
        result.pass_count  = sum(1 for r in result.channel_results if r.overall_pass)
        result.overall_pass = (result.pass_count == result.total_count and result.total_count > 0)

        # 各通道彙整（跨輪次）
        result.ch_summary = self._build_ch_summary(result.channel_results, channels)

        # 產生摘要文字
        result.summary_text = self._build_summary_text(result, channels, rounds)

        return result

    def analyze_channel(
        self,
        data: Optional[np.ndarray],
        ch_idx: int,
        ch_name: str,
        round_idx: int,
        vh_min: float,
        vl_max: float,
        sample_rate: int,
        is_encoder: bool = False
    ) -> DiagChannelResult:
        """
        分析單一通道單輪的高速波形

        Args:
            data:        波形資料（float32 ndarray），None 表示無資料
            ch_idx:      通道索引
            ch_name:     通道名稱
            round_idx:   輪次索引
            vh_min:      H 準位閾值 (V)
            vl_max:      L 準位閾值 (V)
            sample_rate: 取樣率 (Hz)
            is_encoder:  是否為 Encoder 通道（影響邊緣數量門檻）

        Returns:
            DiagChannelResult
        """
        cr = DiagChannelResult(
            ch_idx=ch_idx,
            ch_name=ch_name,
            round_idx=round_idx,
            vh_min=vh_min,
            vl_max=vl_max,
        )

        # 無資料或樣本不足
        min_samples = self._cfg.get("min_samples", 1000)
        if data is None or len(data) < min_samples:
            cr.fail_reasons.append(
                f"資料不足（{len(data) if data is not None else 0} 點 < {min_samples} 點）"
            )
            cr.overall_pass = False
            return cr

        cr.sample_count = len(data)

        # ── 1. H/L/X 準位分類 ────────────────────────────────────────────────
        h_mask = data >= vh_min
        l_mask = data <= vl_max
        x_mask = ~h_mask & ~l_mask

        h_count = int(np.sum(h_mask))
        l_count = int(np.sum(l_mask))
        x_count = int(np.sum(x_mask))
        total   = cr.sample_count

        cr.h_ratio = h_count / total
        cr.l_ratio = l_count / total
        cr.x_ratio = x_count / total

        # ── 2. H/L 比例判斷 ──────────────────────────────────────────────────
        hl_ratio_min = self._cfg.get("hl_ratio_min", 0.05)
        hl_ratio_max = self._cfg.get("hl_ratio_max", 0.95)

        # H 比例在合理範圍內（訊號有在切換，不是全 H 或全 L）
        cr.pass_hl_ratio = (hl_ratio_min <= cr.h_ratio <= hl_ratio_max)
        if not cr.pass_hl_ratio:
            if cr.h_ratio < hl_ratio_min:
                cr.fail_reasons.append(
                    f"H 準位比例過低（{cr.h_ratio*100:.1f}% < {hl_ratio_min*100:.0f}%）"
                )
            else:
                cr.fail_reasons.append(
                    f"H 準位比例過高（{cr.h_ratio*100:.1f}% > {hl_ratio_max*100:.0f}%）"
                )

        # ── 3. 不定態比例判斷 ─────────────────────────────────────────────────
        x_ratio_max = self._cfg.get("undefined_ratio_max", 0.20)
        cr.pass_x_ratio = (cr.x_ratio <= x_ratio_max)
        if not cr.pass_x_ratio:
            cr.fail_reasons.append(
                f"不定態比例過高（{cr.x_ratio*100:.1f}% > {x_ratio_max*100:.0f}%）"
            )

        # ── 4. 邊緣偵測與計數 ─────────────────────────────────────────────────
        # 將波形二值化（H=1, L=0，X 保持前一狀態）後計算邊緣
        binary = self._binarize(data, vh_min, vl_max)
        edges  = self._count_edges(binary)
        cr.edge_count = edges

        min_edges = (
            self._cfg.get("min_edges_encoder", 20)
            if is_encoder
            else self._cfg.get("min_edges_hall", 10)
        )
        cr.pass_edges = (edges >= min_edges)
        if not cr.pass_edges:
            cr.fail_reasons.append(
                f"邊緣數量不足（{edges} < {min_edges}，訊號可能無切換）"
            )

        # ── 5. 主頻率估算（過零率法）─────────────────────────────────────────
        cr.freq_hz = self._estimate_frequency(binary, sample_rate)

        # 頻率範圍判斷（0 = 不限制）
        if is_encoder:
            freq_min = self._cfg.get("freq_min_encoder", 0.0)
            freq_max = self._cfg.get("freq_max_encoder", 0.0)
        else:
            freq_min = self._cfg.get("freq_min_hall", 0.0)
            freq_max = self._cfg.get("freq_max_hall", 0.0)

        if freq_min > 0 and freq_max > 0 and cr.freq_hz > 0:
            cr.pass_freq = (freq_min <= cr.freq_hz <= freq_max)
            if not cr.pass_freq:
                cr.fail_reasons.append(
                    f"頻率超出範圍（{cr.freq_hz:.1f} Hz，允許 {freq_min:.1f}~{freq_max:.1f} Hz）"
                )
        else:
            cr.pass_freq = True  # 不限制頻率範圍

        # ── 整體判斷 ──────────────────────────────────────────────────────────
        cr.overall_pass = (
            cr.pass_hl_ratio and
            cr.pass_x_ratio  and
            cr.pass_edges    and
            cr.pass_freq
        )

        return cr

    # ─── 私有輔助方法 ─────────────────────────────────────────────────────────

    def _get_vh_min(self, ch_idx: int) -> float:
        """依通道索引取得 H 準位閾值"""
        if ch_idx < 3:
            return HALL_THRESHOLDS["vh_min"]
        return ENCODER_THRESHOLDS["vh_min"]

    def _get_vl_max(self, ch_idx: int) -> float:
        """依通道索引取得 L 準位閾值"""
        if ch_idx < 3:
            return HALL_THRESHOLDS["vl_max"]
        return ENCODER_THRESHOLDS["vl_max"]

    def _binarize(
        self,
        data: np.ndarray,
        vh_min: float,
        vl_max: float
    ) -> np.ndarray:
        """
        將波形二值化（H=1, L=0）
        不定態區間（X）保持前一狀態（forward-fill）

        Args:
            data:   原始波形（float32）
            vh_min: H 準位閾值
            vl_max: L 準位閾值

        Returns:
            np.ndarray: int8 陣列，值為 0 或 1
        """
        n = len(data)
        binary = np.zeros(n, dtype=np.int8)

        # 初始狀態：找第一個確定的 H 或 L
        init_state = 0
        for v in data[:min(1000, n)]:
            if v >= vh_min:
                init_state = 1
                break
            elif v <= vl_max:
                init_state = 0
                break

        state = init_state
        for i in range(n):
            v = data[i]
            if v >= vh_min:
                state = 1
            elif v <= vl_max:
                state = 0
            # else: 不定態，保持前一狀態
            binary[i] = state

        return binary

    def _count_edges(self, binary: np.ndarray) -> int:
        """
        計算邊緣總數（上升沿 + 下降沿）

        Args:
            binary: 二值化陣列（0/1）

        Returns:
            int: 邊緣總數
        """
        if len(binary) < 2:
            return 0
        diff = np.diff(binary.astype(np.int16))
        return int(np.sum(diff != 0))

    def _estimate_frequency(
        self,
        binary: np.ndarray,
        sample_rate: int
    ) -> float:
        """
        估算主頻率（過零率法）
        計算上升沿數量 / 總時間 = 頻率

        Args:
            binary:      二值化陣列（0/1）
            sample_rate: 取樣率 (Hz)

        Returns:
            float: 估算頻率 (Hz)，無法估算時回傳 0.0
        """
        if len(binary) < 2 or sample_rate <= 0:
            return 0.0

        diff = np.diff(binary.astype(np.int16))
        rising_edges = int(np.sum(diff > 0))  # 上升沿數量 = 週期數

        if rising_edges == 0:
            return 0.0

        total_time_s = len(binary) / sample_rate
        freq = rising_edges / total_time_s
        return float(freq)

    def _build_ch_summary(
        self,
        channel_results: List[DiagChannelResult],
        channels: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        建立各通道跨輪次彙整結果

        Returns:
            dict: {ch_name: {"pass": bool, "rounds": [DiagChannelResult], "avg_freq": float}}
        """
        summary = {}
        for ch_def in channels:
            ch_name = ch_def.get("name", "")
            rounds_results = [r for r in channel_results if r.ch_name == ch_name]
            ch_pass = all(r.overall_pass for r in rounds_results) and len(rounds_results) > 0
            avg_freq = (
                float(np.mean([r.freq_hz for r in rounds_results if r.freq_hz > 0]))
                if any(r.freq_hz > 0 for r in rounds_results)
                else 0.0
            )
            summary[ch_name] = {
                "pass":     ch_pass,
                "rounds":   rounds_results,
                "avg_freq": avg_freq,
            }
        return summary

    def _build_summary_text(
        self,
        result: DiagOverallResult,
        channels: List[Dict[str, Any]],
        rounds: int
    ) -> str:
        """
        產生人類可讀的診斷摘要文字（供對話框顯示）

        Returns:
            str: 多行摘要文字
        """
        lines = []
        overall_str = "✔ PASS" if result.overall_pass else "✘ FAIL"
        lines.append(f"整體診斷結果：{overall_str}")
        lines.append(f"（{result.pass_count} / {result.total_count} 通道×輪次 PASS）")
        lines.append("")

        for ch_def in channels:
            ch_name = ch_def.get("name", "")
            ch_info = result.ch_summary.get(ch_name, {})
            ch_pass = ch_info.get("pass", False)
            ch_rounds = ch_info.get("rounds", [])
            avg_freq = ch_info.get("avg_freq", 0.0)

            ch_str = "✔" if ch_pass else "✘"
            freq_str = f"  主頻: {avg_freq:.1f} Hz" if avg_freq > 0 else ""
            lines.append(f"  {ch_str} {ch_name}{freq_str}")

            # 顯示各輪次詳細
            for r in ch_rounds:
                round_str = "✔" if r.overall_pass else "✘"
                lines.append(
                    f"      第{r.round_idx+1}輪: {round_str}  "
                    f"H={r.h_ratio*100:.0f}%  X={r.x_ratio*100:.0f}%  "
                    f"邊緣={r.edge_count}  {r.freq_hz:.1f}Hz"
                )
                for reason in r.fail_reasons:
                    lines.append(f"        ⚠ {reason}")

        return "\n".join(lines)


# ─── 靜態工具：從 npz 載入並分析 ─────────────────────────────────────────────

def analyze_from_npz(filepath: str) -> DiagOverallResult:
    """
    從診斷 npz 檔案載入資料並執行分析

    Args:
        filepath: .npz 檔案路徑

    Returns:
        DiagOverallResult: 整體分析結果
    """
    from logic.diagnostic_scanner import DiagnosticScanner

    loaded = DiagnosticScanner.load(filepath)
    sample_rate = loaded["sample_rate"]
    rounds      = loaded["rounds"]
    ch_count    = loaded["ch_count"]
    ch_names    = loaded["channel_names"]
    ch_nums     = loaded["channel_nums"]
    data_dict   = loaded["data"]

    # 重建 raw_results[round_idx][ch_idx]
    raw_results = []
    for round_idx in range(rounds):
        round_data = []
        for ch_idx in range(ch_count):
            key = f"ch{ch_idx}_round{round_idx}"
            arr = data_dict.get(key)
            round_data.append(arr if arr is not None and len(arr) > 0 else None)
        raw_results.append(round_data)

    # 重建 channels 定義（從 thresholds 填入閾值）
    channels = []
    for ch_idx in range(ch_count):
        ch_num = int(ch_nums[ch_idx]) if ch_idx < len(ch_nums) else ch_idx
        ch_name = str(ch_names[ch_idx]) if ch_idx < len(ch_names) else f"CH{ch_idx}"
        if ch_num < 3:
            vh_min = HALL_THRESHOLDS["vh_min"]
            vl_max = HALL_THRESHOLDS["vl_max"]
        else:
            vh_min = ENCODER_THRESHOLDS["vh_min"]
            vl_max = ENCODER_THRESHOLDS["vl_max"]
        channels.append({
            "ch":     ch_num,
            "name":   ch_name,
            "vh_min": vh_min,
            "vl_max": vl_max,
        })

    analyzer = DiagAnalyzer()
    return analyzer.analyze_all(raw_results, channels, sample_rate)
