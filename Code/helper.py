import json, time
from datetime import datetime, timedelta
import requests
from util import update_message_status_box

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
    customers: list cust_cd (bạn có thể truyền 1 hoặc nhiều)
    source_codes: ví dụ ['MRI','FRT'] ...
    Trả về list[dict] đã ghép.
    """
    all_rows = []

    def _call_once(body):
        # 1 request “thử”
        try:
            resp = _post(session, base_url, headers, body)
            return resp, None
        except requests.RequestException as e:
            return None, f"net:{e}"

    def _do_range(fm_s, to_s, depth=0):
        nonlocal all_rows
        # Nếu đã là đơn vị nhỏ nhất (ngày) rồi mà vẫn fail 502/504 thì tách theo source_code tiếp
        def _range_call_for_sources():
            got_any = False
            for src in source_codes:
                body = dict(base_body)
                body.update({
                    "ofc_cd": office,
                    "fm_inv_issue_date": fm_s,
                    "to_inv_issue_date": to_s,
                    "cust_cd": [{"cust_cd": c} for c in customers],
                    "source_code": [{"source_code": src}],
                    # giảm cột để body nhỏ hơn (nếu BE support)
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
                        # JSON hỏng (thường do body cắt) → sẽ chia nhỏ theo ngày ở dưới
                        pass
                # nếu vẫn 502/504 hoặc body cắt → sẽ chia ngày
            return got_any

        # Thử 1 phát với toàn bộ sources cùng lúc (nếu bạn thích có thể bỏ để chỉ chạy theo từng source)
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
            # lỗi mạng → chia đôi
            left, right = split_interval_str(fm_s, to_s)
            if fm_s == to_s:
                # đã là 1 ngày → tách theo source_code, nếu vẫn fail sẽ tách xuống từng ngày ở dưới
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

            # 401 → refresh token 1 lần rồi thử lại cùng range
            if resp.status_code == 401 and depth < 2:
                from getNewToken import updateConfigToken
                updateConfigToken(self)
                with open("config.json","r",encoding="utf-8") as f:
                    cfg = json.load(f)
                headers.update(cfg.get("headers", {}))
                _do_range(fm_s, to_s, depth+1)
                return

            # 204: không có data
            if resp.status_code == 204:
                return

            # 504 hoặc 502 TooBigBody → thu nhỏ
            if resp.status_code in (504, 502) or "TooBigBody" in txt_preview or "Body buffer overflow" in txt_preview:
                # nếu > 1 ngày → chia đôi range
                if _p(to_s) > _p(fm_s):
                    left, right = split_interval_str(fm_s, to_s)
                    _do_range(*left, depth+1)
                    _do_range(*right, depth+1)
                    return
                # đã là 1 ngày → tách theo source_code
                got = _range_call_for_sources()
                if got:
                    return
                # vẫn không được → chia nhỏ xuống từng ngày (trường hợp fm_s==to_s sẽ rơi vào 1 phần tử)
                for d in split_to_days(fm_s, to_s):
                    # ở đây đã là 1 ngày rồi; nếu backend cho theo giờ, bạn có thể bẻ tiếp theo giờ
                    _range_call_for_sources()
                return

            # 5xx khác → backoff rồi chia đôi nếu >1 ngày
            if 500 <= resp.status_code < 600:
                time.sleep(min(8, 0.5*(2**depth)) + 0.2)
                if _p(to_s) > _p(fm_s):
                    left, right = split_interval_str(fm_s, to_s)
                    _do_range(*left, depth+1)
                    _do_range(*right, depth+1)
                else:
                    # 1 ngày mà 5xx → thử theo source_code
                    _range_call_for_sources()
                return

            # các mã khác → log & bỏ qua
            update_message_status_box(self, f"Unhandled {resp.status_code} {fm_s}→{to_s}: {txt_preview}")

    _do_range(fm, to, depth=0)
    return all_rows
