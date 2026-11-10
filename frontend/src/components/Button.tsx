import type { ReactNode } from 'react'

/** Catalogue buttons: squared, condensed caps. Approve is the one solid fill on a
 *  card; everything else is a ruled outline in the colour of its job. */
const TONES = {
  go: 'border-go bg-go text-ground hover:bg-[#74d39d] hover:border-[#74d39d]',
  claude: 'border-claude/60 text-claude hover:bg-claude/10',
  stop: 'border-stop/60 text-stop hover:bg-stop/10',
  attn: 'border-attn/70 text-attn hover:bg-attn/10',
  neutral: 'border-rule-bright text-ink hover:border-ink-dim hover:text-ink-bright',
} as const

export function Button({
  tone = 'neutral',
  onClick,
  disabled,
  children,
  small,
}: {
  tone?: keyof typeof TONES
  onClick: () => void
  disabled?: boolean
  children: ReactNode
  small?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`rounded-sm border font-label font-semibold uppercase tracking-[0.06em] transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
        small ? 'px-2.5 py-1 text-[12px]' : 'px-4 py-2 text-[13px]'
      } ${TONES[tone]}`}
    >
      {children}
    </button>
  )
}
