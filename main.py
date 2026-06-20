# -*- coding: utf-8 -*-
import sys
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QAction
from PyQt5.QtGui import QIcon, QPixmap, QColor
from ui_components import ControlPanel

class App:
    def __init__(self):
        self.qapp = QApplication(sys.argv)
        self.qapp.setStyle("Fusion")
        
        # Icon ve Tray
        px = QPixmap(32, 32)
        px.fill(QColor("#58a6ff"))
        icon = QIcon(px)
        self.qapp.setWindowIcon(icon)
        
        self.panel = ControlPanel()
        
        self.tray = QSystemTrayIcon(icon, self.qapp)
        menu = QMenu()
        show = QAction("Paneli Goster", menu)
        show.triggered.connect(lambda: self.panel.show() or self.panel.raise_())
        quit_action = QAction("Cikis", menu)
        quit_action.triggered.connect(self.qapp.quit)
        menu.addAction(show)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.show()
        
        self.panel.show()

    def run(self):
        sys.exit(self.qapp.exec_())

if __name__ == "__main__":
    # Windows High DPI ayari
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
        
    app = App()
    app.run()
