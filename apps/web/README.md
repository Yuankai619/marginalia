# Web 介面

`pnpm dev` 使用 local API；明確指定 `VITE_MARGINALIA_MODE=mock` 才會使用示範資料與假 Agent 回覆。
`pnpm build` 固定使用 static adapter，只讀 `/data/...` 與公開投影片資產並隱藏修改、生成與 Agent。
靜態課程 JSON／圖片匯出器由 K5 提供；本 PR 的 dist 只有介面資產，完整部署仍須加入匯出資料。

## 驗證

先啟動 Vite 與建置預覽（不同終端）：

```sh
pnpm --filter @marginalia/web dev --host 127.0.0.1 --port 5173
pnpm build
pnpm --filter @marginalia/web exec vite preview --host 127.0.0.1 --port 5191
```

使用環境既有的 Playwright 執行，不新增專案依賴；若模組在別處，透過 `NODE_PATH` 指向其 node_modules：

```sh
node scripts/web-regression.cjs
```

可用 `WEB_LOCAL_URL`／`WEB_STATIC_URL` 改測試位址，`CHROME_PATH` 改瀏覽器路徑。
測試攔截所有 API，以極小合成資料驗證 local/static HTTP 形狀、草稿保護、圖片與影片來源、圈選和選取文字、Agent SSE、multipart 上傳、掃描、工作 SSE 重連，以及 375px 手機版。
它不會對真實課程建立工作或呼叫模型。`WEB_SCREENSHOTS=<目錄>` 可另存桌面與手機截圖。
`screenshots/` 只含測試生成的畫面；真實課程驗證產物保留在 git 忽略的 `.orch/`。
