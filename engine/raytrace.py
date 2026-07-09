# -*- coding: utf-8 -*-
"""레이트레이싱 합성 레이더그램 (GPRSIM 방식의 근사 엔진).

FDTD 와 달리 사용자가 정한 반사 계열만 기하학적으로 계산:
- 직접파 (공기파 + 지표파)
- 원형 객체: 점회절체 근사 (중심까지 거리 - 반지름)
- 사각 객체: 상면 경면반사 + 상부 모서리 회절
- 수평 층: 1차 반사 (R), 옵션으로 2차 다중반사 (RR)

한계 (FDTD 대비): 링잉/공진, 거친 산란, 객체 간 상호작용 없음.
속도: 전체 B-scan 이 1초 미만.
"""

import numpy as np

from config import C0
from core.model import GPRModel

_C_NS = C0 * 1e-9          # m/ns
_ETA0 = 376.7303           # 자유공간 파동임피던스 (Ohm)


def _ricker(t_ns: np.ndarray, f_mhz: float) -> np.ndarray:
    """Ricker 파형 (t=0 에서 피크)."""
    f_ghz = f_mhz / 1000.0
    a = (np.pi * f_ghz * t_ns) ** 2
    return (1.0 - 2.0 * a) * np.exp(-a)


def _refl_coef(eps_above: float, eps_below: float, pec: bool) -> float:
    """수직입사 반사계수 (비자성, 저손실 근사)."""
    if pec:
        return -1.0
    n1, n2 = eps_above ** 0.5, eps_below ** 0.5
    return (n1 - n2) / (n1 + n2)


class _Profile:
    """깊이별 매질 프로파일 (배경 + 수평 층). 수직 슬로우니스 적분용."""

    def __init__(self, model: GPRModel):
        self._bg = model.background
        # (top, bottom, material) — 나중 층이 위를 덮음 (painting 순서 유지)
        self._layers = [(ly.top_d, ly.bottom_d, ly.material) for ly in model.layers]

    def material_at(self, d: float):
        mat = self._bg
        for top, bot, m in self._layers:
            if top <= d < bot:
                mat = m
        return mat

    def eps_at(self, d: float) -> float:
        return self.material_at(d).epsilon_r

    def twoway_time_ns(self, depth: float, half_offset: float, n_seg: int = 64) -> float:
        """지표→depth 왕복 주시 (경사 직선경로, 층별 슬로우니스 적분)."""
        if depth <= 0:
            return 0.0
        path = (depth ** 2 + half_offset ** 2) ** 0.5    # 편도 경사거리
        stretch = path / depth
        zs = np.linspace(0, depth, n_seg + 1)
        zm = 0.5 * (zs[1:] + zs[:-1])
        dz = depth / n_seg
        slow = np.array([self.eps_at(z) ** 0.5 / _C_NS for z in zm])   # ns/m
        return 2.0 * float(np.sum(slow * dz)) * stretch

    def attenuation(self, depth: float, n_seg: int = 32) -> float:
        """왕복 감쇠 계수 exp(-2 α d) (층별 σ 적분, 저손실 근사)."""
        if depth <= 0:
            return 1.0
        zs = np.linspace(0, depth, n_seg + 1)
        zm = 0.5 * (zs[1:] + zs[:-1])
        dz = depth / n_seg
        total = 0.0
        for z in zm:
            m = self.material_at(z)
            alpha = m.sigma * _ETA0 / (2.0 * m.epsilon_r ** 0.5)   # Np/m
            total += alpha * dz
        return float(np.exp(-2.0 * total))


