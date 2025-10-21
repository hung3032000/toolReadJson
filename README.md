UI (mainUI)
   │
   ├── Get Token → getNewToken.py → API /token → lưu Bearer vào config.json
   │
   └── Read Json → process.onFuncButtonClick
         │
         ├── Đọc config + input từ UI
         ├── Chia range 2 tháng → gọi API
         ├── parse JSON → gom data
         ├── Ghi Excel tạm
         ├── processCaseInBrim → phân loại 6 case
         ├── saveNewExcel → ghi nhiều sheet
         └── Cập nhật số lượng case ra UI
