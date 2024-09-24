# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'JsonToDataaCXVJY.ui'
##
## Created by: Qt User Interface Compiler version 5.14.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide2.QtCore import (QCoreApplication, QMetaObject, QObject, QPoint,
    QRect, QSize, QUrl, Qt)
from PySide2.QtGui import (QBrush, QColor, QConicalGradient, QCursor, QFont,
    QFontDatabase, QIcon, QLinearGradient, QPalette, QPainter, QPixmap,
    QRadialGradient)
from PySide2.QtWidgets import *


class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(1006, 320)
        sizePolicy = QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(MainWindow.sizePolicy().hasHeightForWidth())
        MainWindow.setSizePolicy(sizePolicy)
        MainWindow.setMinimumSize(QSize(1006, 320))
        MainWindow.setMaximumSize(QSize(1006, 320))
        MainWindow.setAutoFillBackground(False)
        MainWindow.setStyleSheet(u"")
        self.actionAbout_this_tool = QAction(MainWindow)
        self.actionAbout_this_tool.setObjectName(u"actionAbout_this_tool")
        self.actionAbout_this_tool.setShortcutContext(Qt.WindowShortcut)
        self.actionAbout_this_tool.setVisible(True)
        self.actionAbout_this_tool.setMenuRole(QAction.NoRole)
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.centralwidget.setMinimumSize(QSize(1005, 299))
        self.centralwidget.setMaximumSize(QSize(1005, 299))
        self.centralwidget.setStyleSheet(u"")
        self.horizontalGroupBox = QGroupBox(self.centralwidget)
        self.horizontalGroupBox.setObjectName(u"horizontalGroupBox")
        self.horizontalGroupBox.setGeometry(QRect(10, 10, 311, 91))
        self.horizontalGroupBox.setCursor(QCursor(Qt.ArrowCursor))
        self.horizontalGroupBox.setAutoFillBackground(False)
        self.horizontalGroupBox.setStyleSheet(u"QGroupBox {\n"
"    border: 2px solid black;\n"
"    border-radius: 5px;\n"
"    margin-top: 1ex; /* leave space at the top for the title */\n"
"}\n"
"\n"
"QGroupBox::title {\n"
"    subcontrol-origin: margin;\n"
"    left: 10px;\n"
"    padding: 0 3px 0 3px;\n"
"}")
        self.horizontalLayout = QHBoxLayout(self.horizontalGroupBox)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.option_two = QRadioButton(self.horizontalGroupBox)
        self.option_two.setObjectName(u"option_two")
        sizePolicy1 = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.option_two.sizePolicy().hasHeightForWidth())
        self.option_two.setSizePolicy(sizePolicy1)
        self.option_two.setChecked(True)

        self.horizontalLayout.addWidget(self.option_two)

        self.option_one = QRadioButton(self.horizontalGroupBox)
        self.option_one.setObjectName(u"option_one")
        sizePolicy1.setHeightForWidth(self.option_one.sizePolicy().hasHeightForWidth())
        self.option_one.setSizePolicy(sizePolicy1)
        self.option_one.setStyleSheet(u"")
        self.option_one.setChecked(False)

        self.horizontalLayout.addWidget(self.option_one)

        self.pushButton = QPushButton(self.centralwidget)
        self.pushButton.setObjectName(u"pushButton")
        self.pushButton.setGeometry(QRect(10, 250, 501, 31))
        self.layoutWidget = QWidget(self.centralwidget)
        self.layoutWidget.setObjectName(u"layoutWidget")
        self.layoutWidget.setGeometry(QRect(340, 10, 651, 91))
        self.gridLayout = QGridLayout(self.layoutWidget)
        self.gridLayout.setSpacing(0)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.horizontalWidget_2 = QWidget(self.layoutWidget)
        self.horizontalWidget_2.setObjectName(u"horizontalWidget_2")
        self.horizontalWidget_2.setStyleSheet(u"QWidget{\n"
"   	border: 1px solid black;\n"
"}")
        self.horizontalLayout_2 = QHBoxLayout(self.horizontalWidget_2)
        self.horizontalLayout_2.setSpacing(0)
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.horizontalLayout_2.setContentsMargins(0, 0, 0, 0)
        self.label_9 = QLabel(self.horizontalWidget_2)
        self.label_9.setObjectName(u"label_9")
        self.label_9.setStyleSheet(u"")
        self.label_9.setAlignment(Qt.AlignCenter)

        self.horizontalLayout_2.addWidget(self.label_9)

        self.label_7 = QLabel(self.horizontalWidget_2)
        self.label_7.setObjectName(u"label_7")
        self.label_7.setStyleSheet(u"")
        self.label_7.setAlignment(Qt.AlignCenter)

        self.horizontalLayout_2.addWidget(self.label_7)

        self.label_8 = QLabel(self.horizontalWidget_2)
        self.label_8.setObjectName(u"label_8")
        self.label_8.setStyleSheet(u"")
        self.label_8.setAlignment(Qt.AlignCenter)

        self.horizontalLayout_2.addWidget(self.label_8)

        self.label_10 = QLabel(self.horizontalWidget_2)
        self.label_10.setObjectName(u"label_10")
        self.label_10.setStyleSheet(u"")
        self.label_10.setAlignment(Qt.AlignCenter)

        self.horizontalLayout_2.addWidget(self.label_10)

        self.label_6 = QLabel(self.horizontalWidget_2)
        self.label_6.setObjectName(u"label_6")
        self.label_6.setStyleSheet(u"")
        self.label_6.setAlignment(Qt.AlignCenter)

        self.horizontalLayout_2.addWidget(self.label_6)


        self.gridLayout.addWidget(self.horizontalWidget_2, 1, 0, 1, 1)

        self.horizontalWidget_3 = QWidget(self.layoutWidget)
        self.horizontalWidget_3.setObjectName(u"horizontalWidget_3")
        self.horizontalWidget_3.setStyleSheet(u"QWidget{\n"
"   	border: 1px solid black;\n"
"}")
        self.horizontalLayout_3 = QHBoxLayout(self.horizontalWidget_3)
        self.horizontalLayout_3.setSpacing(0)
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.horizontalLayout_3.setContentsMargins(0, 0, 0, 0)
        self.single_case = QLabel(self.horizontalWidget_3)
        self.single_case.setObjectName(u"single_case")
        self.single_case.setEnabled(True)
        self.single_case.setAlignment(Qt.AlignCenter)

        self.horizontalLayout_3.addWidget(self.single_case)

        self.split_case = QLabel(self.horizontalWidget_3)
        self.split_case.setObjectName(u"split_case")
        self.split_case.setAlignment(Qt.AlignCenter)

        self.horizontalLayout_3.addWidget(self.split_case)

        self.split_manual_case = QLabel(self.horizontalWidget_3)
        self.split_manual_case.setObjectName(u"split_manual_case")
        self.split_manual_case.setAlignment(Qt.AlignCenter)

        self.horizontalLayout_3.addWidget(self.split_manual_case)

        self.group_case = QLabel(self.horizontalWidget_3)
        self.group_case.setObjectName(u"group_case")
        self.group_case.setAlignment(Qt.AlignCenter)

        self.horizontalLayout_3.addWidget(self.group_case)

        self.supple_case = QLabel(self.horizontalWidget_3)
        self.supple_case.setObjectName(u"supple_case")
        self.supple_case.setAlignment(Qt.AlignCenter)

        self.horizontalLayout_3.addWidget(self.supple_case)


        self.gridLayout.addWidget(self.horizontalWidget_3, 0, 0, 1, 1)

        self.statusText = QLabel(self.centralwidget)
        self.statusText.setObjectName(u"statusText")
        self.statusText.setGeometry(QRect(20, 120, 971, 121))
        self.statusText.setMaximumSize(QSize(1000, 1000))
        font = QFont()
        font.setPointSize(16)
        self.statusText.setFont(font)
        self.statusText.setScaledContents(False)
        self.statusText.setAlignment(Qt.AlignLeading|Qt.AlignLeft|Qt.AlignTop)
        self.statusText.setWordWrap(True)
        self.statusText.setIndent(-1)
        self.processButton = QPushButton(self.centralwidget)
        self.processButton.setObjectName(u"processButton")
        self.processButton.setGeometry(QRect(530, 250, 461, 31))
        MainWindow.setCentralWidget(self.centralwidget)
        self.menubar = QMenuBar(MainWindow)
        self.menubar.setObjectName(u"menubar")
        self.menubar.setGeometry(QRect(0, 0, 1006, 21))
        self.menuInfo = QMenu(self.menubar)
        self.menuInfo.setObjectName(u"menuInfo")
        MainWindow.setMenuBar(self.menubar)

        self.menubar.addAction(self.menuInfo.menuAction())
        self.menuInfo.addAction(self.actionAbout_this_tool)

        self.retranslateUi(MainWindow)

        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"MainWindow", None))
        self.actionAbout_this_tool.setText(QCoreApplication.translate("MainWindow", u"About this tool", None))
