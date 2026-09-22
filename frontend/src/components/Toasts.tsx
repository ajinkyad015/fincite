import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";
import { useStore } from "../store";

const ICONS = {
  success: <CheckCircle2 size={14} className="text-emerald-400" />,
  info: <Info size={14} className="text-bone/70" />,
  error: <AlertTriangle size={14} className="text-red-400" />,
};

export default function Toasts() {
  const { toasts, dismissToast } = useStore();
  return (
    <div className="pointer-events-none fixed bottom-5 right-5 z-[80] flex w-[320px] flex-col gap-2">
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.div
            key={t.id}
            layout
            initial={{ opacity: 0, x: 40, scale: 0.96 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: 40, scale: 0.96 }}
            transition={{ duration: 0.24, ease: [0.32, 0.72, 0, 1] }}
            className="pointer-events-auto border border-line-dark bg-soot px-3.5 py-3 text-bone shadow-[0_20px_50px_-20px_rgba(22,19,11,0.7)]"
          >
            <div className="flex items-start gap-2.5">
              <span className="mt-0.5">{ICONS[t.kind]}</span>
              <div className="min-w-0 flex-1">
                <div className="text-[12.5px] font-medium leading-tight">{t.title}</div>
                {t.body && (
                  <div className="mt-1 text-[11px] leading-snug text-bone/60">{t.body}</div>
                )}
                {t.action && (
                  <button
                    type="button"
                    onClick={() => {
                      t.action!.run();
                      dismissToast(t.id);
                    }}
                    className="mt-2 border border-line-dark px-2 py-1 font-mono text-[9.5px] uppercase tracking-[0.1em] text-bone/80 transition-colors hover:border-accent hover:bg-accent hover:text-paper"
                  >
                    {t.action.label}
                  </button>
                )}
              </div>
              <button
                type="button"
                aria-label="Dismiss"
                onClick={() => dismissToast(t.id)}
                className="text-bone/40 transition-colors hover:text-bone"
              >
                <X size={12} />
              </button>
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
