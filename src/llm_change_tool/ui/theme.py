"""Consistent light desktop palette, independent of the OS dark-mode palette."""

from importlib.resources import files

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

STYLE = """
QWidget { font-family: 'Malgun Gothic', 'NanumGothic', 'Noto Sans CJK KR', 'Segoe UI', sans-serif;
    font-size: 14px; color: #243746; }
QMainWindow, QWidget#workspace, QScrollArea, QScrollArea > QWidget > QWidget { background: #f3f6f8; }
QLabel { background: transparent; }
QLabel#pageTitle { font-size: 26px; font-weight: 700; color: #142c3c; }
QLabel#sectionTitle { font-size: 17px; font-weight: 700; color: #183648; }
QLabel#muted { color: #526777; }
QLabel#eyebrow { color: #176a67; font-size: 11px; font-weight: 700; }
QLabel#reviewSummary { color: #176a67; font-size: 14px; font-weight: 600; }
QLabel#badge { color: #12605d; background: #e0f2ed; border-radius: 6px; padding: 7px 12px; }
QLabel#metricValue { font-size: 27px; font-weight: 700; color: #133d45; }
QFrame#card { background: #ffffff; border: 1px solid #dce5eb; border-radius: 12px; }
QFrame#sidebar { background: #142d3d; border: none; }
QFrame#sidebar QLabel { color: #c5d5df; }
QFrame#sidebar QLabel#brand { color: white; font-size: 22px; font-weight: 700; }
QFrame#sidebar QLabel#navSection { color: #a3bdcb; font-size: 11px; font-weight: 700; }
QPushButton { background: #ffffff; border: 1px solid #b7c8d3; border-radius: 7px;
    padding: 8px 14px; min-height: 22px; color: #244354; font-weight: 500; }
QPushButton:hover { background: #edf6f5; border-color: #65978f; }
QPushButton:pressed { background: #d6eae6; }
QPushButton:focus, QComboBox:focus, QLineEdit:focus, QTextEdit:focus, QDoubleSpinBox:focus {
    border: 2px solid #268a85; }
QPushButton:disabled { background: #f1f4f6; border-color: #dde5ea; color: #8797a2; }
QPushButton[role="primary"] { background: #126b65; border-color: #126b65; color: #ffffff; font-weight: 700; }
QPushButton[role="primary"]:hover { background: #09564f; border-color: #09564f; }
QPushButton[role="primary"]:disabled { background: #b4ceca; border-color: #b4ceca; color: #f8fbfa; }
QPushButton[role="danger"] { color: #a43232; border-color: #dcb6b6; }
QPushButton[role="link"] { border: none; background: transparent; color: #176a67; padding: 6px 0; text-align: left; }
QPushButton[role="nav"] { background: transparent; color: #c5d5df; border: 1px solid transparent;
    text-align: left; padding: 12px 14px; min-height: 24px; border-radius: 8px; }
QPushButton[role="nav"]:hover { background: #213e4f; color: #ffffff; }
QPushButton[role="nav"]:checked { background: #275464; color: #ffffff; border-color: #426f7e; font-weight: 700; }
QPushButton[role="nav"]:focus { border: 2px solid #8ad4cd; }
QTabWidget::pane { border: none; background: transparent; }
QLineEdit, QComboBox, QDoubleSpinBox, QTextEdit { background: #ffffff; border: 1px solid #bccbd6;
    border-radius: 6px; padding: 7px 10px; selection-background-color: #c5e8e2; selection-color: #123b39; }
QLineEdit, QComboBox, QDoubleSpinBox { min-height: 22px; }
QLineEdit:disabled, QDoubleSpinBox:disabled, QComboBox:disabled { background: #f0f3f5; color: #84939d; }
QComboBox { padding-right: 25px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 24px; border: none; }
QComboBox::down-arrow { image: url("__CHEVRON__"); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: white; color: #243746; selection-background-color: #dcedea; selection-color: #143b38; padding: 5px; }
QCheckBox { spacing: 10px; min-height: 28px; }
QCheckBox::indicator { width: 21px; height: 21px; background: #ffffff;
    border: 2px solid #708795; border-radius: 5px; }
QCheckBox::indicator:hover { border-color: #268a85; background: #edf6f5; }
QCheckBox::indicator:checked { background: #126b65; border-color: #126b65; image: url("__CHECKMARK__"); }
QCheckBox:focus { color: #126b65; }
QCheckBox[attention="true"] { color: #9b3036; background: #ffedf0;
    border: 1px solid #d87d84; border-radius: 7px; padding: 8px 10px; font-weight: 700; }
QLineEdit[attention="true"] { border: 2px solid #c94e58; background: #fff5f6; }
QProgressBar { border: none; background: #e4ecef; border-radius: 4px; height: 8px; max-height: 8px; }
QProgressBar::chunk { background: #218779; border-radius: 4px; }
QTableWidget { border: 1px solid #dce5eb; border-radius: 7px; background: #ffffff;
    alternate-background-color: #f6f9fa; gridline-color: #edf1f4; selection-background-color: #e0f0ec; selection-color: #163d37; }
QTableWidget::item { padding: 6px; }
QHeaderView::section { background: #edf3f6; color: #405b6d; font-weight: 700;
    border: none; border-bottom: 1px solid #dce5eb; padding: 9px 6px; }
QSplitter::handle { background: #dce5eb; width: 5px; }
QScrollArea { border: none; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #bacbd4; border-radius: 5px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QToolTip { background: #173545; color: white; border: none; padding: 7px; }
QLabel[tone="success"] { color: #146147; background: #e7f5ed; border-radius: 7px; padding: 12px; }
QLabel[tone="warning"] { color: #845114; background: #fff4dc; border-radius: 7px; padding: 12px; }
QLabel[tone="error"] { color: #9b3036; background: #ffedf0; border-radius: 7px; padding: 12px; }
QLabel[tone="info"] { color: #30576d; background: #eaf2f7; border-radius: 7px; padding: 12px; }
QGraphicsView#imageCanvas { background: #1c303b; border: 1px solid #354e5d; border-radius: 8px; }
"""


def apply_theme():
    app = QApplication.instance()
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: "#f3f6f8",
        QPalette.ColorRole.WindowText: "#243746",
        QPalette.ColorRole.Base: "#ffffff",
        QPalette.ColorRole.AlternateBase: "#f6f9fa",
        QPalette.ColorRole.Text: "#243746",
        QPalette.ColorRole.Button: "#ffffff",
        QPalette.ColorRole.ButtonText: "#243746",
        QPalette.ColorRole.Highlight: "#c5e8e2",
        QPalette.ColorRole.HighlightedText: "#123b39",
        QPalette.ColorRole.PlaceholderText: "#687d8a",
    }.items():
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    font = QFont()
    font.setFamilies(["Malgun Gothic", "NanumGothic", "Noto Sans CJK KR", "Segoe UI"])
    font.setPointSize(10)
    app.setFont(font)
    chevron = files("llm_change_tool").joinpath("resources/ui/chevron-down.svg")
    checkmark = files("llm_change_tool").joinpath("resources/ui/checkmark.svg")
    app.setStyleSheet(
        STYLE.replace("__CHEVRON__", str(chevron).replace("\\", "/")).replace(
            "__CHECKMARK__", str(checkmark).replace("\\", "/")
        )
    )
