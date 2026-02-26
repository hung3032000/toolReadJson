import json, time, threading
from datetime import datetime, timedelta
import requests
from util import update_message_status_box

# ---- lock để tránh nhiều thread cùng refresh token/ghi config.json ----
_TOKEN_LOCK = threading.Lock()

# ---- thời gian ----
def _p(s, fmt="%Y%m%d"): return datetime.strptime(s, fmt)
def _f(d, fmt="%Y%m%d"): return d.strftime(fmt)
def split_interval_str(fm, to):
    a, b = _p(fm), _p(to)
    mid = a + (b - a)/2
    left  = (_f(a), _f(mid))
    right = (_f(mid + timedelta(days=1)), _f(b))
    return left, right

def split_to_days(fm, to):
    a, b = _p(fm), _p(to)
    out = []
    cur = a
    while cur <= b:
        out.append(_f(cur))
        cur += timedelta(days=1)
    return out

# ---- chuẩn hoá JSON ----
def extract_records(payload):
    if isinstance(payload, list): return payload
    if isinstance(payload, dict):
        for k in ['data','items','results','rows','content','list','records']:
            v = payload.get(k)
            if isinstance(v, list): return v
        return [payload]
    return []

# ---- HTTP session với retry “nhẹ” ----
def build_session():
    s = requests.Session()
    s.headers.update({
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    })
    return s

def _post(session, url, headers, body, timeout=120):
    return session.post(url, headers=headers, data=json.dumps(body), timeout=timeout)

