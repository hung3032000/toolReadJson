# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'JsonToData.ui'
#
# Created by: PyQt5 UI code generator 5.15.9
#
# WARNING: Any manual changes made to this file will be lost when pyuic5 is
# run again.  Do not edit this file unless you know what you are doing.


from PyQt5 import QtCore, QtGui, QtWidgets


class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        MainWindow.setObjectName("MainWindow")
        MainWindow.resize(1006, 320)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(MainWindow.sizePolicy().hasHeightForWidth())
        MainWindow.setSizePolicy(sizePolicy)
        MainWindow.setMinimumSize(QtCore.QSize(1006, 320))
        MainWindow.setMaximumSize(QtCore.QSize(1006, 320))
        MainWindow.setAutoFillBackground(False)
        MainWindow.setStyleSheet("")
        self.centralwidget = QtWidgets.QWidget(MainWindow)
        self.centralwidget.setMinimumSize(QtCore.QSize(1005, 299))
        self.centralwidget.setMaximumSize(QtCore.QSize(1005, 299))
        self.centralwidget.setStyleSheet("")
        self.centralwidget.setObjectName("centralwidget")
        self.horizontalGroupBox = QtWidgets.QGroupBox(self.centralwidget)
        self.horizontalGroupBox.setGeometry(QtCore.QRect(10, 10, 311, 91))
        self.horizontalGroupBox.setCursor(QtGui.QCursor(QtCore.Qt.ArrowCursor))
        self.horizontalGroupBox.setWhatsThis("")
        self.horizontalGroupBox.setAutoFillBackground(False)
        self.horizontalGroupBox.setStyleSheet("QGroupBox {\n"
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
        self.horizontalGroupBox.setObjectName("horizontalGroupBox")
        self.horizontalLayout = QtWidgets.QHBoxLayout(self.horizontalGroupBox)
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.option_two = QtWidgets.QRadioButton(self.horizontalGroupBox)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.option_two.sizePolicy().hasHeightForWidth())
        self.option_two.setSizePolicy(sizePolicy)
        self.option_two.setChecked(True)
        self.option_two.setObjectName("option_two")
        self.horizontalLayout.addWidget(self.option_two)
        self.option_one = QtWidgets.QRadioButton(self.horizontalGroupBox)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.option_one.sizePolicy().hasHeightForWidth())
        self.option_one.setSizePolicy(sizePolicy)
        self.option_one.setStyleSheet("")
        self.option_one.setChecked(False)
        self.option_one.setObjectName("option_one")
        self.horizontalLayout.addWidget(self.option_one)
        self.pushButton = QtWidgets.QPushButton(self.centralwidget)
        self.pushButton.setGeometry(QtCore.QRect(10, 250, 981, 31))
        self.pushButton.setObjectName("pushButton")
        self.layoutWidget = QtWidgets.QWidget(self.centralwidget)
        self.layoutWidget.setGeometry(QtCore.QRect(340, 10, 651, 91))
        self.layoutWidget.setObjectName("layoutWidget")
        self.gridLayout = QtWidgets.QGridLayout(self.layoutWidget)
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.gridLayout.setSpacing(0)
        self.gridLayout.setObjectName("gridLayout")
        self.horizontalWidget_2 = QtWidgets.QWidget(self.layoutWidget)
        self.horizontalWidget_2.setStyleSheet("QWidget{\n"
"       border: 1px solid black;\n"
"}")
        self.horizontalWidget_2.setObjectName("horizontalWidget_2")
        self.horizontalLayout_2 = QtWidgets.QHBoxLayout(self.horizontalWidget_2)
        self.horizontalLayout_2.setContentsMargins(0, 0, 0, 0)
        self.horizontalLayout_2.setSpacing(0)
        self.horizontalLayout_2.setObjectName("horizontalLayout_2")
        self.label_9 = QtWidgets.QLabel(self.horizontalWidget_2)
        self.label_9.setStyleSheet("")
        self.label_9.setAlignment(QtCore.Qt.AlignCenter)
        self.label_9.setObjectName("label_9")
        self.horizontalLayout_2.addWidget(self.label_9)
        self.label_7 = QtWidgets.QLabel(self.horizontalWidget_2)
        self.label_7.setStyleSheet("")
        self.label_7.setAlignment(QtCore.Qt.AlignCenter)
        self.label_7.setObjectName("label_7")
        self.horizontalLayout_2.addWidget(self.label_7)
        self.label_8 = QtWidgets.QLabel(self.horizontalWidget_2)
        self.label_8.setStyleSheet("")
        self.label_8.setAlignment(QtCore.Qt.AlignCenter)
        self.label_8.setObjectName("label_8")
        self.horizontalLayout_2.addWidget(self.label_8)
        self.label_10 = QtWidgets.QLabel(self.horizontalWidget_2)
        self.label_10.setStyleSheet("")
        self.label_10.setAlignment(QtCore.Qt.AlignCenter)
        self.label_10.setObjectName("label_10")
        self.horizontalLayout_2.addWidget(self.label_10)
        self.label_6 = QtWidgets.QLabel(self.horizontalWidget_2)
        self.label_6.setStyleSheet("")
        self.label_6.setAlignment(QtCore.Qt.AlignCenter)
        self.label_6.setObjectName("label_6")
        self.horizontalLayout_2.addWidget(self.label_6)
        self.gridLayout.addWidget(self.horizontalWidget_2, 1, 0, 1, 1)
        self.horizontalWidget_3 = QtWidgets.QWidget(self.layoutWidget)
        self.horizontalWidget_3.setStyleSheet("QWidget{\n"
"       border: 1px solid black;\n"
"}")
        self.horizontalWidget_3.setObjectName("horizontalWidget_3")
        self.horizontalLayout_3 = QtWidgets.QHBoxLayout(self.horizontalWidget_3)
        self.horizontalLayout_3.setContentsMargins(0, 0, 0, 0)
        self.horizontalLayout_3.setSpacing(0)
        self.horizontalLayout_3.setObjectName("horizontalLayout_3")
        self.single_case = QtWidgets.QLabel(self.horizontalWidget_3)
        self.single_case.setEnabled(True)
        self.single_case.setAlignment(QtCore.Qt.AlignCenter)
        self.single_case.setObjectName("single_case")
        self.horizontalLayout_3.addWidget(self.single_case)
        self.split_case = QtWidgets.QLabel(self.horizontalWidget_3)
        self.split_case.setAlignment(QtCore.Qt.AlignCenter)
        self.split_case.setObjectName("split_case")
        self.horizontalLayout_3.addWidget(self.split_case)
        self.split_manual_case = QtWidgets.QLabel(self.horizontalWidget_3)
        self.split_manual_case.setAlignment(QtCore.Qt.AlignCenter)
        self.split_manual_case.setObjectName("split_manual_case")
        self.horizontalLayout_3.addWidget(self.split_manual_case)
        self.group_case = QtWidgets.QLabel(self.horizontalWidget_3)
        self.group_case.setAlignment(QtCore.Qt.AlignCenter)
        self.group_case.setObjectName("group_case")
        self.horizontalLayout_3.addWidget(self.group_case)
        self.supple_case = QtWidgets.QLabel(self.horizontalWidget_3)
        self.supple_case.setAlignment(QtCore.Qt.AlignCenter)
        self.supple_case.setObjectName("supple_case")
        self.horizontalLayout_3.addWidget(self.supple_case)
        self.gridLayout.addWidget(self.horizontalWidget_3, 0, 0, 1, 1)
        self.statusText = QtWidgets.QLabel(self.centralwidget)
        self.statusText.setGeometry(QtCore.QRect(20, 120, 971, 121))
        self.statusText.setMaximumSize(QtCore.QSize(1000, 1000))
        font = QtGui.QFont()
        font.setPointSize(13)
        self.statusText.setFont(font)
        self.statusText.setScaledContents(False)
        self.statusText.setAlignment(QtCore.Qt.AlignLeading|QtCore.Qt.AlignLeft|QtCore.Qt.AlignTop)
        self.statusText.setWordWrap(True)
        self.statusText.setIndent(-1)
        self.statusText.setObjectName("statusText")
        MainWindow.setCentralWidget(self.centralwidget)
        self.menubar = QtWidgets.QMenuBar(MainWindow)
        self.menubar.setGeometry(QtCore.QRect(0, 0, 1006, 21))
        self.menubar.setObjectName("menubar")
        self.menuInfo = QtWidgets.QMenu(self.menubar)
        self.menuInfo.setObjectName("menuInfo")
        MainWindow.setMenuBar(self.menubar)
        self.actionAbout_this_tool = QtWidgets.QAction(MainWindow)
        self.actionAbout_this_tool.setShortcutContext(QtCore.Qt.WindowShortcut)
        self.actionAbout_this_tool.setVisible(True)
        self.actionAbout_this_tool.setMenuRole(QtWidgets.QAction.NoRole)
        self.actionAbout_this_tool.setObjectName("actionAbout_this_tool")
        self.menuInfo.addAction(self.actionAbout_this_tool)
        self.menubar.addAction(self.menuInfo.menuAction())

        self.retranslateUi(MainWindow)
        QtCore.QMetaObject.connectSlotsByName(MainWindow)

    def retranslateUi(self, MainWindow):
        _translate = QtCore.QCoreApplication.translate
        MainWindow.setWindowTitle(_translate("MainWindow", "MainWindow"))
        self.horizontalGroupBox.setTitle(_translate("MainWindow", "Option save:"))
        self.option_two.setText(_translate("MainWindow", "Save"))
        self.option_one.setText(_translate("MainWindow", "Save and replace"))
        self.pushButton.setText(_translate("MainWindow", "Read Json"))
        self.label_9.setText(_translate("MainWindow", "0"))
        self.label_7.setText(_translate("MainWindow", "0"))
        self.label_8.setText(_translate("MainWindow", "0"))
        self.label_10.setText(_translate("MainWindow", "0"))
        self.label_6.setText(_translate("MainWindow", "0"))
        self.single_case.setText(_translate("MainWindow", "Single Case"))
        self.split_case.setText(_translate("MainWindow", "Split"))
        self.split_manual_case.setText(_translate("MainWindow", "Split Manual Case"))
        self.group_case.setText(_translate("MainWindow", "Group Case"))
        self.supple_case.setText(_translate("MainWindow", "Supplement"))
        self.statusText.setText(_translate("MainWindow", "TextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelTextLabelabelTextLabelTextLabelTextLabelTextLabelTextLabel"))
        self.menuInfo.setTitle(_translate("MainWindow", "Info"))
        self.actionAbout_this_tool.setText(_translate("MainWindow", "About this tool"))


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    MainWindow = QtWidgets.QMainWindow()
    ui = Ui_MainWindow()
    ui.setupUi(MainWindow)
    MainWindow.show()
    sys.exit(app.exec_())
