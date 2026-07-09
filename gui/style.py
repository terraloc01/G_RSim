# -*- coding: utf-8 -*-
"""G-시리즈 공통 스타일 (G_UI_Catalog_v01 기준)."""

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QMessageBox

from config import FONT_FAMILY

GLOBAL_QSS = """
QMainWindow { background-color: #f0f0f0; }
QGroupBox {
    background-color: #ffffff;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
    margin-top: 10px;
    padding: 6px;
    font-weight: bold;
    font-size: 12px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0 4px;
    background-color: #ffffff;
    color: #0096c8;
}
QPushButton {
    background-color: #ffffff;
    border: 1px solid #c0c0c0;
    border-radius: 3px;
    padding: 4px 10px;
    font-size: 12px;
}
QPushButton:hover { background-color: #e8e8e8; border-color: #0078d4; }
QPushButton:pressed { background-color: #d0d0d0; }
QLabel, QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit { font-size: 12px; }
QTableWidget {
    background-color: #ffffff;
    gridline-color: #e0e0e0;
    border: 1px solid #d0d0d0;
    font-size: 12px;
}
QTableWidget::item:selected { background-color: #0078d4; color: white; }
QHeaderView::section {
    background-color: #f5f5f5;
    padding: 4px;
    border: 1px solid #e0e0e0;
    font-weight: bold;
    font-size: 12px;
}
QListWidget {
    background-color: #ffffff;
    border: 1px solid #d0d0d0;
    font-size: 12px;
}
"""


def _kr_buttons(box: QMessageBox) -> None:
    """표준 버튼 한글화."""
    mapping = {
        QMessageBox.StandardButton.Yes: "예",
        QMessageBox.StandardButton.No: "아니오",
        QMessageBox.StandardButton.Ok: "확인",
        QMessageBox.StandardButton.Cancel: "취소",
    }
    for std, kr in mapping.items():
        btn = box.button(std)
        if btn:
            btn.setText(kr)


def _make_box(icon, parent, title, text, buttons) -> QMessageBox:
    box = QMessageBox(icon, title, text, buttons, parent)
    box.setFont(QFont(FONT_FAMILY, 10))
    _kr_buttons(box)
    return box


def kr_info(parent, title, text) -> None:
    box = _make_box(QMessageBox.Icon.Information, parent, title, text,
                    QMessageBox.StandardButton.Ok)
    show_modal = getattr(box, "exec")
    show_modal()


def kr_warn(parent, title, text) -> None:
    box = _make_box(QMessageBox.Icon.Warning, parent, title, text,
                    QMessageBox.StandardButton.Ok)
    show_modal = getattr(box, "exec")
    show_modal()


def kr_question(parent, title, text) -> bool:
    box = _make_box(QMessageBox.Icon.Question, parent, title, text,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    show_modal = getattr(box, "exec")
    return show_modal() == QMessageBox.StandardButton.Yes
