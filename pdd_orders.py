#!/usr/bin/env python3
"""拼多多订单导出工具。

子命令:
  fetch  翻页抓取订单列表(普通订单+多多买菜),原始 JSON 逐行存入数据文件
  export 合并买菜父订单接口数据,导出带表头的记账明细 CSV
  test   单页请求验证 cookie 与 anti_content 链路是否有效

依赖: requests, PyExecJS(execjs), Node.js(hello.js 需要)
用法示例:
  uv run --with requests --with PyExecJS python pdd_orders.py fetch --year 2026
  uv run --with requests --with PyExecJS python pdd_orders.py export --start 2026-06-01 --end 2026-09-01 --out bill.csv
"""
import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime

import execjs
import requests

DATA_FILE = 'pdd_order.txt'
PAGE_INTERVAL = 5.2  # 翻页间隔,避免触发风控
UA = ('Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36')


class ApiError(RuntimeError):
    pass


def load_config(path):
    if not os.path.exists(path):
        raise SystemExit(f"缺少配置文件 {path}: 请参照 config.example.json 创建,cookies 从已登录"
                         " mobile.pinduoduo.com 的浏览器会话中提取")
    config = json.load(open(path, encoding='utf-8'))
    cookies = config.get('cookies') or {}
    pdduid = str(config.get('pdduid') or '')
    if not cookies or not pdduid:
        raise SystemExit(f"{path} 中缺少 cookies 或 pdduid")
    return cookies, pdduid


def anti_content():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hello.js'),
              encoding='utf-8') as f:
        return execjs.compile(f.read()).call('dt')


def order_list_request(cookies, pdduid, offset):
    headers = {
        'accept': 'application/json, text/plain, */*',
        'content-type': 'application/json;charset=UTF-8',
        'origin': 'https://mobile.pinduoduo.com',
        'referer': 'https://mobile.pinduoduo.com/orders.html?type=0&comment_tab=1&combine_orders=1&main_orders=1',
        'user-agent': UA,
    }
    body = {
        'type': 'all', 'page': 1, 'origin_host_name': 'mobile.pinduoduo.com',
        'scene': 'order_list_h5', 'page_from': 0, 'anti_content': anti_content(),
        'size': 10, 'offset': offset,
    }
    r = requests.post('https://mobile.pinduoduo.com/proxy/api/api/aristotle/order_list_v4',
                      params={'pdduid': pdduid}, cookies=cookies, headers=headers,
                      json=body, timeout=30)
    if r.status_code != 200:
        raise ApiError(f'order_list_v4 返回 HTTP {r.status_code}: {r.text[:200]}')
    try:
        return r.json()
    except ValueError as e:
        raise ApiError(f'order_list_v4 返回非 JSON(HTTP {r.status_code}): {r.text[:200]}') from e


def cmd_fetch(args):
    cookies, pdduid = load_config(args.config)
    year_start = datetime(args.year, 1, 1).timestamp()
    year_end = datetime(args.year + 1, 1, 1).timestamp()
    if os.path.exists(args.data):
        backup = args.data + '.bak'
        os.replace(args.data, backup)
        print(f"已存在的 {args.data} 备份为 {backup}")

    total = 0
    offset = '0'
    with open(args.data, 'w', encoding='utf-8') as f:
        while True:
            resp = order_list_request(cookies, pdduid, offset)
            orders = resp.get('orders') or []
            if not orders:
                break
            for o in orders:
                f.write(json.dumps(o, ensure_ascii=False) + '\n')
            total += len(orders)
            print(f"已抓取 {total} 笔(本页 {len(orders)} 笔)")
            last = orders[-1]
            t = last.get('order_time') or last.get('group_order', {}).get('success_time', 0)
            if not (year_start <= t < year_end):
                print(f"已到达 {args.year} 年边界,停止")
                break
            offset = last.get('offset', '')
            if not offset:
                raise ApiError(f'翻页 offset 缺失,订单 {last.get("order_sn")}')
            time.sleep(PAGE_INTERVAL)
    print(f"完成: 共 {total} 笔订单写入 {args.data}")


