from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QComboBox, QCheckBox, QSlider, QSpinBox, QPushButton
from PyQt5.QtCore import Qt
import sys

app = QApplication(sys.argv)

from src.gui.npu_theme import STYLESHEET

w = QWidget()
w.setStyleSheet(STYLESHEET)
layout = QVBoxLayout(w)

cb = QComboBox()
cb.addItems(["A", "B"])
layout.addWidget(cb)

chk = QCheckBox("Check me")
layout.addWidget(chk)

slider = QSlider(Qt.Horizontal)
layout.addWidget(slider)

spin = QSpinBox()
layout.addWidget(spin)

btn = QPushButton("Button")
layout.addWidget(btn)

w.show()
sys.exit(app.exec_())
