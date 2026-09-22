import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { TICKS } from "../lib/mockData";

export default function Ticker() {
  const items = [...TICKS, ...TICKS];
  return (
    <div className="relative z-30 h-7 shrink-0 overflow-hidden border-b border-line-dark bg-soot text-bone/80">
      <div className="flex h-full w-max animate-marquee items-center">
        {items.map((t, i) => {
          const up = t.change >= 0;
          return (
            <span
              key={i}
              className="flex h-full items-center gap-2 border-r border-line-dark/60 px-4 font-mono text-[10px] tracking-wide"
            >
              <span className="text-bone/50">{t.symbol}</span>
              <span className="tnum text-bone/90">{t.price}</span>
              <span
                className={`tnum flex items-center gap-0.5 ${
                  up ? "text-emerald-400/90" : "text-red-400/90"
                }`}
              >
                {up ? <ArrowUpRight size={9} strokeWidth={2.4} /> : <ArrowDownRight size={9} strokeWidth={2.4} />}
                {Math.abs(t.change).toFixed(2)}%
              </span>
            </span>
          );
        })}
      </div>
      <div className="pointer-events-none absolute inset-y-0 left-0 w-16 bg-gradient-to-r from-soot to-transparent" />
      <div className="pointer-events-none absolute inset-y-0 right-0 w-16 bg-gradient-to-l from-soot to-transparent" />
    </div>
  );
}
