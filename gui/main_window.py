# -*- coding: utf-8 -*-
"""G_RSim 메인 윈도우 — 모델 빌더 + gprMax 시뮬레이션 + B-scan 뷰어."""

import os
import time

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QFormLayout, QGroupBox,
    QLabel, QComboBox, QDoubleSpinBox, QPushButton, QRadioButton, QButtonGroup,
    QListWidget, QProgressBar, QTabWidget, QCheckBox, QScrollArea, QSplitter,
)

from config import APP_NAME, APP_VERSION
from gui.style import GLOBAL_QSS, kr_info, kr_warn, kr_question
from core.model import (
    GPRModel, LayerObject, BoxObject, CylinderObject, MATERIAL_PRESETS,
)
from engine.gprmax_writer import write_input_file
from engine.gprmax_runner import run_simulation, read_bscan, cleanup_outputs
from gui.model_canvas import ModelCanvas
from gui.bscan_widget import BScanWidget

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")


class SimThread(QThread):
    progress = Signal(int, int)
    log_line = Signal(str)
    done = Signal(bool, str)

    def __init__(self, in_path, n_traces, parent=None):
        super().__init__(parent)
        self._in_path = in_path
        self._n = n_traces
        self._cancel = False
        self._log = []

    def cancel(self):
        self._cancel = True

    def _save_log(self):
        log_path = os.path.join(os.path.dirname(self._in_path), "last_run.log")
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("\n".join(self._log))
        except OSError:
            pass
        return log_path

    def _collect(self, line):
        self._log.append(line)
        self.log_line.emit(line)

    def run(self):
        try:
            ok = run_simulation(
                self._in_path, self._n,
                progress_cb=lambda c, t: self.progress.emit(c, t),
                log_cb=self._collect,
                cancel_flag=lambda: self._cancel,
            )
            log_path = self._save_log()
            if self._cancel:
                self.done.emit(False, "취소됨")
            elif ok:
                self.done.emit(True, "완료")
            else:
                tail = "\n".join(self._log[-6:]) if self._log else "(출력 없음)"
                self.done.emit(False,
                               f"gprMax 비정상 종료.\n\n--- 마지막 출력 ---\n{tail}\n\n"
                               f"전체 로그: {log_path}")
        except Exception as exc:  # noqa: BLE001
            self._save_log()
            self.done.emit(False, f"오류: {exc}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION} — GPR 시뮬레이터")
        self.resize(1280, 800)
        self.setStyleSheet(GLOBAL_QSS)

        self._model = GPRModel()
        self._thread = None
        self._selected = None      # (kind, index)

        self._build_ui()
        self._sync_panel_to_model()
        self._apply_autos()
        self._canvas.set_model(self._model)
        self._refresh_info()
        self.statusBar().showMessage(
            "① 좌측 설정 → ② 캔버스에 객체 그리기 → ③ 시뮬레이션 실행   "
            "(처음이면 [예제 모델] 버튼으로 바로 체험해 보세요)")

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        self.setCentralWidget(central)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 좌측 설정 패널 — QScrollArea (카탈로그 L1 패턴)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._build_left_panel())
        scroll.setFixedWidth(320)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        splitter.addWidget(scroll)

        self._tabs = QTabWidget()
        self._canvas = ModelCanvas(self)
        self._bscan = BScanWidget(self)
        self._tabs.addTab(self._canvas, "  모델  ")
        self._tabs.addTab(self._bscan, "  B-scan 결과  ")
        splitter.addWidget(self._tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter)

        self._canvas.box_drawn.connect(self._on_box_drawn)
        self._canvas.cylinder_drawn.connect(self._on_cyl_drawn)
        self._canvas.object_clicked.connect(self._on_object_clicked)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        def dspin(lo, hi, val, step, dec=2, suffix=""):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setValue(val)
            s.setSingleStep(step)
            s.setDecimals(dec)
            if suffix:
                s.setSuffix(suffix)
            return s

        # --- 예제/초기화 ---
        ex_row = QHBoxLayout()
        self._btn_example = QPushButton("예제 모델")
        self._btn_example.setToolTip("관로/공동/지층이 배치된 예제를 불러옵니다")
        self._btn_reset = QPushButton("모델 초기화")
        ex_row.addWidget(self._btn_example)
        ex_row.addWidget(self._btn_reset)
        lay.addLayout(ex_row)

        # --- 도메인 ---
        grp_dom = QGroupBox("도메인")
        f = QFormLayout(grp_dom)
        self._spn_width = dspin(0.5, 500, 10.0, 0.5, 2, " m")
        self._spn_depth = dspin(0.2, 50, 3.0, 0.5, 2, " m")
        self._chk_cell_auto = QCheckBox("자동")
        self._chk_cell_auto.setChecked(True)
        self._spn_cell = dspin(0.001, 0.5, 0.01, 0.005, 4, " m")
        self._spn_cell.setEnabled(False)
        cell_row = QHBoxLayout()
        cell_row.addWidget(self._spn_cell)
        cell_row.addWidget(self._chk_cell_auto)
        self._spn_air = dspin(0.05, 5, 0.2, 0.05, 2, " m")
        self._chk_tw_auto = QCheckBox("자동")
        self._chk_tw_auto.setChecked(True)
        self._spn_tw = dspin(1, 5000, 60, 10, 1, " ns")
        self._spn_tw.setEnabled(False)
        tw_row = QHBoxLayout()
        tw_row.addWidget(self._spn_tw)
        tw_row.addWidget(self._chk_tw_auto)
        f.addRow("측선 폭:", self._spn_width)
        f.addRow("깊이:", self._spn_depth)
        f.addRow("셀 크기:", cell_row)
        f.addRow("공기층:", self._spn_air)
        f.addRow("Time window:", tw_row)
        self._lbl_cell_hint = QLabel("")
        self._lbl_cell_hint.setStyleSheet("color: #666;")
        f.addRow("", self._lbl_cell_hint)
        lay.addWidget(grp_dom)

        # --- 안테나 ---
        grp_ant = QGroupBox("안테나 (Ricker)")
        f = QFormLayout(grp_ant)
        self._spn_freq = dspin(10, 3000, 400, 50, 0, " MHz")
        self._spn_offset = dspin(0.0, 5, 0.1, 0.01, 3, " m")
        self._spn_step = dspin(0.005, 5, 0.1, 0.01, 3, " m")
        self._chk_ant_auto = QCheckBox("스캔 범위 자동 (측선 전체)")
        self._chk_ant_auto.setChecked(True)
        self._spn_xs = dspin(0.0, 500, 0.5, 0.1, 2, " m")
        self._spn_xe = dspin(0.0, 500, 9.5, 0.1, 2, " m")
        self._spn_xs.setEnabled(False)
        self._spn_xe.setEnabled(False)
        f.addRow("중심 주파수:", self._spn_freq)
        f.addRow("TX-RX 간격:", self._spn_offset)
        f.addRow("Trace 간격:", self._spn_step)
        f.addRow("", self._chk_ant_auto)
        f.addRow("시작 위치:", self._spn_xs)
        f.addRow("끝 위치:", self._spn_xe)
        lay.addWidget(grp_ant)

        # --- 재질/객체 ---
        grp_obj = QGroupBox("모델 구성")
        v = QVBoxLayout(grp_obj)
        fr = QFormLayout()
        self._cmb_bg = QComboBox()
        for m in MATERIAL_PRESETS:
            self._cmb_bg.addItem(f"{m.name} (εr={m.epsilon_r:g})", m)
        self._cmb_bg.setCurrentIndex(1)
        fr.addRow("배경 매질:", self._cmb_bg)
        self._cmb_mat = QComboBox()
        for m in MATERIAL_PRESETS:
            self._cmb_mat.addItem(f"{m.name} (εr={m.epsilon_r:g})", m)
        self._cmb_mat.setCurrentIndex(len(MATERIAL_PRESETS) - 1)  # 금속
        fr.addRow("그리기 재질:", self._cmb_mat)
        v.addLayout(fr)

        tool_row = QHBoxLayout()
        self._rb_select = QRadioButton("선택")
        self._rb_box = QRadioButton("사각형")
        self._rb_cyl = QRadioButton("원형")
        self._rb_select.setChecked(True)
        self._tool_grp = QButtonGroup(self)
        for rb in (self._rb_select, self._rb_box, self._rb_cyl):
            self._tool_grp.addButton(rb)
            tool_row.addWidget(rb)
        v.addLayout(tool_row)

        layer_row = QHBoxLayout()
        self._spn_ly_top = dspin(0, 50, 0.5, 0.1, 2, " m")
        self._spn_ly_bot = dspin(0, 50, 1.0, 0.1, 2, " m")
        self._btn_add_layer = QPushButton("층 추가")
        layer_row.addWidget(QLabel("층:"))
        layer_row.addWidget(self._spn_ly_top)
        layer_row.addWidget(QLabel("~"))
        layer_row.addWidget(self._spn_ly_bot)
        layer_row.addWidget(self._btn_add_layer)
        v.addLayout(layer_row)

        self._lst_objects = QListWidget()
        self._lst_objects.setMaximumHeight(140)
        v.addWidget(self._lst_objects)
        self._btn_del = QPushButton("선택 객체 삭제")
        v.addWidget(self._btn_del)
        lay.addWidget(grp_obj)

        # --- 실행 ---
        grp_run = QGroupBox("시뮬레이션")
        v = QVBoxLayout(grp_run)
        eng_row = QFormLayout()
        self._cmb_engine = QComboBox()
        self._cmb_engine.addItem("gprMax (FDTD 정밀, 분 단위)", "fdtd")
        self._cmb_engine.addItem("레이트레이싱 (근사, 1초 미만)", "ray")
        eng_row.addRow("엔진:", self._cmb_engine)
        v.addLayout(eng_row)
        self._chk_multiples = QCheckBox("다중반사 (RR) 포함 — 레이트레이싱 전용")
        self._chk_multiples.setEnabled(False)
        v.addWidget(self._chk_multiples)
        self._lbl_info = QLabel("")
        self._lbl_info.setWordWrap(True)
        v.addWidget(self._lbl_info)
        self._btn_run = QPushButton("시뮬레이션 실행")
        self._btn_run.setStyleSheet("font-weight: bold; padding: 6px;")
        self._btn_cancel = QPushButton("취소")
        self._btn_cancel.setEnabled(False)
        run_row = QHBoxLayout()
        run_row.addWidget(self._btn_run, 1)
        run_row.addWidget(self._btn_cancel)
        v.addLayout(run_row)
        self._prg = QProgressBar()
        self._prg.setTextVisible(True)
        v.addWidget(self._prg)
        self._lbl_status = QLabel("대기")
        v.addWidget(self._lbl_status)
        lay.addWidget(grp_run)

        lay.addStretch(1)

        # 시그널 연결
        for s in (self._spn_width, self._spn_depth, self._spn_cell, self._spn_air,
                  self._spn_tw, self._spn_freq, self._spn_offset, self._spn_step,
                  self._spn_xs, self._spn_xe):
            s.valueChanged.connect(self._on_param_changed)
        self._chk_tw_auto.toggled.connect(self._on_tw_auto)
        self._chk_cell_auto.toggled.connect(self._on_cell_auto)
        self._chk_ant_auto.toggled.connect(self._on_ant_auto)
        self._cmb_bg.currentIndexChanged.connect(self._on_param_changed)
        self._btn_example.clicked.connect(self._on_example)
        self._btn_reset.clicked.connect(self._on_reset_model)
        self._rb_select.toggled.connect(lambda on: on and self._set_tool(
            "select", "선택 도구: 캔버스에서 객체를 클릭해 선택하고, [선택 객체 삭제]로 제거합니다"))
        self._rb_box.toggled.connect(lambda on: on and self._set_tool(
            "box", "사각형 도구: 캔버스에서 대각선으로 드래그하면 '그리기 재질'로 사각 객체가 배치됩니다"))
        self._rb_cyl.toggled.connect(lambda on: on and self._set_tool(
            "cylinder", "원형 도구: 중심에서 바깥으로 드래그하면 관로/공동 같은 원형 객체가 배치됩니다"))
        self._btn_add_layer.clicked.connect(self._on_add_layer)
        self._btn_del.clicked.connect(self._on_delete_object)
        self._lst_objects.currentRowChanged.connect(self._on_list_selected)
        self._btn_run.clicked.connect(self._on_run)
        self._btn_cancel.clicked.connect(self._on_cancel)
        self._cmb_engine.currentIndexChanged.connect(
            lambda _: self._chk_multiples.setEnabled(self._cmb_engine.currentData() == "ray"))
        return panel

    # ------------------------------------------------------------ 모델 동기화

    def _sync_panel_to_model(self):
        m = self._model
        m.width = self._spn_width.value()
        m.depth = self._spn_depth.value()
        m.cell = self._spn_cell.value()
        m.air_height = self._spn_air.value()
        m.time_window_ns = 0.0 if self._chk_tw_auto.isChecked() else self._spn_tw.value()
        m.background = self._cmb_bg.currentData()
        a = m.antenna
        a.freq_mhz = self._spn_freq.value()
        a.offset = self._spn_offset.value()
        a.step = self._spn_step.value()
        a.x_start = self._spn_xs.value()
        a.x_end = self._spn_xe.value()

    def _on_param_changed(self):
        self._sync_panel_to_model()
        self._apply_autos()
        self._canvas.redraw()
        self._refresh_info()

    def _apply_autos(self):
        """자동 체크된 항목(셀 크기/안테나 범위)을 모델+스핀박스에 반영."""
        m = self._model
        if self._chk_cell_auto.isChecked():
            m.cell = m.nice_cell()
            self._spn_cell.blockSignals(True)
            self._spn_cell.setValue(m.cell)
            self._spn_cell.blockSignals(False)
        if self._chk_ant_auto.isChecked():
            xs, xe = m.auto_antenna_range()
            m.antenna.x_start, m.antenna.x_end = xs, xe
            for spn, v in ((self._spn_xs, xs), (self._spn_xe, xe)):
                spn.blockSignals(True)
                spn.setValue(v)
                spn.blockSignals(False)

    def _on_tw_auto(self, checked):
        self._spn_tw.setEnabled(not checked)
        self._on_param_changed()

    def _on_cell_auto(self, checked):
        self._spn_cell.setEnabled(not checked)
        self._on_param_changed()

    def _on_ant_auto(self, checked):
        self._spn_xs.setEnabled(not checked)
        self._spn_xe.setEnabled(not checked)
        self._on_param_changed()

    def _set_tool(self, tool, hint):
        self._canvas.set_tool(tool)
        self.statusBar().showMessage(hint)

    def _refresh_info(self):
        m = self._model
        nx = int(m.width / m.cell)
        ny = int((m.depth + m.air_height) / m.cell)
        self._lbl_cell_hint.setText(f"권장 셀 ≤ {m.suggest_cell()*1000:.1f} mm (λmin/10)")
        self._lbl_info.setText(
            f"격자 {nx} x {ny} = {nx*ny:,} 셀\n"
            f"Trace 수: {m.n_traces()}  /  Time window: {m.effective_time_window_ns():.1f} ns")

    # ------------------------------------------------------------ 객체 편집

    def _refresh_object_list(self):
        self._lst_objects.clear()
        m = self._model
        for ly in m.layers:
            self._lst_objects.addItem(ly.label())
        for b in m.boxes:
            self._lst_objects.addItem(b.label())
        for c in m.cylinders:
            self._lst_objects.addItem(c.label())

    def _row_to_ref(self, row):
        """리스트 행 번호 → (kind, index)."""
        m = self._model
        if row < 0:
            return None
        if row < len(m.layers):
            return ("layer", row)
        row -= len(m.layers)
        if row < len(m.boxes):
            return ("box", row)
        row -= len(m.boxes)
        if row < len(m.cylinders):
            return ("cyl", row)
        return None

    def _on_box_drawn(self, x1, d1, x2, d2):
        self._model.boxes.append(BoxObject(x1, d1, x2, d2, self._cmb_mat.currentData()))
        self._after_object_change()

    def _on_cyl_drawn(self, x, d, r):
        self._model.cylinders.append(CylinderObject(x, d, r, self._cmb_mat.currentData()))
        self._after_object_change()

    def _on_add_layer(self):
        top, bot = self._spn_ly_top.value(), self._spn_ly_bot.value()
        if bot <= top:
            kr_warn(self, "층 추가", "하단 깊이는 상단 깊이보다 커야 합니다.")
            return
        self._model.layers.append(LayerObject(top, bot, self._cmb_mat.currentData()))
        self._after_object_change()

    def _after_object_change(self):
        self._refresh_object_list()
        self._apply_autos()      # 객체 재질이 최대 εr(권장 셀/TW)에 영향
        self._canvas.redraw()
        self._refresh_info()

    def _on_example(self):
        """원클릭 예제: 관로 + 공동 + 하부 지층."""
        mats = {mm.name: mm for mm in MATERIAL_PRESETS}
        for spn, v in ((self._spn_width, 6.0), (self._spn_depth, 2.5),
                       (self._spn_freq, 400), (self._spn_step, 0.1),
                       (self._spn_offset, 0.1), (self._spn_air, 0.2)):
            spn.blockSignals(True)
            spn.setValue(v)
            spn.blockSignals(False)
        self._cmb_bg.blockSignals(True)
        self._cmb_bg.setCurrentIndex(1)  # 건조 모래
        self._cmb_bg.blockSignals(False)
        m = self._model
        m.layers.clear()
        m.boxes.clear()
        m.cylinders.clear()
        m.layers.append(LayerObject(1.6, 2.5, mats["석회암"]))
        m.cylinders.append(CylinderObject(1.5, 0.6, 0.10, mats["금속 (PEC)"]))
        m.cylinders.append(CylinderObject(3.0, 0.9, 0.15, mats["공기"]))
        m.boxes.append(BoxObject(4.2, 0.4, 4.8, 1.0, mats["콘크리트"]))
        self._selected = None
        self._canvas.set_selected("", -1)
        self._sync_panel_to_model()
        self._apply_autos()
        self._refresh_object_list()
        self._canvas.redraw()
        self._refresh_info()
        self.statusBar().showMessage(
            "예제 모델 로드 완료 (금속관/공동/콘크리트/하부암반). [시뮬레이션 실행]을 눌러 보세요")

    def _on_reset_model(self):
        m = self._model
        if (m.layers or m.boxes or m.cylinders) and not kr_question(
                self, "모델 초기화", "배치된 객체를 모두 삭제할까요?"):
            return
        m.layers.clear()
        m.boxes.clear()
        m.cylinders.clear()
        self._selected = None
        self._canvas.set_selected("", -1)
        self._after_object_change()

    def _on_object_clicked(self, kind, index):
        self._selected = (kind, index) if kind else None
        self._canvas.set_selected(kind, index)
        if kind:
            m = self._model
            row = index
            if kind == "box":
                row = len(m.layers) + index
            elif kind == "cyl":
                row = len(m.layers) + len(m.boxes) + index
            self._lst_objects.setCurrentRow(row)

    def _on_list_selected(self, row):
        ref = self._row_to_ref(row)
        if ref:
            self._selected = ref
            self._canvas.set_selected(*ref)

    def _on_delete_object(self):
        ref = self._row_to_ref(self._lst_objects.currentRow())
        if ref is None:
            return
        kind, idx = ref
        m = self._model
        if kind == "layer":
            del m.layers[idx]
        elif kind == "box":
            del m.boxes[idx]
        else:
            del m.cylinders[idx]
        self._selected = None
        self._canvas.set_selected("", -1)
        self._after_object_change()

    # ------------------------------------------------------------ 시뮬레이션

    def _on_run(self):
        self._sync_panel_to_model()
        errs = self._model.validate()
        if errs:
            kr_warn(self, "모델 검증", "\n".join(errs))
            return
        n = self._model.n_traces()

        # ---- 레이트레이싱 엔진: 즉시 계산 ----
        if self._cmb_engine.currentData() == "ray":
            from engine.raytrace import simulate_raytrace
            data, dt = simulate_raytrace(self._model,
                                         include_multiples=self._chk_multiples.isChecked())
            a = self._model.antenna
            self._bscan.set_data(data, dt, a.x_start + a.offset / 2.0, a.step,
                                 self._model.background.epsilon_r)
            self._tabs.setCurrentWidget(self._bscan)
            self._prg.setRange(0, 1)
            self._prg.setValue(1)
            self._lbl_status.setText("완료 (레이트레이싱)")
            return
        nx = int(self._model.width / self._model.cell)
        ny = int((self._model.depth + self._model.air_height) / self._model.cell)
        if nx * ny * n > 50_000_000:  # 대략적 경고 기준
            if not kr_question(
                    self, "대형 모델",
                    f"격자 {nx*ny:,} 셀 x {n} traces: 계산이 오래 걸릴 수 있습니다.\n계속할까요?"):
                return

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        in_path = os.path.join(OUTPUT_DIR, "grsim_model.in")
        write_input_file(self._model, in_path, title="G_RSim model")
        cleanup_outputs(in_path, n)

        self._btn_run.setEnabled(False)
        self._btn_cancel.setEnabled(True)
        self._prg.setRange(0, n)
        self._prg.setValue(0)
        self._t_run_start = time.time()
        self._lbl_status.setText(f"실행 중... (0/{n})")

        self._thread = SimThread(in_path, n, self)
        self._thread.progress.connect(self._on_progress)
        self._thread.done.connect(self._on_done)
        self._thread.start()

    def _on_progress(self, cur, total):
        self._prg.setValue(cur)
        txt = f"실행 중... ({cur}/{total})"
        if cur >= 1:
            elapsed = time.time() - self._t_run_start
            remain = int(elapsed / cur * (total - cur))
            txt += f"  남은 약 {remain // 60}분 {remain % 60:02d}초"
        self._lbl_status.setText(txt)

    def _on_cancel(self):
        if self._thread is not None:
            self._thread.cancel()
            self._lbl_status.setText("취소 요청...")

    def _on_done(self, ok, msg):
        self._btn_run.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._lbl_status.setText(msg)
        if not ok:
            if msg != "취소됨":
                kr_warn(self, "시뮬레이션", msg)
            return
        in_path = os.path.join(OUTPUT_DIR, "grsim_model.in")
        n = self._model.n_traces()
        try:
            data, dt = read_bscan(in_path, n)
        except Exception as exc:  # noqa: BLE001
            kr_warn(self, "결과 읽기 실패", str(exc))
            return
        a = self._model.antenna
        mid_start = a.x_start + a.offset / 2.0
        self._bscan.set_data(data, dt, mid_start, a.step, self._model.background.epsilon_r)
        self._tabs.setCurrentWidget(self._bscan)
        self._prg.setValue(self._prg.maximum())
        kr_info(self, "시뮬레이션", f"완료: {n} traces")