#if QT_CONFIG(whatsthis)
        self.horizontalGroupBox.setWhatsThis("")
#endif // QT_CONFIG(whatsthis)
        self.horizontalGroupBox.setTitle(QCoreApplication.translate("MainWindow", u"Option save:", None))
        self.option_two.setText(QCoreApplication.translate("MainWindow", u"Save", None))
        self.option_one.setText(QCoreApplication.translate("MainWindow", u"Save and replace", None))
        self.pushButton.setText(QCoreApplication.translate("MainWindow", u"Read Json", None))
        self.label_9.setText(QCoreApplication.translate("MainWindow", u"0", None))
        self.label_7.setText(QCoreApplication.translate("MainWindow", u"0", None))
        self.label_8.setText(QCoreApplication.translate("MainWindow", u"0", None))
        self.label_10.setText(QCoreApplication.translate("MainWindow", u"0", None))
        self.label_6.setText(QCoreApplication.translate("MainWindow", u"0", None))
        self.single_case.setText(QCoreApplication.translate("MainWindow", u"Single Case", None))
        self.split_case.setText(QCoreApplication.translate("MainWindow", u"Split", None))
        self.split_manual_case.setText(QCoreApplication.translate("MainWindow", u"Split Manual Case", None))
        self.group_case.setText(QCoreApplication.translate("MainWindow", u"Group Case", None))
        self.supple_case.setText(QCoreApplication.translate("MainWindow", u"Supplement", None))
        self.statusText.setText(QCoreApplication.translate("MainWindow", u"TextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTex"
                        "tLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelabelTextLabelTextLabelTextLabelTextLabelTextLabel", None))
        self.processButton.setText(QCoreApplication.translate("MainWindow", u"Process", None))
        self.menuInfo.setTitle(QCoreApplication.translate("MainWindow", u"Info", None))
    # retranslateUi