def fetch_po_orders(cookies, pdduid):
    """多多买菜父订单列表。

    退款单在 order_list_v4 中金额归零,须用此接口拿原始金额与子单级退款状态。
    page 参数翻页无效(服务端重复返回第一页),按 sn 去重后停止。
    """
    headers = {
        'accept': 'application/json, text/plain, */*',
        'content-type': 'application/json;charset=UTF-8',
        'origin': 'https://mobile.pinduoduo.com',
        'referer': 'https://mobile.pinduoduo.com/ywgnpxpt.html?_p_page=vgt_order_list',
        'user-agent': UA,
    }
    collected, page = {}, 1
    while True:
        body = {'page': page, 'size': 20, 'anti_content': anti_content()}
        r = requests.post(
            'https://mobile.pinduoduo.com/proxy/api/api/mc/v0/banana/query_user_parent_order_list',
            params={'pdduid': pdduid}, cookies=cookies, headers=headers, json=body, timeout=30)
        if r.status_code != 200:
            raise ApiError(f'query_user_parent_order_list 返回 HTTP {r.status_code}: {r.text[:200]}')
        lst = (r.json().get('result') or {}).get('parent_fresh_order_result_list') or []
        new = [o for o in lst if o['parent_order_sn'] not in collected]
        if not new:
            break
        for o in new:
            collected[o['parent_order_sn']] = o
        page += 1
        time.sleep(1.5)
    return list(collected.values())


def yuan(fen):
    return '' if fen is None else f"{fen / 100:.2f}"


def ts(t):
    return datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M:%S') if t else ''