# ---- gọi 1 window với chia nhỏ thích ứng cho 504/502 ----
def fetch_window_adaptive(self, session, base_url, headers, base_body,
                          office, customers, fm, to, source_codes,
                          min_unit_days=1):
    """
    customers: list cust_cd (1 hoặc nhiều)
    source_codes: ví dụ ['MRI','FRT','MDM','MDT','MRD']
    Trả về list[dict] đã ghép.
    """
    all_rows = []

    def _call_once(body):
        try:
            # có thể thêm sleep jitter nhẹ nếu bị rate limit:
            time.sleep(0.05)
            resp = _post(session, base_url, headers, body)
            return resp, None
        except requests.RequestException as e:
            return None, f"net:{e}"

    def _range_call_for_sources(fm_s, to_s):
        """
        Tách theo source_code khi body lớn/hỏng JSON.
        Trả về True nếu lấy được bất kỳ data.
        """
        got_any = False
        for src in source_codes:
            body = dict(base_body)
            body.update({
                "ofc_cd": office,
                "fm_inv_issue_date": fm_s,
                "to_inv_issue_date": to_s,
                "cust_cd": [{"cust_cd": c} for c in customers],
                "source_code": [{"source_code": src}],
                "fields": ["ZZ_IF_ID","INV_NO","INV_CUST_CD","BL_SRC_NO","INV_ISS_CURR_CD"],
            })
            resp, err = _call_once(body)
            if err:
                continue
            if resp.status_code == 200:
                try:
                    rows = extract_records(resp.json())
                    all_rows.extend(rows)
                    got_any = True
                    continue
                except ValueError:
                    # JSON hỏng → để chia nhỏ tiếp theo ngày/khách
                    pass
        return got_any

    def _split_customers_and_call(fm_s, to_s):
        """
        Fallback cuối: tách theo customers nếu vẫn quá lớn.
        Chia đôi danh sách customers và gọi lại một lượt (không đệ quy vô hạn).
        """
        if len(customers) <= 1:
            return False
        mid = len(customers) // 2
        chunks = [customers[:mid], customers[mid:]]
        got_any = False
        for chunk in chunks:
            body = dict(base_body)
            body.update({
                "ofc_cd": office,
                "fm_inv_issue_date": fm_s,
                "to_inv_issue_date": to_s,
                "cust_cd": [{"cust_cd": c} for c in chunk],
                "source_code": [{"source_code": s} for s in source_codes],
                "fields": ["ZZ_IF_ID","INV_NO","INV_CUST_CD","BL_SRC_NO","INV_ISS_CURR_CD"],
            })
            resp, err = _call_once(body)
            if err:
                continue
            if resp.status_code == 200:
                try:
                    rows = extract_records(resp.json())
                    all_rows.extend(rows); got_any = True
                    continue
                except ValueError:
                    # Nếu vẫn JSON hỏng → chia theo ngày + source cho chunk này
                    for d in split_to_days(fm_s, to_s):
                        _range_call_for_sources(d, d)
                continue

            # Nếu 5xx/TooBigBody → chia theo ngày + source cho chunk này
            txt_preview = (getattr(resp, "text", "") or "")[:160]
            if resp.status_code in (502, 504) or "TooBigBody" in txt_preview or "Body buffer overflow" in txt_preview:
                for d in split_to_days(fm_s, to_s):
                    _range_call_for_sources(d, d)
                continue
            if 500 <= resp.status_code < 600:
                time.sleep(0.6)
                for d in split_to_days(fm_s, to_s):
                    _range_call_for_sources(d, d)
        return got_any

    def _do_range(fm_s, to_s, depth=0):
        nonlocal all_rows

        # Thử 1 phát với toàn bộ sources + toàn bộ customers trong batch
        body_try = dict(base_body)
        body_try.update({
            "ofc_cd": office,
            "fm_inv_issue_date": fm_s,
            "to_inv_issue_date": to_s,
            "cust_cd": [{"cust_cd": c} for c in customers],
            "source_code": [{"source_code": s} for s in source_codes],
            "fields": ["ZZ_IF_ID","INV_NO","INV_CUST_CD","BL_SRC_NO","INV_ISS_CURR_CD"],
        })
        resp, err = _call_once(body_try)

        if err:
            # lỗi mạng → chia đôi range
            left, right = split_interval_str(fm_s, to_s)
            if fm_s == to_s:
                # đã là 1 ngày → tách theo source_code, nếu vẫn fail sẽ tách theo customer ở dưới
                pass
            else:
                _do_range(*left, depth+1)
                _do_range(*right, depth+1)
                return

        if resp:
            txt_preview = (getattr(resp, "text", "") or "")[:160]
            if resp.status_code == 200:
                try:
                    rows = extract_records(resp.json())
                    all_rows.extend(rows)
                    return
                except ValueError:
                    # JSON hỏng → xem như body quá lớn
                    pass

            # 401 → refresh token 1 lần rồi thử lại cùng range (có lock)
            if resp.status_code == 401 and depth < 2:
                from getNewToken import updateConfigToken
                with _TOKEN_LOCK:
                    updateConfigToken(self)
                    try:
                        with open("config.json","r",encoding="utf-8") as f:
                            cfg = json.load(f)
                        merged = dict(cfg.get("headers", {}) or {})
                        try:
                            from secret_provider import apply_secrets_to_headers
                            env = (self.envCombobox.currentText() if hasattr(self, "envCombobox") else "TEST").strip().upper()
                            merged = apply_secrets_to_headers(cfg, env, merged)
                        except Exception:
                            pass
                        headers.update(merged)
                    except Exception:
                        pass
                _do_range(fm_s, to_s, depth+1)
                return

            # 204: không có data
            if resp.status_code == 204:
                return

            # 504/502 hoặc quá to → chia nhỏ
            if resp.status_code in (504, 502) or "TooBigBody" in txt_preview or "Body buffer overflow" in txt_preview:
                # nếu > 1 ngày → chia đôi range
                if _p(to_s) > _p(fm_s):
                    left, right = split_interval_str(fm_s, to_s)
                    _do_range(*left, depth+1)
                    _do_range(*right, depth+1)
                    return
                # đã 1 ngày → tách theo source_code
                got = _range_call_for_sources(fm_s, to_s)
                if got:
                    return
                # vẫn khó → tách tiếp theo customers
                _split_customers_and_call(fm_s, to_s)
                return

            # 5xx khác → backoff rồi chia đôi nếu >1 ngày
            if 500 <= resp.status_code < 600:
                time.sleep(min(8, 0.5*(2**depth)) + 0.2)
                if _p(to_s) > _p(fm_s):
                    left, right = split_interval_str(fm_s, to_s)
                    _do_range(*left, depth+1)
                    _do_range(*right, depth+1)
                else:
                    # 1 ngày mà 5xx → thử theo source_code, sau đó customer
                    got = _range_call_for_sources(fm_s, to_s)
                    if not got:
                        _split_customers_and_call(fm_s, to_s)
                return

            # các mã khác → log & bỏ qua
            update_message_status_box(self, f"Unhandled {resp.status_code} {fm_s}→{to_s}: {txt_preview}")

    _do_range(fm, to, depth=0)
    return all_rows
