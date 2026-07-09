# -*- coding: utf-8 -*-
"""G_RSim 앱 엔트리포인트."""

import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from config import FONT_FAMILY


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont(FONT_FAMILY, 10))
    from gui.main_window import MainWindow
    win = MainWindow()
    win.showMaximized()
    run_loop = getattr(app, "exec")
    sys.exit(run_loop())


if __name__ == "__main__":
    main()
