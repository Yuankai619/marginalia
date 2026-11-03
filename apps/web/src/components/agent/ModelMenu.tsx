// Adapted from open-slide's agent-panel ModelMenu (MIT, Copyright (c) 2026 Yiwei Ho).
import { Check, ChevronDown, Settings2 } from "lucide-react";
import { useState } from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Segmented } from "@/components/ui/segmented";
import type { Account } from "@/lib/types";
import { cn } from "@/lib/utils";
import { PROVIDER_NAME, ProviderLogo } from "./ProviderLogo";
import { type Choice, EFFORTS } from "./use-chat";

export function ModelMenu({
  accounts,
  account,
  model,
  effort,
  onChoose,
  onManage,
  disabled,
}: {
  accounts: Account[];
  account: Account | null;
  model: { id: string; label: string } | null;
  effort: string;
  onChoose: (choice: Partial<Choice>) => void;
  onManage: () => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ready = accounts.filter((item) => item.loggedIn);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        disabled={disabled}
        className="flex h-7 min-w-0 items-center gap-1.5 rounded-[5px] px-2 text-[12.5px] font-medium outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/30 disabled:opacity-60 aria-expanded:bg-muted"
      >
        {account ? (
          <ProviderLogo
            provider={account.provider}
            className="size-3.5 shrink-0"
          />
        ) : (
          <span
            aria-hidden
            className="size-1.5 rounded-full bg-muted-foreground/50"
          />
        )}
        <span className="truncate">
          {model
            ? `${account?.provider === "claude" ? "Claude " : ""}${model.label}`
            : "AI 助教"}
        </span>
        {effort && (
          <span className="shrink-0 font-normal text-muted-foreground">
            {EFFORTS[effort] ?? effort}
          </span>
        )}
        <ChevronDown
          className="size-3 shrink-0 text-muted-foreground"
          aria-hidden
        />
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[288px] p-1.5">
        {ready.length > 1 && (
          <div className="mb-1.5 grid gap-px">
            <p className="px-2 pt-1 pb-1 text-[11.5px] font-medium text-muted-foreground">
              帳號
            </p>
            {ready.map((item) => (
              <button
                key={item.id}
                type="button"
                aria-pressed={item.id === account?.id}
                onClick={() => onChoose({ account: item.id })}
                className="flex h-8 items-center gap-2 rounded-[5px] px-2 text-left text-[12.5px] outline-none hover:bg-muted focus-visible:bg-muted"
              >
                <ProviderLogo
                  provider={item.provider}
                  className="size-3.5 shrink-0"
                />
                <span className="min-w-0 flex-1 truncate">
                  {PROVIDER_NAME[item.provider]}
                  <span className="ml-1.5 text-muted-foreground">
                    {item.provider === "claude"
                      ? item.plan
                        ? `${item.plan} 方案`
                        : ""
                      : item.label}
                  </span>
                </span>
                {item.id === account?.id && (
                  <Check className="size-3.5 shrink-0" aria-hidden />
                )}
              </button>
            ))}
          </div>
        )}
        {account && (
          <div
            className={cn(
              "grid gap-px",
              ready.length > 1 && "border-t border-hairline pt-1.5",
            )}
          >
            <p className="px-2 pt-1 pb-1 text-[11.5px] font-medium text-muted-foreground">
              模型
            </p>
            {account.models.map((item) => (
              <button
                key={item.id}
                type="button"
                aria-pressed={item.id === model?.id}
                onClick={() => onChoose({ model: item.id })}
                className={cn(
                  "flex h-7 items-center justify-between gap-2 rounded-[5px] px-2 text-left text-[12.5px] outline-none hover:bg-muted focus-visible:bg-muted",
                  item.id === model?.id && "font-medium",
                )}
              >
                <span className="truncate">{item.label}</span>
                {item.id === model?.id && (
                  <Check className="size-3.5 shrink-0" aria-hidden />
                )}
              </button>
            ))}
          </div>
        )}
        {account && account.efforts.length > 0 && (
          <div className="mt-1.5 border-t border-hairline px-1 pt-2 pb-1">
            <p className="mb-1.5 px-1 text-[11.5px] font-medium text-muted-foreground">
              思考深度
            </p>
            <Segmented
              stretch
              options={account.efforts.map((item) => ({
                id: item,
                label: EFFORTS[item] ?? item,
              }))}
              value={effort}
              onChange={(item) => onChoose({ effort: item })}
            />
            <p className="mt-1.5 px-1 text-[11px] leading-snug text-muted-foreground">
              越深入回答越仔細，但會比較慢、用掉比較多額度。
            </p>
          </div>
        )}
        <div className="mt-1.5 border-t border-hairline pt-1.5">
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              onManage();
            }}
            className="flex h-7 w-full items-center gap-2 rounded-[5px] px-2 text-[12.5px] text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:bg-muted"
          >
            <Settings2 className="size-3.5" /> 管理帳號連線
          </button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
