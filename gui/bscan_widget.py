# -*- coding: utf-8 -*-
"""B-scan 결과 뷰어 — 게인/컬러맵/대비 조절."""

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QDoubleSpinBox,
    QPushButton, QFileDialog,
)

from config import C0
from gui.style import kr_info

GAIN_MODES = ["원본", "선형 t-게인", "AGC"]
COLORMAPS = ["gray", "seismic", "viridis", "jet"]


def apply_gain(data: np.ndarray, mode: str, dt: float) -> np.ndarray:
    if mode == "선형 t-게인":
        t = np.arange(data.shape[0], dtype=float)
        return data * (1.0 + t / max(1.0, data.shape[0]) * 20.0)[:, None]
    if mode == "AGC":
        win = max(8, data.shape[0] // 40)
        out = np.empty_like(data, dtype=float)
        for j in range(data.shape[1]):
            tr = data[:, j].astype(float)
            env = np.convolve(np.abs(tr), np.ones(win) / win, mode="same")
            out[:, j] = tr / np.maximum(env, env.max() * 1e-3 + 1e-30)
        return out
    return data.astype(float)


class BScanWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = None
        self._dt = None
        self._x_start = 0.0
        self._step = 0.05
        self._eps_bg = 5.0

        self._fig = Figure(figsize=(8, 5), tight_layout=True)
        self._canvas = FigureCanvasQTAgg(self._fig)
        self._ax = self._fig.add_subplot(111)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("게인:"))
        self._cmb_gain = QComboBox()
        self._cmb_gain.addItems(GAIN_MODES)
        self._cmb_gain.setCurrentIndex(1)
        bar.addWidget(self._cmb_gain)
        bar.addWidget(QLabel("컬러맵:"))
        self._cmb_cmap = QComboBox()
        self._cmb_cmap.addItems(COLORMAPS)
        bar.addWidget(self._cmb_cmap)
        bar.addWidget(QLabel("대비 clip (%):"))
        self._spn_clip = QDoubleSpinBox()
        self._spn_clip.setRange(80.0, 100.0)
        self._spn_clip.setValue(98.0)
        self._spn_clip.setSingleStep(0.5)
        bar.addWidget(self._spn_clip)
        self._btn_png = QPushButton("PNG 저장...")
        bar.addWidget(self._btn_png)
        bar.addStretch(1)

        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(self._canvas, 1)

        self._cmb_gain.currentIndexChanged.connect(self._replot)
        self._cmb_cmap.currentIndexChanged.connect(self._replot)
        self._spn_clip.valueChanged.connect(self._replot)
        self._btn_png.clicked.connect(self._save_png)

    def set_data(self, data, dt, x_start, step, eps_bg):
        self._data = data
        self._dt = dt
        self._x_start = x_start
        self._step = step
        self._eps_bg = max(1.0, eps_bg)
        self._replot()

    def _replot(self):
        ax = self._ax
        ax.clear()
        if self._data is None:
            ax.set_title("시뮬레이션 결과 없음")
            self._canvas.draw_idle()
            return
        d = apply_gain(self._data, self._cmb_gain.currentText(), self._dt)
        vmax = np.percentile(np.abs(d), self._spn_clip.value())
        n = d.shape[1]
        t_end_ns = d.shape[0] * self._dt * 1e9
        x_end = self._x_start + (n - 1) * self._step
        ax.imshow(d, aspect="auto", cmap=self._cmb_cmap.currentText(),
                  vmin=-vmax, vmax=vmax, extent=[self._x_start, x_end, t_end_ns, 0],
                  interpolation="bilinear")
        ax.set_xlabel("Distance (m)")
        ax.set_ylabel("Time (ns)")

        # 우측 보조축: 배경 매질 속도 기준 환산 깊이
        v = C0 / (self._eps_bg ** 0.5)
        sec = ax.secondary_yaxis(
            "right",
            functions=(lambda t: t * 1e-9 * v / 2.0, lambda z: z * 2.0 / v * 1e9))
        sec.set_ylabel(f"환산 깊이 (m, εr={self._eps_bg:.0f})")
        self._canvas.draw_idle()

    def _save_png(self):
        if self._data is None:
            kr_info(self, "PNG 저장", "저장할 결과가 없습니다.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "B-scan PNG 저장", "bscan.png",
                                              "PNG 이미지 (*.png)")
        if not path:
            return
        self._fig.savefig(path, dpi=200)
