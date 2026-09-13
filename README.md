# pinduoduo-order-export

拼多多买家订单导出工具：抓取普通订单与多多买菜订单，导出带表头、含退款金额与净支出的记账明细 CSV。

基于 [LynnShaw/pinduoduo-summary](https://github.com/LynnShaw/pinduoduo-summary) 完善而来，主要增强：

- 多多买菜订单单独走父订单接口（`mc/v0/banana/query_user_parent_order_list`）补全金额。买菜退款单在订单列表接口中金额归零，父订单接口能返回原始金额和子单级退款状态，整单退款与部分退款都能识别
- 导出 CSV 带 20 列中文表头：订单号 / 父单号 / 类型 / 下单时间 / 店铺 / 商品名 / 规格 / 单价 / 数量 / 小计 / 优惠 / 运费 / 实付 / 订单状态 / 售后状态 / 退款金额 / 净支出 / 收货时间 / 快递单号 / 商品图
- 统计输出实付合计、退款合计、净支出，逐笔列出退款单
- `test` 子命令单页验证 cookie 与风控参数链路
- 重跑 `fetch` 自动备份旧数据文件
- 修复原脚本的数据问题：重复运行时订单重复追加、原始 JSON 存档只保留最后一行、导出 CSV 中文乱码

## 环境要求

- Python 3.10+
- Node.js（`hello.js` 由 PyExecJS 调用执行，用于生成 `anti_content` 风控参数）
- 推荐用 [uv](https://docs.astral.sh/uv/) 运行，无需手动建虚拟环境

## 使用步骤

### 1. 登录并提取 cookie

用浏览器（手机模式 UA 或开发者工具切移动端视图）访问并登录 [拼多多网页版](https://mobile.pinduoduo.com/)，打开"我的订单"页面。

然后从开发者工具中提取 `mobile.pinduoduo.com` 的 cookie 与 `pdd_user_id`，写入 `config.json`（模板见 `config.example.json`）：

```json
{
  "cookies": {
    "api_uid": "xxx",
    "PDDAccessToken": "xxx",
    "pdd_user_id": "xxx",
    "pdd_user_uin": "xxx",
    "pdd_vds": "xxx",
    "JSESSIONID": "xxx",
    "rec_list_personal": "xxx"
  },
  "pdduid": "与 pdd_user_id 相同的数字"
}
```

> 提示：可登录后在控制台执行 `document.cookie` 获取非 httpOnly cookie，或在 Network 面板找到 `order_list_v4` 请求复制完整 cookie。推荐直接复制浏览器该域下的全部 cookie（越全越稳）。

### 2. 验证链路

```bash
uv run --with requests --with PyExecJS python pdd_orders.py test
```

返回最新订单时间即说明 cookie 与 `anti_content` 均有效。返回 0 笔订单通常是 cookie 失效，重新提取即可。

### 3. 抓取订单

```bash
uv run --with requests --with PyExecJS python pdd_orders.py fetch --year 2026
```

从最新订单向前翻页，跨出指定年份边界自动停止。原始 JSON 逐行写入 `pdd_order.txt`（重跑时旧文件自动备份为 `.bak`）。每页间隔 5.2 秒以降低风控触发概率。

### 4. 导出记账 CSV

```bash
uv run --with requests --with PyExecJS python pdd_orders.py export \
  --start 2026-06-01 --end 2026-09-01 --out 拼多多订单明细.csv
```

导出会再次调用买菜父订单接口补全买菜单金额（需 cookie 有效）。CSV 为 `utf-8-sig` 编码，Excel 直接打开中文不乱码。

## 口径说明

- **实付**：普通订单取 `order_amount`（分）；多多买菜取子单 `order_amount` 之和。先用后付未扣款的单按应付额记录，状态列可区分。
- **退款金额**：普通订单"退款成功"视为整单全额退款（=实付，退款含现金与退回优惠券）；多多买菜按子单 `fresh_order_text` 逐单判定，可精确到部分退款。
- **净支出** = 实付 − 退款。同一区间内"实付合计 − 退款合计"即为实际净花费。

## 注意事项

- `config.json`、`pdd_order.txt`、导出的 CSV 均含个人隐私，已列入 `.gitignore`，请勿提交或外发。
- cookie 有有效期，失效后重新登录提取。
- `hello.js` 是从拼多多 H5 页面提取的 `anti_content` 生成器（上游仓库提供），拼多多风控升级后可能失效；失效表现为接口返回空订单或错误，届时需要重新逆向。
- 请合理控制请求频率（脚本已内置翻页间隔），仅供个人数据导出使用。

## License

MIT

## Agent Skill

仓库附带 [skill/pinduoduo-orders](skill/pinduoduo-orders/SKILL.md)，供 ZCode / Claude / Codex 等 agent 作为技能安装使用，覆盖 cookie 提取、链路验证、抓取与导出的完整流程。安装：

```bash
cp -r skill/pinduoduo-orders ~/.agents/skills/
```
