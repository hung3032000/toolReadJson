def update_message_status_box(self, new_status):
    current_text = self.statusText.text()
    if current_text == '':
        new_message = f"{new_status}"
    else:
        new_message = f"{current_text} \n{new_status}"
    self.statusText.setText(new_message)
    