import { COMPANY_HUE } from "../lib/mockData";

export default function Monogram({
  symbol,
  size = 30,
  className = "",
}: {
  symbol: string;
  size?: number;
  className?: string;
}) {
  const hue = COMPANY_HUE[symbol] ?? COMPANY_HUE.DEFAULT;
  return (
    <span
      className={`flex shrink-0 select-none items-center justify-center font-display font-semibold text-paper ${className}`}
      style={{
        width: size,
        height: size,
        background: hue,
        fontSize: Math.max(10, size * 0.34),
        letterSpacing: "0.02em",
      }}
    >
      {symbol.slice(0, 2)}
    </span>
  );
}
