# util.py
def update_message_status_box(self, new_status):
    try:
        w = getattr(self, "statusText", None)
        if w is None:
            return
        msg = str(new_status)

        # QTextEdit có toPlainText()/append()
        if hasattr(w, "toPlainText") and hasattr(w, "append"):
            w.append(msg)
            return

        # QLabel có text()/setText()
        curr = w.text() if hasattr(w, "text") else ""
        new_msg = (curr + "\n" + msg).strip()
        if hasattr(w, "setText"):
            w.setText(new_msg)
    except Exception:
        pass
