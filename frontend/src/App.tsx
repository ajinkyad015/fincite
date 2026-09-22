import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Menu } from "lucide-react";
import { StoreProvider, useStore } from "./store";
import Ticker from "./components/Ticker";
import Sidebar from "./components/Sidebar";
import ChatView from "./components/ChatView";
import LibraryView from "./components/LibraryView";
import SourceDrawer from "./components/SourceDrawer";
import Toasts from "./components/Toasts";

function Shell() {
  const { booted, boot, view, mobileNav, setMobileNav, checkHealth, health } = useStore();
  const [splashing, setSplashing] = useState(true);

  useEffect(() => {
    let alive = true;
    const minSplash = new Promise((r) => setTimeout(r, 1500));
    void Promise.all([boot(), minSplash]).then(() => alive && setSplashing(false));
    return () => {
      alive = false;
    };
  }, [boot]);

  // periodic health probe → GET /api/health/
  useEffect(() => {
    if (!booted) return;
    const t = window.setInterval(() => void checkHealth(), 25_000);
    return () => window.clearInterval(t);
  }, [booted, checkHealth]);

  return (
    <div className="flex h-full flex-col overflow-hidden bg-bone text-ink">
      <Ticker />

      <div className="flex min-h-0 flex-1">
        {/* desktop rail */}
        <aside className="hidden w-[268px] shrink-0 border-r border-line-dark lg:block">
          <Sidebar />
        </aside>

        {/* mobile rail */}
        <AnimatePresence>
          {mobileNav && (
            <>
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="fixed inset-0 z-40 bg-ink/40 backdrop-blur-[1px] lg:hidden"
                onClick={() => setMobileNav(false)}
              />
              <motion.aside
                initial={{ x: -290 }}
                animate={{ x: 0 }}
                exit={{ x: -290 }}
                transition={{ duration: 0.28, ease: [0.32, 0.72, 0, 1] }}
                className="fixed inset-y-0 left-0 z-50 w-[280px] lg:hidden"
              >
                <Sidebar />
              </motion.aside>
            </>
          )}
        </AnimatePresence>

        {/* main */}
        <main className="relative flex min-w-0 flex-1 flex-col">
          {/* mobile top bar */}
          <div className="flex h-11 shrink-0 items-center gap-2 border-b border-line bg-bone/90 px-3 backdrop-blur-sm lg:hidden">
            <button
              type="button"
              onClick={() => setMobileNav(true)}
              aria-label="Open navigation"
              className="flex h-8 w-8 items-center justify-center border border-line bg-paper text-ink"
            >
              <Menu size={15} />
            </button>
            <span className="flex items-center gap-1.5">
              <span className="flex h-5 w-5 items-center justify-center bg-accent font-display text-[13px] font-semibold italic text-paper">
                f
              </span>
              <span className="font-display text-[15px] font-semibold">Fincite</span>
            </span>
            <span
              className={`ml-auto h-1.5 w-1.5 ${
                health?.status === "healthy" ? "bg-emerald-500" : "bg-moss/40"
              }`}
            />
          </div>

          <AnimatePresence mode="wait">
            <motion.div
              key={view}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.22, ease: [0.32, 0.72, 0, 1] }}
              className="flex min-h-0 flex-1 flex-col"
            >
              {view === "chat" ? <ChatView /> : <LibraryView />}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>

      <SourceDrawer />
      <Toasts />

      {/* boot splash */}
      <AnimatePresence>
        {splashing && <Splash />}
      </AnimatePresence>
    </div>
  );
}

function Splash() {
  return (
    <motion.div
      exit={{ opacity: 0, transition: { duration: 0.5, ease: "easeInOut" } }}
      className="fixed inset-0 z-[100] flex flex-col items-center justify-center bg-soot"
    >
      <div className="flex items-center gap-3">
        <motion.span
          initial={{ scale: 0.6, opacity: 0, rotate: -8 }}
          animate={{ scale: 1, opacity: 1, rotate: 0 }}
          transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
          className="flex h-11 w-11 items-center justify-center bg-accent font-display text-[28px] font-semibold italic text-paper"
        >
          f
        </motion.span>
        <div className="flex overflow-hidden">
          {"Fincite".split("").map((ch, i) => (
            <motion.span
              key={i}
              initial={{ y: 34, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              transition={{ delay: 0.12 + i * 0.05, duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
              className="font-display text-[36px] font-semibold tracking-tight text-bone"
            >
              {ch}
            </motion.span>
          ))}
        </div>
      </div>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.5 }}
        className="mt-5 font-mono text-[9.5px] uppercase tracking-[0.3em] text-bone/45"
      >
        warming the retrieval index
      </motion.div>
      <motion.div
        initial={{ scaleX: 0 }}
        animate={{ scaleX: 1 }}
        transition={{ duration: 1.1, delay: 0.3, ease: [0.65, 0, 0.35, 1] }}
        className="mt-3 h-px w-44 origin-left bg-accent"
      />
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.85 }}
        className="mt-3 font-mono text-[9px] text-bone/25"
      >
        nse filings · annual reports · concalls
      </motion.div>
    </motion.div>
  );
}

export default function App() {
  return (
    <StoreProvider>
      <Shell />
    </StoreProvider>
  );
}
