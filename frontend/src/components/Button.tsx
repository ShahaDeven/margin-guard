import type { ReactNode } from 'react'

/** Sentence-case buttons. `go` is the one filled button on a screen (Approve on Decide);
 *  everything else is an outline in the colour of its job. */
const TONES = {
  go: 'border-go bg-go text-ground hover:bg-go-soft hover:border-go-soft',
  claude: 'border-rule-bright text-ink hover:border-ink-dim',
  stop: 'border-stop/60 text-stop hover:bg-stop/10',
  attn: 'border-attn/70 text-attn hover:bg-attn/10',
  neutral: 'border-rule-bright bg-sheet text-ink hover:border-ink-dim',
} as const

export function Button({
  tone = 'neutral',
  onClick,
  disabled,
  children,
  small,
  className = '',
}: {
  tone?: keyof typeof TONES
  onClick: () => void
  disabled?: boolean
  children: ReactNode
  small?: boolean
  className?: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`rounded-sm border font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
        small ? 'px-2.5 py-1 text-[13px]' : 'min-h-11 px-3.5 text-sm'
      } ${TONES[tone]} ${className}`}
    >
      {children}
    </button>
  )
}
