# util.py
def update_message_status_box(self, new_status):
    try:
        curr = self.statusText.text() if hasattr(self.statusText, "text") else ""
        new_msg = (curr + "\n" + str(new_status)).strip()
        if hasattr(self.statusText, "setText"):
            self.statusText.setText(new_msg)
    except Exception:
        pass
