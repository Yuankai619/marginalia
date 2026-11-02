# Marginalia

[![CI](https://github.com/Yuankai619/marginalia/actions/workflows/ci.yml/badge.svg)](https://github.com/Yuankai619/marginalia/actions/workflows/ci.yml)

投影片在左、筆記在右。把上課簡報和錄影丟進來，Marginalia 會自動對齊「哪段影片在講哪一頁」、在本機轉出逐字稿，
再用你自己電腦上已登入的 Claude（訂閱額度，不用 API key）逐頁寫成筆記，每一段都附可以跳回影片的時間點。

- 一部影片講不完一份簡報、或一部影片橫跨兩份簡報都沒關係：對齊是逐格比對畫面上的投影片。
- 筆記可以在本機直接編輯；`pnpm build` 產生唯讀的靜態網站方便部署。
- 內建 agent：問答（知道你停在哪一頁、圈了哪一塊）、口試模式、筆記審稿。

從其他裝置開啟開發介面時，建議綁定這台電腦的 Tailscale IP，例如：

```sh
pnpm dev -- --host 100.81.100.96
```

將範例位址換成自己的 Tailscale IP，再從同一 tailnet 的裝置開啟 `http://100.81.100.96:5173`。
不要綁定 `0.0.0.0` 或公網 IP：開發介面沒有登入保護，會透過 proxy 暴露教材與本機 Agent。
`--host` 只傳給 Vite，後端仍只監聽 `127.0.0.1:8765`；`/api` 與 `/files` 的 proxy 會重寫 Host，讓後端 TrustedHost 驗證正常運作。

開發說明見 `AGENTS.md` 和 `docs/architecture.md`。
