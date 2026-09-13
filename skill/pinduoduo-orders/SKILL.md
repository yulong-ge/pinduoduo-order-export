---
name: pinduoduo-orders
description: Export the user's Pinduoduo (拼多多) buyer orders to a bookkeeping CSV with refund amounts and net spending. Use when the user asks for 拼多多订单, 拼多多账单, 拼多多年度账单, 多多买菜订单, 导出/下载/爬取拼多多订单, or wants to see how much they spent on Pinduoduo over a date range.
---

# Pinduoduo Orders Export

Export Pinduoduo buyer orders (normal orders + 多多买菜) into a 20-column Chinese-header CSV suitable for bookkeeping, with per-order refund amounts and net spending.

The tool lives in the open-source repo `pinduoduo-order-export`. Run everything through `uv` (never bare `python`/`pip`). Node.js must be available for the anti_content generator (`hello.js` via PyExecJS).

## Setup

```bash
# if not already cloned locally (do not hardcode a machine-specific path; use the task workspace)
git clone https://github.com/yulong-ge/pinduoduo-order-export.git
cd pinduoduo-order-export
```

## Workflow

1. **Cookies.** The user must be logged in to https://mobile.pinduoduo.com/ in a browser. Extract cookies into `config.json` (see `config.example.json`; `pdduid` = `pdd_user_id`).
   - Fast path when the user is logged in inside EgoLite (agent browser): open a task space, navigate to `https://mobile.pinduoduo.com/orders.html`, then pull cookies via `page.cdp("Network.getCookies", { urls: ["https://mobile.pinduoduo.com"] })` and write them to `config.json`. Include httpOnly cookies, notably `PDDAccessToken`.
   - Generic path: browser DevTools → copy all cookies for the `mobile.pinduoduo.com` domain from the `order_list_v4` request.

2. **Verify the chain** before any bulk crawl. A single-page check is cheap and avoids wasting requests on a dead cookie:

   ```bash
   uv run --with requests --with PyExecJS python pdd_orders.py test
   ```

   0 orders returned means the cookie expired, re-extract it. Other failures usually mean the anti_content algorithm in `hello.js` (extracted from the H5 page in 2024) no longer passes risk control. Report that and stop instead of retrying.

3. **Fetch** raw orders (paginates newest→oldest, stops at the year boundary; ~5.2s/page):

   ```bash
   uv run --with requests --with PyExecJS python pdd_orders.py fetch --year 2026
   ```

   Writes `pdd_order.txt` (one JSON per line; previous file auto-backed-up to `.bak`).

4. **Export** the bookkeeping CSV for the requested range:

   ```bash
   uv run --with requests --with PyExecJS python pdd_orders.py export \
     --start 2026-06-01 --end 2026-09-01 --out 拼多多订单明细.csv
   ```

   This calls the 多多买菜 parent-order API again to fill in amounts (maicai refund orders read as 0 in the order-list API). Reuse step-1 cookies.

## Data semantics

- type=2 orders are 多多买菜 (self-pickup grocery). Their refund amounts only exist in the parent-order API (`mc/v0/banana/query_user_parent_order_list`), including sub-order-level status that detects partial refunds. The `page` param on that API repeats page 1; the tool dedupes by order sn and stops.
- Normal orders with status 退款成功 are treated as fully refunded (refund = paid, cash + returned coupon). Net spending = 实付 − 退款.
- 先用后付 (pay-after-use) orders are recorded at the payable amount; the status column shows the pending state.

## Privacy rules

- `config.json`, `pdd_order.txt`, and exported CSVs contain personal data: never commit them, never paste cookie values into replies. The repo's `.gitignore` already excludes them.
- Deliver the CSV as a local file path (user's bills folders), not through any external service.
