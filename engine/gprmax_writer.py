# -*- coding: utf-8 -*-
"""GPRModel → gprMax .in 입력파일 생성.

gprMax 2D 규약 (cylinder_Bscan_2D 예제 기준):
- domain z = 1셀 (dz), TMz 모드
- 좌표 (x, y, z): y 는 위로 증가. 지하 y=[0, depth], 공기 y=[depth, depth+air]
- Hertzian dipole z 편파, 지표면 (y=depth) 에 배치
- 기하 명령은 나중 것이 먼저 것을 덮어씀 (painting)
"""

import os

from core.model import GPRModel, Material


def _mat_id(mat: Material, registry: dict) -> str:
    """재질 → gprMax 재질 식별자. air/pec 은 내장 이름 사용."""
    if mat.is_air:
        return "free_space"
    if mat.is_pec:
        return "pec"
    key = (mat.epsilon_r, mat.sigma, mat.mu_r)
    if key not in registry:
        registry[key] = f"mat{len(registry) + 1}"
    return registry[key]


def write_input_file(model: GPRModel, path: str, title: str = "G_RSim model") -> int:
    """모델을 .in 파일로 저장하고 B-scan trace 수를 반환."""
    m = model
    a = m.antenna
    dz = m.cell
    dom_y = m.depth + m.air_height
    y_surf = m.depth
    tw_s = m.effective_time_window_ns() * 1e-9
    f_hz = a.freq_mhz * 1e6
    n = m.n_traces()

    registry = {}
    lines = []
    add = lines.append

    add(f"#title: {title}")
    add(f"#domain: {m.width:.6g} {dom_y:.6g} {dz:.6g}")
    add(f"#dx_dy_dz: {m.cell:.6g} {m.cell:.6g} {dz:.6g}")
    add(f"#time_window: {tw_s:.6e}")
    add("")

    # ---- 재질 등록 (기하 명령보다 먼저) ----
    geom = []
    gadd = geom.append

    def box_cmd(x1, d1, x2, d2, mat):
        """깊이 좌표 사각형 → gprMax #box (y 변환, 좌하→우상 정렬)."""
        xa, xb = sorted((x1, x2))
        ya, yb = sorted((y_surf - d1, y_surf - d2))
        gadd(f"#box: {xa:.6g} {ya:.6g} 0 {xb:.6g} {yb:.6g} {dz:.6g} {_mat_id(mat, registry)}")

    # 배경 반무한 매질 (지하 전체)
    box_cmd(0, m.depth, m.width, 0, m.background)
    # 수평 층 (입력 순서대로 덮어쓰기)
    for ly in m.layers:
        box_cmd(0, ly.bottom_d, m.width, ly.top_d, ly.material)
    # 사각 객체
    for b in m.boxes:
        box_cmd(b.x1, b.d1, b.x2, b.d2, b.material)
    # 원형 객체 (z 축 방향 실린더)
    for c in m.cylinders:
        y = y_surf - c.d
        gadd(f"#cylinder: {c.x:.6g} {y:.6g} 0 {c.x:.6g} {y:.6g} {dz:.6g} "
             f"{c.radius:.6g} {_mat_id(c.material, registry)}")

    for (eps, sig, mu), name in registry.items():
        add(f"#material: {eps:.6g} {sig:.6g} {mu:.6g} 0 {name}")
    add("")

    # ---- 소스/수신기 ----
    add(f"#waveform: ricker 1 {f_hz:.6g} src_wave")
    add(f"#hertzian_dipole: z {a.x_start:.6g} {y_surf:.6g} 0 src_wave")
    add(f"#rx: {a.x_start + a.offset:.6g} {y_surf:.6g} 0")
    if n > 1:
        add(f"#src_steps: {a.step:.6g} 0 0")
        add(f"#rx_steps: {a.step:.6g} 0 0")
    add("")

    lines.extend(geom)
    add("")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="ascii") as f:
        f.write("\n".join(lines) + "\n")
    return n