def simulate_raytrace(model: GPRModel, include_multiples: bool = False):
    """레이트레이싱 B-scan 합성 → (data[samples, n_traces], dt초)."""
    m = model
    a = m.antenna
    prof = _Profile(m)
    f = a.freq_mhz

    tw_ns = m.effective_time_window_ns()
    dt_ns = 1000.0 / (f * 40.0)          # 파장당 40샘플
    n_samp = int(tw_ns / dt_ns) + 1
    t_axis = np.arange(n_samp) * dt_ns
    n_tr = m.n_traces()
    data = np.zeros((n_samp, n_tr))

    t0 = 1000.0 / f    # gprMax ricker 지연(≈1/f)과 시각 정합

    def add_event(j, t_ns, amp):
        if t_ns < 0 or amp == 0.0:
            return
        data[:, j] += amp * _ricker(t_axis - (t_ns + t0), f)

    # 층 경계 목록: (깊이, 위 매질 εr, 아래 매질, R계수)
    interfaces = []
    for ly in m.layers:
        for d_if in (ly.top_d, ly.bottom_d):
            if d_if <= 0 or d_if >= m.depth:
                continue
            above = prof.material_at(max(d_if - 1e-4, 0.0))
            below = prof.material_at(d_if + 1e-4)
            if above is below:
                continue
            rc = _refl_coef(above.epsilon_r, below.epsilon_r, below.is_pec)
            if abs(rc) > 1e-6:
                interfaces.append((d_if, rc))

    # 지표(공기→지반) 반사계수 — 다중반사의 상부 반사에 사용
    r_surf = _refl_coef(prof.eps_at(0.0), 1.0, False) * -1.0  # 아래서 위로 볼 때 부호 반전

    for j in range(n_tr):
        tx = a.x_start + j * a.step
        rx = tx + a.offset
        mid = 0.5 * (tx + rx)
        half = 0.5 * abs(rx - tx)

        # ---- 직접파 ----
        add_event(j, abs(rx - tx) / _C_NS, 1.0)                                  # 공기파
        add_event(j, abs(rx - tx) * prof.eps_at(0.0) ** 0.5 / _C_NS, 0.8)        # 지표파

        # ---- 수평 층: 1차 반사 (R) ----
        for d_if, rc in interfaces:
            t_r = prof.twoway_time_ns(d_if, half)
            amp = rc * prof.attenuation(d_if) / max(d_if, 0.2)
            add_event(j, t_r, amp)
            # ---- 다중반사 (RR): 층↔지표 왕복 1회 추가 ----
            if include_multiples:
                add_event(j, 2.0 * t_r, amp * rc * r_surf / 2.0)

        # ---- 원형 객체: 점회절체 ----
        for c in m.cylinders:
            eps_bg = prof.eps_at(max(c.d - c.radius, 0.0))
            r1 = ((tx - c.x) ** 2 + c.d ** 2) ** 0.5 - c.radius
            r2 = ((rx - c.x) ** 2 + c.d ** 2) ** 0.5 - c.radius
            if r1 <= 0 or r2 <= 0:
                continue
            # 경로별 주시: 층 통과를 반영하기 위해 등가 수직깊이로 슬로우니스 적분
            d_eq = max(c.d - c.radius, 0.01)
            stretch = (r1 + r2) / (2.0 * d_eq)
            t_d = prof.twoway_time_ns(d_eq, 0.0) * stretch
            rc = _refl_coef(eps_bg, c.material.epsilon_r, c.material.is_pec)
            amp = rc * prof.attenuation(d_eq) / max((r1 + r2) * 0.5, 0.2)
            add_event(j, t_d, amp)

        # ---- 사각 객체: 상면 경면반사 + 상부 모서리 회절 ----
        for b in m.boxes:
            x1, x2 = sorted((b.x1, b.x2))
            d_top = min(b.d1, b.d2)
            eps_bg = prof.eps_at(max(d_top - 0.01, 0.0))
            rc = _refl_coef(eps_bg, b.material.epsilon_r, b.material.is_pec)
            if abs(rc) < 1e-6:
                continue
            att = prof.attenuation(d_top)
            if x1 <= mid <= x2:   # 상면 경면반사
                t_r = prof.twoway_time_ns(d_top, half)
                add_event(j, t_r, rc * att / max(d_top, 0.2))
            for cx in (x1, x2):   # 모서리 회절 (진폭 절반)
                r1 = ((tx - cx) ** 2 + d_top ** 2) ** 0.5
                r2 = ((rx - cx) ** 2 + d_top ** 2) ** 0.5
                d_eq = max(d_top, 0.01)
                stretch = (r1 + r2) / (2.0 * d_eq)
                t_d = prof.twoway_time_ns(d_eq, 0.0) * stretch
                amp = 0.5 * rc * att / max((r1 + r2) * 0.5, 0.2)
                add_event(j, t_d, amp)

    return data, dt_ns * 1e-9
