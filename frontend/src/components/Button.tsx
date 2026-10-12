import type { ReactNode } from 'react'

const TONES = {
  cyan: 'border-cyan/50 bg-cyan/10 text-cyan hover:bg-cyan/20',
  purple: 'border-purple/50 bg-purple/10 text-purple hover:bg-purple/20',
  signal: 'border-signal/50 bg-signal/10 text-signal hover:bg-signal/20',
  hiviz: 'border-hiviz/50 bg-hiviz/10 text-hiviz hover:bg-hiviz/20',
  neutral: 'border-line bg-panel text-silver hover:border-line-bright',
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
      className={`rounded-md border font-mono tracking-wide transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
        small ? 'px-2.5 py-1 text-[11px]' : 'px-4 py-2 text-xs'
      } ${TONES[tone]}`}
    >
      {children}
    </button>
  )
}
