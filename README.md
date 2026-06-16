# EasyCollect

EasyCollect 是一个面向跨境电商运营的商品采集与上架资产管理工具。当前版本已经从早期的“采集后立即下载 ZIP”升级为“采集箱 Inbox Model”：浏览器插件负责从 1688 / Shopee 商品页采集并入库，独立 Dashboard 负责商品管理、批量导出和后续发布扩展。

## 核心能力

- Chrome MV3 扩展：在 1688 和 Shopee 商品页注入悬浮采集面板。
- 双模式采集：
  - 极速采集：只做结构化提取、清洗和入库。
  - AI 深度采集：采集后调用 OpenAI 兼容模型生成优化文案，失败时自动降级。
- 多平台解析：
  - 1688：支持 `FE_GLOBALS` 等复杂页面数据结构，递归嗅探 SKU、价格和变体图。
  - Shopee：支持 SSR JSON、网络拦截、DOM 可见价格兜底、单规格和多规格模型解析。
- 商品库 Dashboard：独立扩展页面，基于 Vue 3 + Element Plus。
- SQLite 本地商品库：保存采集后的商品、平台、价格、图片、SKU 和原始数据；同平台同商品重复采集会覆盖旧记录。
- 批量管理：支持平台 Tab 过滤、批量导出、批量删除、一键清空。
- ERP 资产导出：生成 Shopee 批量上架 CSV、主图包、变体图包和商品文案。
- 防御式 LLM 调用：主备双通道、15 秒超时、Pydantic 校验失败自动兜底。

## 技术栈

### 扩展端

- Vue 3
- Vite
- CRXJS
- Chrome Manifest V3
- Element Plus
- TypeScript

### 后端

- Python 3.12+
- FastAPI
- Uvicorn
- SQLite
- Pydantic
- HTTPX
- OpenAI-compatible Async SDK

## 目录结构

```text
EasyCollect/
  extension/
    dashboard.html
    src/
      background/service-worker.ts
      content/index.ts
      content/interceptor.ts
      pages/dashboard/Dashboard.vue
      manifest.ts
  server/
    app/
      api/
        export.py
        optimize.py
        shopee.py
      product_store.py
    main.py
    test_1688_sku.py
    requirements.txt
```

## 当前数据流

```text
1688 / Shopee 商品页
  -> Content Script 悬浮按钮
  -> Service Worker 在 MAIN world 提取页面数据
  -> FastAPI /api/collect
  -> 解析器标准化 title / base_price / main_images / sku_list
  -> 可选 AI 文案优化
  -> SQLite 商品库
  -> Dashboard 展示、筛选、删除、批量导出
```

## 快速启动

### 1. 启动后端

```powershell
cd E:\e-commerce-project\EasyCollect\server
& .\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

预期返回：

```json
{
  "status": "ok",
  "service": "easycollect-server",
  "static_url": "/static"
}
```

如果需要首次创建虚拟环境：

```powershell
cd E:\e-commerce-project\EasyCollect\server
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. 启动扩展开发环境

```powershell
cd E:\e-commerce-project\EasyCollect\extension
pnpm install
pnpm run dev
```

生产构建：

```powershell
cd E:\e-commerce-project\EasyCollect\extension
pnpm run build
```

然后在 `chrome://extensions` 打开开发者模式，加载 `extension/dist`。

当修改扩展代码后，请执行：

1. 在 `chrome://extensions` 刷新 EasyCollect。
2. 回到 1688 / Shopee 商品页按 `F5`。
3. 清除旧错误中的 `Extension context invalidated`。

## 环境变量

复制 `server/.env.example` 到 `server/.env`，并填写真实配置。

```env
PRIMARY_API_KEY=
PRIMARY_BASE_URL=
PRIMARY_MODEL_NAME=gpt-4o

FALLBACK_API_KEY=
FALLBACK_BASE_URL=
FALLBACK_MODEL_NAME=deepseek-chat

SHOPEE_PARTNER_ID=
SHOPEE_PARTNER_KEY=
SHOPEE_SHOP_ID=
SHOPEE_ACCESS_TOKEN=
SHOPEE_ENV=test
```

缺少 LLM Key 时，极速采集仍可正常使用；AI 深度采集会走安全降级。

## 主要 API

- `GET /health`：后端健康检查。
- `POST /api/collect`：接收扩展采集数据，解析并入库。
- `GET /api/products?platform=1688|shopee`：商品库列表，支持平台过滤。
- `DELETE /api/products/{product_id}`：删除单个商品。
- `DELETE /api/products/bulk`：批量删除商品。
- `DELETE /api/products/clear`：清空商品库。
- `POST /api/export/bulk`：按商品 ID 批量生成 ZIP 导出包。
- `POST /api/optimize`：对缓存商品执行 AI 文案优化。

