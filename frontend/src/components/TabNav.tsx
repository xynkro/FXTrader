export type TabKey = "dashboard" | "strategy" | "settings";

const TABS: { key: TabKey; label: string }[] = [
  { key: "dashboard", label: "Dashboard" },
  { key: "strategy", label: "Strategy" },
  { key: "settings", label: "Settings" },
];

export default function TabNav({
  active,
  onChange,
}: {
  active: TabKey;
  onChange: (k: TabKey) => void;
}) {
  return (
    <div className="border-b border-border mb-4 flex gap-1 overflow-x-auto">
      {TABS.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={
            "px-4 py-2 text-sm font-semibold border-b-2 transition-colors whitespace-nowrap " +
            (active === t.key
              ? "border-accent text-accent"
              : "border-transparent text-muted hover:text-neutral-200")
          }
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
