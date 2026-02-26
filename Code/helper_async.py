import asyncio
import json
import time
from datetime import datetime, timedelta

import httpx

from util import update_message_status_box


def _p(s, fmt="%Y%m%d"):
    return datetime.strptime(s, fmt)


def _f(d, fmt="%Y%m%d"):
    return d.strftime(fmt)


def split_interval_str(fm, to):
    a, b = _p(fm), _p(to)
    mid = a + (b - a) / 2
    left = (_f(a), _f(mid))
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


def extract_records(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ["data", "items", "results", "rows", "content", "list", "records"]:
            v = payload.get(k)
            if isinstance(v, list):
                return v
        return [payload]
    return []


def build_async_client(connect_timeout=10.0, read_timeout=120.0):
    timeout = httpx.Timeout(connect=connect_timeout, read=read_timeout, write=read_timeout, pool=read_timeout)
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    return httpx.AsyncClient(timeout=timeout, limits=limits)


_TOKEN_LOCK = asyncio.Lock()


async def _refresh_headers_after_token_update(self, headers):
    from getNewToken import updateConfigToken

    async with _TOKEN_LOCK:
        await asyncio.to_thread(updateConfigToken, self)
        try:
            def _read_cfg():
                with open("config.json", "r", encoding="utf-8") as f:
                    return json.load(f)

            cfg = await asyncio.to_thread(_read_cfg)
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


async def fetch_window_adaptive_async(
    self,
    client,
    base_url,
    headers,
    base_body,
    office,
    customers,
    fm,
    to,
    source_codes,
    throttle=None,
):
    all_rows = []

    async def _call_once(body):
        await asyncio.sleep(0.02)
        started = time.perf_counter()
        try:
            resp = await client.post(base_url, headers=headers, json=body)
            latency_ms = (time.perf_counter() - started) * 1000.0
            if throttle is not None:
                throttle.record(latency_ms, status_code=resp.status_code, is_error=False)
            return resp, None
        except httpx.RequestError as e:
            latency_ms = (time.perf_counter() - started) * 1000.0
            if throttle is not None:
                throttle.record(latency_ms, status_code=None, is_error=True)
            return None, f"net:{e}"

    async def _range_call_for_sources(fm_s, to_s):
        got_any = False
        for src in source_codes:
            body = dict(base_body)
            body.update(
                {
                    "ofc_cd": office,
                    "fm_inv_issue_date": fm_s,
                    "to_inv_issue_date": to_s,
                    "cust_cd": [{"cust_cd": c} for c in customers],
                    "source_code": [{"source_code": src}],
                    "fields": ["ZZ_IF_ID", "INV_NO", "INV_CUST_CD", "BL_SRC_NO", "INV_ISS_CURR_CD"],
                }
            )
            resp, err = await _call_once(body)
            if err:
                continue
            if resp.status_code == 200:
                try:
                    rows = extract_records(resp.json())
                    all_rows.extend(rows)
                    got_any = True
                    continue
                except ValueError:
                    pass
        return got_any

    async def _split_customers_and_call(fm_s, to_s):
        if len(customers) <= 1:
            return False

        mid = len(customers) // 2
        chunks = [customers[:mid], customers[mid:]]
        got_any = False

        for chunk in chunks:
            body = dict(base_body)
            body.update(
                {
                    "ofc_cd": office,
                    "fm_inv_issue_date": fm_s,
                    "to_inv_issue_date": to_s,
                    "cust_cd": [{"cust_cd": c} for c in chunk],
                    "source_code": [{"source_code": s} for s in source_codes],
                    "fields": ["ZZ_IF_ID", "INV_NO", "INV_CUST_CD", "BL_SRC_NO", "INV_ISS_CURR_CD"],
                }
            )
            resp, err = await _call_once(body)
            if err:
                continue

            if resp.status_code == 200:
                try:
                    rows = extract_records(resp.json())
                    all_rows.extend(rows)
                    got_any = True
                    continue
                except ValueError:
                    for d in split_to_days(fm_s, to_s):
                        await _range_call_for_sources(d, d)
                continue

            txt_preview = (getattr(resp, "text", "") or "")[:160]
            if resp.status_code in (502, 504) or "TooBigBody" in txt_preview or "Body buffer overflow" in txt_preview:
                for d in split_to_days(fm_s, to_s):
                    await _range_call_for_sources(d, d)
                continue

            if 500 <= resp.status_code < 600:
                await asyncio.sleep(0.6)
                for d in split_to_days(fm_s, to_s):
                    await _range_call_for_sources(d, d)
        return got_any

    async def _do_range(fm_s, to_s, depth=0):
        body_try = dict(base_body)
        body_try.update(
            {
                "ofc_cd": office,
                "fm_inv_issue_date": fm_s,
                "to_inv_issue_date": to_s,
                "cust_cd": [{"cust_cd": c} for c in customers],
                "source_code": [{"source_code": s} for s in source_codes],
                "fields": ["ZZ_IF_ID", "INV_NO", "INV_CUST_CD", "BL_SRC_NO", "INV_ISS_CURR_CD"],
            }
        )
        resp, err = await _call_once(body_try)

        if err:
            if fm_s == to_s:
                return
            left, right = split_interval_str(fm_s, to_s)
            await _do_range(*left, depth + 1)
            await _do_range(*right, depth + 1)
            return

        txt_preview = (getattr(resp, "text", "") or "")[:160]
        if resp.status_code == 200:
            try:
                rows = extract_records(resp.json())
                all_rows.extend(rows)
                return
            except ValueError:
                pass

        if resp.status_code == 401 and depth < 2:
            await _refresh_headers_after_token_update(self, headers)
            await _do_range(fm_s, to_s, depth + 1)
            return

        if resp.status_code == 204:
            return

        if resp.status_code in (502, 504) or "TooBigBody" in txt_preview or "Body buffer overflow" in txt_preview:
            if _p(to_s) > _p(fm_s):
                left, right = split_interval_str(fm_s, to_s)
                await _do_range(*left, depth + 1)
                await _do_range(*right, depth + 1)
                return
            got = await _range_call_for_sources(fm_s, to_s)
            if got:
                return
            await _split_customers_and_call(fm_s, to_s)
            return

        if 500 <= resp.status_code < 600:
            await asyncio.sleep(min(8.0, 0.5 * (2 ** depth)) + 0.2)
            if _p(to_s) > _p(fm_s):
                left, right = split_interval_str(fm_s, to_s)
                await _do_range(*left, depth + 1)
                await _do_range(*right, depth + 1)
            else:
                got = await _range_call_for_sources(fm_s, to_s)
                if not got:
                    await _split_customers_and_call(fm_s, to_s)
            return

        update_message_status_box(self, f"Unhandled {resp.status_code} {fm_s}->{to_s}: {txt_preview}")

    await _do_range(fm, to, depth=0)
    return all_rows
