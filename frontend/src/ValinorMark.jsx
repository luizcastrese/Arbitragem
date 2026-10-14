import { useId } from 'react'

// As Duas Árvores de Valinor: Telperion (prata) e Laurelin (ouro).
export default function ValinorMark({ size = 40, tone = 'dark', title }) {
  const uid = useId().replace(/:/g, '')
  const light = tone === 'dark'
  const silver = light ? ['#F4F7FB', '#9FB0C6'] : ['#AEBBCD', '#5F7390']
  const gold = light ? ['#F6DC95', '#C79A3A'] : ['#E2BE6A', '#9C7420']
  const silverStroke = light ? '#C9D3E0' : '#7F92AD'
  const goldStroke = light ? '#E2BE6A' : '#B8892B'
  const vein = light ? '#6E819C' : '#F6F2E8'
  const goldVein = light ? '#8A6A1F' : '#F6F2E8'
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 72 72"
      role={title ? 'img' : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      <defs>
        <linearGradient id={`${uid}s`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={silver[0]} />
          <stop offset="1" stopColor={silver[1]} />
        </linearGradient>
        <linearGradient id={`${uid}g`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={gold[0]} />
          <stop offset="1" stopColor={gold[1]} />
        </linearGradient>
      </defs>
      {light && <circle cx="26" cy="24" r="21" fill="#C9D3E0" opacity=".12" />}
      {light && <circle cx="48" cy="31" r="18" fill="#E2BE6A" opacity=".16" />}
      <path d="M26 6 C38 15 40 30 26 41 C12 30 14 15 26 6Z" fill={`url(#${uid}s)`} />
      <path d="M26 12 L26 40" stroke={vein} strokeWidth="1" strokeLinecap="round" opacity=".6" />
      <path d="M26 41 L26 53 M20 65 C24 62 26 58 26 53 C26 58 28 62 32 65" stroke={silverStroke} strokeWidth="2.2" fill="none" strokeLinecap="round" />
      <path d="M48 12 C59 20 61 34 48 45 C35 34 37 20 48 12Z" fill={`url(#${uid}g)`} />
      <path d="M48 18 L48 44" stroke={goldVein} strokeWidth="1" strokeLinecap="round" opacity=".6" />
      <path d="M48 45 L48 55 M42 65 C46 62 48 59 48 55 C48 59 50 62 54 65" stroke={goldStroke} strokeWidth="2.2" fill="none" strokeLinecap="round" />
      <path d="M8 67.5 H64" stroke={silverStroke} strokeWidth="1" strokeLinecap="round" opacity=".5" />
    </svg>
  )
}
