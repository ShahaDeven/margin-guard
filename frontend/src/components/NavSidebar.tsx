import { useEffect, useState } from 'react'

import { api } from '../lib/api'
import type { Lane } from '../lib/api'
import type { Overview, ShopListing } from '../lib/types'

type Item = { id: Lane; label: string; count?: (ov: Overview) => number }

/** Grouped by what the person is doing: working the queue, checking before a quote,
 *  reading reports, or setting the shop up. */
const GROUPS: { label: string; items: Item[] }[] = [
  {
    label: 'Queue',
    items: [
      { id: 'decide', label: 'To decide', count: (ov) => ov.needs_you },
      { id: 'rules', label: 'Settled by rules', count: (ov) => ov.rule_pending },
      { id: 'done', label: 'Done' },
    ],
  },
  { label: 'Before you quote', items: [{ id: 'quote', label: 'Quote check' }] },
  {
    label: 'Reports',
    items: [
      { id: 'leakage', label: 'Leakage' },
      { id: 'outcomes', label: 'Outcomes' },
    ],
  },
  {
    label: 'Setup',
    items: [
      { id: 'inbox', label: 'Supplier inbox' },
      { id: 'imports', label: 'Imports' },
      { id: 'erp', label: 'ERP connection' },
      { id: 'data', label: 'Shop data' },
    ],
  },
]

/** The left sidebar: brand, the lanes in four groups, and the sample-shop note with the
 *  way into the demo controls. On narrow screens it stacks above the content. */
export function NavSidebar({ lane, setLane, ov, busy, onOpenDemo }: {
  lane: Lane
  setLane: (l: Lane) => void
  ov: Overview | null
  busy: boolean
  onOpenDemo: () => void
}) {
  return (
    <nav
      aria-label="Main"
      className="flex shrink-0 flex-col gap-5 border-b border-rule bg-sheet px-3.5 py-5 lg:sticky lg:top-0 lg:h-screen lg:w-[230px] lg:gap-[22px] lg:overflow-y-auto lg:border-b-0 lg:border-r"
    >
      <div className="px-2.5 text-base font-bold text-ink">Margin Guard</div>
      <NavItem item={{ id: 'home', label: 'Home' }} lane={lane} setLane={setLane} ov={ov} />

      <div className="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-4 lg:flex lg:flex-col lg:gap-[22px]">
        {GROUPS.map((g) => (
          <div key={g.label} className="flex flex-col gap-0.5">
            <div className="px-2.5 pb-1.5 text-xs text-ink-dim">{g.label}</div>
            {g.items.map((it) => <NavItem key={it.id} item={it} lane={lane} setLane={setLane} ov={ov} />)}
          </div>
        ))}
      </div>

      <div className="rounded-sm border border-dashed border-rule-bright px-2.5 py-3 text-[13px] text-ink-dim lg:mt-auto">
        <ShopSwitch busy={busy} />
        <button type="button" onClick={onOpenDemo} className="text-go hover:text-go-soft">Open demo controls</button>
        {/* Only while the agents run: approving or sending can take a few seconds to show up. */}
        <p className={`mt-1 items-center gap-2 text-attn ${busy ? 'flex' : 'hidden'}`} role="status">
          <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-attn mg-breathe" />
          {busy ? 'Agents working…' : ''}
        </p>
      </div>
    </nav>
  )
}

function NavItem({ item, lane, setLane, ov }: { item: Item; lane: Lane; setLane: (l: Lane) => void; ov: Overview | null }) {
  const on = lane === item.id
  const n = ov && item.count ? item.count(ov) : null
  return (
    <button
      type="button"
      aria-current={on ? 'page' : undefined}
      onClick={() => setLane(item.id)}
      className={`flex items-center justify-between gap-2 rounded-sm px-2.5 py-[9px] text-left transition-colors ${
        on ? 'bg-nav-active font-semibold text-go-soft' : 'text-ink hover:bg-nav-active/60'
      }`}
    >
      {item.label}
      {n != null ? <span className={on ? '' : 'text-ink-dim'}>{n}</span> : null}
    </button>
  )
}

/** Which shop the console is on, and the way to another. The sample shop is synthetic;
 *  a shop loaded from CSVs (Imports) is the person's own. */
function ShopSwitch({ busy }: { busy: boolean }) {
  const [list, setList] = useState<ShopListing | null>(null)
  useEffect(() => { api.shops().then(setList).catch(() => {}) }, [])
  const current = list?.shops.find((s) => s.id === list.current)
  const go = (id: string) => api.switchShop(id).then(() => { window.location.hash = 'home'; window.location.reload() })

  return (
    <>
      <p>{!current || current.synthetic ? 'Sample shop, synthetic data.' : <><span className="text-ink">{current.name}</span>, loaded from CSV.</>}</p>
      {list && list.shops.length > 1 ? (
        <label className="mb-1 mt-1.5 block">
          <span className="sr-only">Switch shop</span>
          <select value={list.current ?? ''} disabled={busy} onChange={(e) => go(e.target.value)}
            className="w-full rounded-sm border border-rule-bright bg-ground px-2 py-1.5 text-[13px] text-ink outline-none focus:border-go">
            {list.current ? null : <option value="">Another database</option>}
            {list.shops.map((s) => <option key={s.id} value={s.id}>{s.synthetic ? 'Sample shop' : s.name}</option>)}
          </select>
        </label>
      ) : null}
    </>
  )
}
