# -*- coding: utf-8 -*-
"""GPR 시뮬레이션 모델 데이터 구조.

좌표 규약:
- x: 측선 방향 거리 (m), 0 ~ width
- d: 깊이 (m), 지표 0, 아래로 증가
- gprMax 변환 시 y = depth - d (y 위로 증가, 지표 y=depth)
"""

from dataclasses import dataclass, field

from config import C0


@dataclass
class Material:
    name: str
    epsilon_r: float = 1.0
    sigma: float = 0.0          # 전기전도도 (S/m)
    mu_r: float = 1.0
    color: str = "#CCCCCC"      # 모델 캔버스 표시 색
    is_pec: bool = False        # 완전도체 (금속)
    is_air: bool = False        # 공기 (gprMax free_space)

    @property
    def velocity(self) -> float:
        """전파속도 (m/s)."""
        return C0 / (self.epsilon_r ** 0.5)


# 대표 매질 프리셋 (εr, σ 는 문헌 대표값)
MATERIAL_PRESETS = [
    Material("공기", 1.0, 0.0, color="#E8F4FF", is_air=True),
    Material("건조 모래", 5.0, 0.001, color="#E7D8A1"),
    Material("습윤 모래", 20.0, 0.01, color="#C9B26D"),
    Material("점토", 12.0, 0.05, color="#B0763B"),
    Material("실트", 8.0, 0.01, color="#C89A6B"),
    Material("자갈", 6.0, 0.002, color="#A9A9A9"),
    Material("콘크리트", 8.0, 0.005, color="#9E9E9E"),
    Material("아스팔트", 5.0, 0.001, color="#5A5A5A"),
    Material("화강암", 6.0, 0.00001, color="#D8BFD8"),
    Material("석회암", 7.0, 0.00001, color="#DCD0C0"),
    Material("풍화암", 10.0, 0.005, color="#BC8F8F"),
    Material("물 (담수)", 81.0, 0.001, color="#7EC8E3"),
    Material("금속 (PEC)", 1.0, 0.0, color="#404040", is_pec=True),
]


@dataclass
class LayerObject:
    """수평 층 — 깊이 구간 [top_d, bottom_d]."""
    top_d: float
    bottom_d: float
    material: Material

    def label(self) -> str:
        return f"층 {self.top_d:.2f}~{self.bottom_d:.2f}m ({self.material.name})"


@dataclass
class BoxObject:
    """사각 객체 — (x1,d1)~(x2,d2)."""
    x1: float
    d1: float
    x2: float
    d2: float
    material: Material

    def label(self) -> str:
        return (f"사각 x{min(self.x1, self.x2):.2f}~{max(self.x1, self.x2):.2f} "
                f"d{min(self.d1, self.d2):.2f}~{max(self.d1, self.d2):.2f} ({self.material.name})")


@dataclass
class CylinderObject:
    """원형 객체 (관로/공동 단면) — 중심 (x, d), 반지름 r."""
    x: float
    d: float
    radius: float
    material: Material

    def label(self) -> str:
        return f"원 ({self.x:.2f}, {self.d:.2f}) r={self.radius:.3f} ({self.material.name})"


@dataclass
class AntennaConfig:
    freq_mhz: float = 400.0     # 중심 주파수 (Ricker)
    offset: float = 0.1         # TX-RX 간격 (m)
    step: float = 0.1           # trace 간격 (m)
    x_start: float = 0.5        # 첫 TX 위치 (m)
    x_end: float = 9.5          # 마지막 RX 허용 위치 (m)