def cmd_export(args):
    cookies, pdduid = load_config(args.config)
    if not os.path.exists(args.data):
        raise SystemExit(f"数据文件 {args.data} 不存在,请先运行 fetch")
    start_ts = datetime.fromisoformat(args.start).timestamp()
    end_ts = datetime.fromisoformat(args.end).timestamp()
    orders = [json.loads(l) for l in open(args.data, encoding='utf-8') if l.strip()]
    po_orders = {o['parent_order_sn']: o for o in fetch_po_orders(cookies, pdduid)}

    rows, stats = [], []

    for o in orders:
        if o.get('type') != 1 or not (start_ts <= o.get('order_time', 0) < end_ts):
            continue
        goods = o.get('order_goods', [])
        status = o.get('order_status_prompt', '')
        paid = o.get('order_amount', 0)
        refund = paid if status == '退款成功' else 0
        rows.append([
            o.get('order_sn', ''), '', '普通', ts(o.get('order_time')),
            (o.get('mall') or {}).get('mall_name', ''),
            '\n'.join(g.get('goods_name', '') for g in goods),
            '\n'.join(g.get('spec', '') or '' for g in goods),
            '\n'.join(yuan(g.get('goods_price')) for g in goods),
            '\n'.join(str(g.get('goods_number', 0)) for g in goods),
            yuan(sum((g.get('goods_price') or 0) * (g.get('goods_number') or 0) for g in goods)),
            yuan(o.get('discount_amount')), yuan(o.get('shipping_amount')),
            yuan(paid), status, status, yuan(refund), yuan(paid - refund),
            ts(o.get('receive_time')), o.get('tracking_number') or '',
            '\n'.join(g.get('thumb_url', '') for g in goods),
        ])
        stats.append((o.get('order_sn'), paid, refund))

    for o in orders:
        if o.get('type') != 2:
            continue
        t = o.get('group_order', {}).get('success_time', 0)
        if not (start_ts <= t < end_ts):
            continue
        po = po_orders.get(o.get('order_sn', ''))
        if po is None:
            print(f"WARN: 买菜单 {o.get('order_sn')} 不在父订单接口返回中,金额字段将缺失",
                  file=sys.stderr)
            po = {'parent_order_time': t, 'parent_discount_amount': None,
                  'fresh_order_result_list': [
                      {'order_sn': s.get('order_sn'), 'order_amount': None,
                       'fresh_order_text': {'text': ''}, 'goods_name': g.get('goods_name'),
                       'sku_number': g.get('goods_number'), 'goods_price': g.get('goods_price'),
                       'thumb_url': g.get('thumb_url')}
                      for s in o.get('orders', []) for g in s.get('order_goods', [])]}
        sub_paid = sub_refund = 0
        first = True
        for sub in po.get('fresh_order_result_list') or []:
            amt = sub.get('order_amount') or 0
            st = ((sub.get('fresh_order_text') or {}).get('text')) or ''
            refunded = st == '退款成功'
            sub_paid += amt
            sub_refund += amt if refunded else 0
            rows.append([
                sub.get('order_sn', ''), po.get('parent_order_sn', '') if first else '',
                '多多买菜' if first else '', ts(po.get('parent_order_time')) if first else '',
                '多多买菜(自提)' if first else '',
                sub.get('goods_name', ''), '', yuan(sub.get('goods_price')),
                sub.get('sku_number', ''), yuan(amt),
                yuan(po.get('parent_discount_amount')) if first else '', '',
                yuan(amt), st, st, yuan(amt if refunded else 0),
                yuan(0 if refunded else amt), '', '', sub.get('thumb_url', ''),
            ])
            first = False
        stats.append((po.get('parent_order_sn', ''), sub_paid, sub_refund))

    header = ['订单号', '父单号', '类型', '下单时间', '店铺', '商品名', '规格', '单价(元)', '数量',
              '小计(元)', '优惠(元)', '运费(元)', '实付(元)', '订单状态', '售后状态', '退款金额(元)',
              '净支出(元)', '收货时间', '快递单号', '商品图']
    with open(args.out, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)

    paid_sum = sum(p for _, p, _ in stats) / 100
    refund_sum = sum(r for _, _, r in stats) / 100
    print(f"拼多多账单 {args.start} ~ {args.end}:")
    print(f"  订单数: {len(stats)}  商品行数: {len(rows)}")
    print(f"  实付合计: {paid_sum:.2f} 元")
    print(f"  退款合计: {refund_sum:.2f} 元")
    print(f"  净支出:   {paid_sum - refund_sum:.2f} 元")
    for sn, p, r in stats:
        if r:
            print(f"    退款单 {sn}: 实付 {yuan(p)} 退款 {yuan(r)}")


def cmd_test(args):
    cookies, pdduid = load_config(args.config)
    resp = order_list_request(cookies, pdduid, '0')
    orders = resp.get('orders') or []
    print(f"HTTP OK, 返回 {len(orders)} 笔订单")
    if orders:
        o = orders[0]
        t = o.get('order_time') or o.get('group_order', {}).get('success_time')
        print(f"最新订单时间: {ts(t)}, 状态: {o.get('order_status_prompt')}")
        print("链路有效: cookie 与 anti_content 均通过")
    else:
        print("返回 0 笔订单: cookie 可能已失效,请重新提取", file=sys.stderr)
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('fetch', help='翻页抓取订单原始 JSON')
    p.add_argument('--year', type=int, default=datetime.now().year, help='抓取到哪一年边界(默认当年)')
    p.add_argument('--config', default='config.json')
    p.add_argument('--data', default=DATA_FILE)
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser('export', help='导出记账明细 CSV')
    p.add_argument('--start', required=True, help='区间起始日(含), YYYY-MM-DD')
    p.add_argument('--end', required=True, help='区间结束日(不含), YYYY-MM-DD')
    p.add_argument('--out', required=True, help='输出 CSV 路径')
    p.add_argument('--config', default='config.json')
    p.add_argument('--data', default=DATA_FILE)
    p.set_defaults(func=cmd_export)

    p = sub.add_parser('test', help='单页请求验证链路')
    p.add_argument('--config', default='config.json')
    p.set_defaults(func=cmd_test)

    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