## 商品库去重策略

商品入库时会生成稳定的 `dedupe_key`。如果用户重复采集同一件商品，系统不会新增重复行，而是覆盖原商品记录的最新数据，保证 Dashboard 始终展示最新解析结果。

去重优先级：

1. 平台 + 标准化商品 URL。
2. Shopee URL 会优先提取 `-i.shopid.itemid`，忽略标题 slug 和追踪参数。
3. 1688 / 其他平台保留路径与稳定查询参数，如 `offerId`。
4. 如果没有 URL，则使用平台 + 标题 + 首图作为兜底指纹。

旧 SQLite 数据库启动时会自动补齐 `dedupe_key`，并清理同一 key 下的历史重复记录，只保留 `updated_at` 最新的一条。

## 1688 SKU 图片排查

项目内置脱机嗅探脚本，用于分析最新 `raw_payload.json` 中真实的 SKU 和图片节点：

```powershell
cd E:\e-commerce-project\EasyCollect\server
& .\.venv\Scripts\python.exe .\test_1688_sku.py
```

该脚本会打印：

- `globalData` 命中路径
- `skuModel` 命中路径
- 所有递归发现的 `skuProps`
- 所有递归发现的 `skuMap / skuInfoMap`
- 疑似图片字段，如 `imageUrl`、`imageURI`、`skuImageURI`

如果看到 `[MaxDepth]`，说明前端序列化仍然截断了深层数据；当前版本已经改为 1688 精准提纯 payload，正常重新刷新扩展和页面后不应再出现。

## Shopee 价格与 SKU 归一化

Shopee 的商品价格可能出现在多个位置，甚至只显示在页面 DOM 中。当前版本采用分层兜底策略：

```text
API item/models 价格
  -> models/price_stocks 动态倒推
  -> price_min / price_max 区间
  -> price_before_discount
  -> DOM 可见文本价格，如 RM5.40
```

前端会在 Shopee 页面读取可见价格文本，并把它放进采集 payload：

```json
{
  "platform": "shopee",
  "dom_price": "RM5.40"
}
```

后端会将其标准化为：

```text
RM5.40 -> 5.40
RM5.40 - RM10.00 -> 5.40-10.00
```

SKU 解析采用原子化去重：

- 优先使用 `modelid / model_id / sku_id` 作为唯一键。
- 没有 ID 时使用 `tier_index` 组合，例如 `0_1`。
- 最后按 `spec_name` 归并重复行。
- 导出 Shopee CSV 前会再次按规格名去重，避免历史脏数据污染导出。

如果 Shopee 页面仍然价格为空，请优先确认：

1. 扩展已在 `chrome://extensions` 刷新。
2. Shopee 商品页已按 `F5` 重新加载。
3. 页面上肉眼可见 `RM` 或 `MYR` 价格。
4. 重新采集后再查看 Dashboard 中的新入库记录。

## 运行时文件

以下文件为本地运行产物，不提交到 Git：

- `server/.env`
- `server/static/cache_data/`
- `server/static/exports/`
- `server/.venv/`
- `extension/node_modules/`
- `extension/dist/`

## 常见问题

### Extension context invalidated

这是 Chrome 扩展热更新后的旧页面上下文失效。处理方式：

1. `chrome://extensions` 刷新 EasyCollect。
2. 清除扩展错误。
3. 商品页面按 `F5`。

### 后端端口被占用

查看 8000 端口：

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen
```

启动后端：

```powershell
cd E:\e-commerce-project\EasyCollect\server
& .\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

### Dashboard 打不开

Dashboard 必须由 Service Worker 使用 `chrome.tabs.create` 打开，不能从目标网页直接 `window.open(chrome-extension://...)`。当前版本已经通过 `OPEN_DASHBOARD` 消息修复。

## 验证命令

后端编译检查：

```powershell
cd E:\e-commerce-project\EasyCollect\server
& .\.venv\Scripts\python.exe -m py_compile main.py app\api\export.py app\product_store.py
```

扩展构建：

```powershell
cd E:\e-commerce-project\EasyCollect\extension
pnpm run build
```

## 当前状态

EasyCollect 当前已经具备一个本地 MVP ERP 闭环：

1. 商品页采集。
2. 结构化解析。
3. 本地商品库管理。
4. 平台隔离视图。
5. 批量导出 ZIP / CSV。
6. AI 文案优化兜底链路。
7. Shopee DOM 价格兜底与 SKU 去重归一化。
8. 商品库同商品重复采集自动覆盖。

后续可以继续扩展商品编辑、AI 单品重写、Shopee 模板校验、图片水印处理和真实 OpenAPI 发布。