@dataclass
class GPRModel:
    width: float = 10.0         # 측선 길이 (m)
    depth: float = 3.0          # 모델 깊이 (m)
    cell: float = 0.01          # 셀 크기 (m)
    air_height: float = 0.2     # 지표 위 공기층 두께 (m)
    time_window_ns: float = 0.0     # 0 이면 자동 산정
    background: Material = field(default_factory=lambda: MATERIAL_PRESETS[1])
    layers: list = field(default_factory=list)      # list[LayerObject]
    boxes: list = field(default_factory=list)       # list[BoxObject]
    cylinders: list = field(default_factory=list)   # list[CylinderObject]
    antenna: AntennaConfig = field(default_factory=AntennaConfig)

    # ---- 파생값 ----

    def max_epsilon(self) -> float:
        eps = [self.background.epsilon_r]
        eps += [ly.material.epsilon_r for ly in self.layers]
        eps += [b.material.epsilon_r for b in self.boxes]
        eps += [c.material.epsilon_r for c in self.cylinders]
        return max(eps)

    def auto_time_window_ns(self) -> float:
        """왕복 주시 자동 산정: 최저속 매질 기준 2*depth/v + 20% 여유."""
        v = C0 / (self.max_epsilon() ** 0.5)
        tw = 2.0 * self.depth / v * 1.2
        return tw * 1e9

    def effective_time_window_ns(self) -> float:
        return self.time_window_ns if self.time_window_ns > 0 else self.auto_time_window_ns()

    def suggest_cell(self) -> float:
        """λ_min/10 권장 셀 크기 (Ricker 최대 유효주파수 ≈ 2.5 f_c)."""
        f_max = self.antenna.freq_mhz * 1e6 * 2.5
        v = C0 / (self.max_epsilon() ** 0.5)
        return v / f_max / 10.0

    def nice_cell(self) -> float:
        """권장 셀 이하의 '깔끔한' 값 (1/2/2.5/5 x 10^k)."""
        target = self.suggest_cell()
        k = 1.0
        while k > target:
            k /= 10.0
        best = k
        for m in (2.0, 2.5, 5.0):
            if k * m <= target:
                best = k * m
        return max(best, 0.001)

    def auto_antenna_range(self) -> tuple:
        """PML(10셀)+여유 2셀을 피한 측선 전체 스캔 범위 (x_start, x_end).

        우측 여유는 trace 간격 이상 확보 — gprMax 가 스텝 위치를
        n스텝(실제 최종은 n-1스텝)으로 보수 검사하는 것에 대응.
        """
        margin = 12 * self.cell
        margin_r = max(margin, self.antenna.step)
        return (round(margin, 3), round(self.width - margin_r, 3))

    def n_traces(self) -> int:
        a = self.antenna
        span = a.x_end - a.offset - a.x_start
        if span < 0 or a.step <= 0:
            return 0
        return int(span / a.step + 1e-9) + 1

    def validate(self) -> list:
        """오류 메시지 목록 (빈 리스트 = 통과)."""
        errs = []
        a = self.antenna
        pml = 10 * self.cell  # 기본 PML 10셀
        if self.width <= 0 or self.depth <= 0 or self.cell <= 0:
            errs.append("도메인 폭/깊이/셀 크기는 0보다 커야 합니다.")
            return errs
        if self.n_traces() < 1:
            errs.append("측정 trace 수가 0입니다. 안테나 시작/끝/간격을 확인하세요.")
        if a.x_start < pml + self.cell:
            errs.append(f"안테나 시작 위치가 PML 영역과 겹칩니다 (최소 {pml + self.cell:.2f}m).")
        if a.x_end > self.width - pml - self.cell:
            errs.append(f"안테나 끝 위치가 PML 영역과 겹칩니다 (최대 {self.width - pml - self.cell:.2f}m).")
        if self.air_height < pml + 2 * self.cell:
            errs.append(f"공기층이 너무 얇습니다 (최소 {pml + 2 * self.cell:.2f}m = PML 10셀 + 여유).")
        n = self.n_traces()
        if n >= 1 and a.x_start + a.offset + a.step * n > self.width + 1e-9:
            errs.append("스캔 스텝이 측선 끝을 넘습니다 (gprMax 는 n스텝 기준으로 검사). "
                        "끝 위치나 trace 간격을 줄이세요.")
        suggested = self.suggest_cell()
        if self.cell > suggested * 1.5:
            errs.append(f"셀 {self.cell*100:.1f}cm 가 권장값 {suggested*100:.1f}cm 보다 큽니다 (수치분산 우려).")
        return errs
