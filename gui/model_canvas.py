# -*- coding: utf-8 -*-
"""모델 빌더 캔버스 — 지하 단면(거리 x 깊이) 표시 + 마우스 그리기."""

import matplotlib
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle, Circle
from PySide6.QtCore import Qt, Signal

from config import FONT_FAMILY

matplotlib.rcParams["font.family"] = FONT_FAMILY
matplotlib.rcParams["axes.unicode_minus"] = False


class ModelCanvas(FigureCanvasQTAgg):
    """GPRModel 단면 표시. 도구 모드: select / box / cylinder."""

    box_drawn = Signal(float, float, float, float)      # x1, d1, x2, d2
    cylinder_drawn = Signal(float, float, float)        # x, d, radius
    object_clicked = Signal(str, int)                   # kind('layer'|'box'|'cyl'), index

    def __init__(self, parent=None):
        self._fig = Figure(figsize=(8, 5), tight_layout=True)
        super().__init__(self._fig)
        self.setParent(parent)
        self._ax = self._fig.add_subplot(111)
        self._model = None
        self._tool = "select"
        self._press_xy = None       # 드래그 시작 (x, d)
        self._preview = None        # 드래그 미리보기 artist
        self._selected = None       # (kind, index)

        self.mpl_connect("button_press_event", self._on_press)
        self.mpl_connect("motion_notify_event", self._on_motion)
        self.mpl_connect("button_release_event", self._on_release)

    # ---- 외부 인터페이스 ----

    def set_model(self, model):
        self._model = model
        self.redraw()

    def set_tool(self, tool: str):
        self._tool = tool
        self._press_xy = None
        if tool in ("box", "cylinder"):
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_selected(self, kind, index):
        self._selected = (kind, index) if kind else None
        self.redraw()

    # ---- 렌더 ----

    def redraw(self):
        ax = self._ax
        ax.clear()
        m = self._model
        if m is None:
            self.draw_idle()
            return

        # 공기 + 배경
        ax.add_patch(Rectangle((0, -m.air_height), m.width, m.air_height,
                               facecolor="#EAF4FF", edgecolor="none"))
        ax.add_patch(Rectangle((0, 0), m.width, m.depth,
                               facecolor=m.background.color, edgecolor="none"))

        # 층 (입력 순서 = 덮어쓰기 순서)
        for i, ly in enumerate(m.layers):
            ax.add_patch(Rectangle((0, ly.top_d), m.width, ly.bottom_d - ly.top_d,
                                   facecolor=ly.material.color, edgecolor="none"))
        # 사각
        for b in m.boxes:
            x0, d0 = min(b.x1, b.x2), min(b.d1, b.d2)
            ax.add_patch(Rectangle((x0, d0), abs(b.x2 - b.x1), abs(b.d2 - b.d1),
                                   facecolor=b.material.color, edgecolor="#333333", lw=0.6))
        # 원
        for c in m.cylinders:
            ax.add_patch(Circle((c.x, c.d), c.radius,
                                facecolor=c.material.color, edgecolor="#333333", lw=0.6))

        # 선택 강조
        if self._selected:
            kind, idx = self._selected
            try:
                if kind == "layer":
                    ly = m.layers[idx]
                    ax.add_patch(Rectangle((0, ly.top_d), m.width, ly.bottom_d - ly.top_d,
                                           facecolor="none", edgecolor="red", lw=1.6, ls="--"))
                elif kind == "box":
                    b = m.boxes[idx]
                    x0, d0 = min(b.x1, b.x2), min(b.d1, b.d2)
                    ax.add_patch(Rectangle((x0, d0), abs(b.x2 - b.x1), abs(b.d2 - b.d1),
                                           facecolor="none", edgecolor="red", lw=1.6, ls="--"))
                elif kind == "cyl":
                    c = m.cylinders[idx]
                    ax.add_patch(Circle((c.x, c.d), c.radius,
                                        facecolor="none", edgecolor="red", lw=1.6, ls="--"))
            except IndexError:
                self._selected = None

        # 빈 모델 사용 안내
        if not (m.layers or m.boxes or m.cylinders):
            ax.text(m.width / 2, m.depth * 0.45,
                    "사용 순서\n\n"
                    "① 좌측에서 측선 폭 / 깊이 / 주파수 / 배경 매질 설정\n"
                    "② 그리기 재질 선택 후 [사각형]이나 [원형] 도구로\n"
                    "     이 화면에 드래그하여 관로 / 공동 / 구조물 배치\n"
                    "     ([층 추가]로 수평 지층도 가능)\n"
                    "③ [시뮬레이션 실행] → B-scan 결과 탭에서 확인",
                    ha="center", va="center", fontsize=12, color="#333333",
                    linespacing=1.6,
                    bbox=dict(boxstyle="round,pad=0.8", facecolor="white",
                              edgecolor="#0096c8", alpha=0.9))

        # 지표선 + 안테나 스캔 범위
        ax.axhline(0, color="k", lw=1.2)
        a = m.antenna
        ax.plot([a.x_start, a.x_end], [-m.air_height * 0.4] * 2,
                color="#D62728", lw=2.5, solid_capstyle="butt")
        ax.annotate("", xy=(a.x_end, -m.air_height * 0.4),
                    xytext=(a.x_end - min(0.3, m.width * 0.03), -m.air_height * 0.4),
                    arrowprops=dict(arrowstyle="->", color="#D62728", lw=2))

        ax.set_xlim(0, m.width)
        ax.set_ylim(m.depth, -m.air_height)
        ax.set_xlabel("Distance (m)")
        ax.set_ylabel("Depth (m)")
        ax.set_aspect("auto")
        ax.grid(True, color="#FFFFFF", alpha=0.35, lw=0.5)
        self.draw_idle()

    # ---- 마우스 ----

    def _event_xd(self, event):
        if event.inaxes != self._ax or event.xdata is None:
            return None
        return (event.xdata, event.ydata)

    def _on_press(self, event):
        pt = self._event_xd(event)
        if pt is None or self._model is None or event.button != 1:
            return
        if self._tool in ("box", "cylinder"):
            self._press_xy = pt
        elif self._tool == "select":
            self._pick_object(pt)

    def _on_motion(self, event):
        if self._press_xy is None:
            return
        pt = self._event_xd(event)
        if pt is None:
            return
        if self._preview is not None:
            self._preview.remove()
            self._preview = None
        x0, d0 = self._press_xy
        if self._tool == "box":
            self._preview = self._ax.add_patch(
                Rectangle((min(x0, pt[0]), min(d0, pt[1])),
                          abs(pt[0] - x0), abs(pt[1] - d0),
                          facecolor="none", edgecolor="blue", lw=1.2, ls="--"))
        else:
            r = ((pt[0] - x0) ** 2 + (pt[1] - d0) ** 2) ** 0.5
            self._preview = self._ax.add_patch(
                Circle((x0, d0), r, facecolor="none", edgecolor="blue", lw=1.2, ls="--"))
        self.draw_idle()

    def _on_release(self, event):
        if self._press_xy is None:
            return
        pt = self._event_xd(event)
        x0, d0 = self._press_xy
        self._press_xy = None
        if self._preview is not None:
            self._preview.remove()
            self._preview = None
        if pt is None:
            self.draw_idle()
            return
        if self._tool == "box":
            if abs(pt[0] - x0) > 1e-3 and abs(pt[1] - d0) > 1e-3:
                self.box_drawn.emit(x0, d0, pt[0], pt[1])
        elif self._tool == "cylinder":
            r = ((pt[0] - x0) ** 2 + (pt[1] - d0) ** 2) ** 0.5
            if r > 1e-3:
                self.cylinder_drawn.emit(x0, d0, r)

    def _pick_object(self, pt):
        """클릭 지점의 객체 탐색 — 원/사각 우선(위에 그려짐), 다음 층."""
        m = self._model
        x, d = pt
        for i in range(len(m.cylinders) - 1, -1, -1):
            c = m.cylinders[i]
            if (x - c.x) ** 2 + (d - c.d) ** 2 <= c.radius ** 2:
                self.object_clicked.emit("cyl", i)
                return
        for i in range(len(m.boxes) - 1, -1, -1):
            b = m.boxes[i]
            if min(b.x1, b.x2) <= x <= max(b.x1, b.x2) and min(b.d1, b.d2) <= d <= max(b.d1, b.d2):
                self.object_clicked.emit("box", i)
                return
        for i in range(len(m.layers) - 1, -1, -1):
            ly = m.layers[i]
            if ly.top_d <= d <= ly.bottom_d:
                self.object_clicked.emit("layer", i)
                return
        self.object_clicked.emit("", -1)
