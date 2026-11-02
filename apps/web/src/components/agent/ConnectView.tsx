// Adapted from open-slide's agent/connect-view.tsx (MIT, Copyright (c) 2026 Yiwei Ho).
import { Check, RotateCw, Terminal } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import type { Account } from "@/lib/types";
import { cn } from "@/lib/utils";
import { PROVIDER_NAME, ProviderLogo } from "./ProviderLogo";

const LOGIN: Record<Account["provider"], string> = {
  claude: "claude auth login",
  codex: "codex login",
};

export function ConnectView({
  accounts,
  error,
  onRefresh,
}: {
  accounts: Account[];
  error: string | null;
  onRefresh: () => Promise<void>;
}) {
  const [checking, setChecking] = useState(false);
  const none = !accounts.some((account) => account.loggedIn);
  const providers: Account[] = accounts.length
    ? accounts
    : (["claude", "codex"] as const).map((provider) => ({
        id: provider,
        provider,
        label: PROVIDER_NAME[provider],
        loggedIn: false,
        models: [],
        efforts: [],
      }));
  return (
    <div className="flex flex-col gap-4 px-4 py-5">
      <div>
        <h2 className="text-[15px] font-semibold">
          {none ? "先連上你的 AI 帳號" : "帳號連線"}
        </h2>
        <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted-foreground">
          助教用的是這台電腦上已登入的 Claude Code 或 Codex，不需要 API
          金鑰，費用算在你自己的訂閱方案裡。在終端機登入後按「重新檢查」。
        </p>
      </div>
      {error && (
        <p className="rounded-[6px] bg-destructive/8 px-3 py-2 text-[12.5px] text-destructive">
          讀取帳號失敗：{error}
        </p>
      )}
      <ul className="flex flex-col gap-2">
        {providers.map((account) => (
          <li
            key={account.id}
            className="rounded-[8px] border border-border bg-card p-3 shadow-edge"
          >
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="flex items-center gap-1.5 text-[13px] font-semibold">
                  <ProviderLogo
                    provider={account.provider}
                    className="size-3.5 shrink-0"
                  />
                  {PROVIDER_NAME[account.provider]}
                </p>
                <p className="mt-0.5 truncate text-[11.5px] text-muted-foreground">
                  {account.provider === "claude"
                    ? account.plan
                      ? `${account.plan} 方案`
                      : "Claude Code"
                    : account.label}
                </p>
              </div>
              <span
                className={cn(
                  "inline-flex shrink-0 items-center gap-1 rounded-[5px] px-2 py-1 text-[11.5px] font-medium",
                  account.loggedIn
                    ? "bg-success/12 text-success"
                    : "bg-muted text-muted-foreground",
                )}
              >
                {account.loggedIn && <Check className="size-3" aria-hidden />}
                {account.loggedIn ? "已連線" : "未登入"}
              </span>
            </div>
            {!account.loggedIn && (
              <div className="mt-2.5 flex flex-col gap-1.5">
                <p className="flex items-center gap-1 text-[11.5px] text-muted-foreground">
                  <Terminal className="size-3" aria-hidden /> 在終端機執行：
                </p>
                <code className="block overflow-x-auto rounded-[5px] bg-muted px-2 py-1.5 font-mono text-[11.5px] whitespace-nowrap select-all">
                  {LOGIN[account.provider]}
                </code>
              </div>
            )}
          </li>
        ))}
      </ul>
      <Button
        size="sm"
        variant="outline"
        className="self-start"
        disabled={checking}
        onClick={async () => {
          setChecking(true);
          try {
            await onRefresh();
          } finally {
            setChecking(false);
          }
        }}
      >
        <RotateCw className={cn(checking && "animate-spin")} /> 重新檢查
      </Button>
    </div>
  );
}
