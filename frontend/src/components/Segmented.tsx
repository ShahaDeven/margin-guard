/** A small set of mutually exclusive choices, as one control. */
export function Segmented<T extends string>({ items, value, onChange, label }: {
  items: { id: T; label: string }[]; value: T; onChange: (v: T) => void; label: string
}) {
  return (
    <div className="inline-flex rounded-sm border border-rule-bright p-0.5" role="group" aria-label={label}>
      {items.map((x) => (
        <button key={x.id} type="button" aria-pressed={value === x.id} onClick={() => onChange(x.id)}
          className={`rounded-[4px] px-3 py-1.5 text-sm transition-colors ${value === x.id ? 'bg-nav-active font-semibold text-go-soft' : 'text-ink hover:text-go-soft'}`}>
          {x.label}
        </button>
      ))}
    </div>
  )
}
