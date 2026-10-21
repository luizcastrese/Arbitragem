import { useId } from 'react'

// As Duas Árvores de Valinor: Telperion (prata) e Laurelin (ouro).
// tone="light" é para fundos claros; tone="dark", para fundos escuros.
export default function ValinorMark({ size = 40, tone = 'light', title }) {
  const uid = useId().replace(/:/g, '')
  const dark = tone === 'dark'
  const silver = dark ? ['#E6EDF6', '#8FA5C4'] : ['#C5D2E3', '#6F87A8']
  const gold = dark ? ['#F6DC95', '#C79A3A'] : ['#F2D68A', '#C08F2E']
  const silverTrunk = dark ? '#B9C7DA' : '#6F87A8'
  const goldTrunk = dark ? '#E2BE6A' : '#B8892B'
  const separator = dark ? '#0F1B2D' : '#FAF7F0'
  const vein = dark ? '#0F1B2D' : '#FFFFFF'
  const veinOpacity = dark ? 0.28 : 0.6
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
      <path d="M24 4 C40 14 44 34 24 50 C4 34 8 14 24 4Z" fill={`url(#${uid}s)`} />
      <path d="M24 12 V46" stroke={vein} strokeOpacity={veinOpacity} strokeWidth="1.6" strokeLinecap="round" />
      <path d="M24 50 V63" stroke={silverTrunk} strokeWidth="3" strokeLinecap="round" />
      <path d="M48 8 C65 19 68 40 48 56 C28 40 31 19 48 8Z" fill={`url(#${uid}g)`} stroke={separator} strokeWidth="2" />
      <path d="M48 17 V52" stroke={vein} strokeOpacity={veinOpacity} strokeWidth="1.6" strokeLinecap="round" />
      <path d="M48 56 V63" stroke={goldTrunk} strokeWidth="3" strokeLinecap="round" />
      <path d="M12 66.5 H60" stroke={silverTrunk} strokeOpacity=".6" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

// Ilustração da abertura: as duas árvores em traço fino, sobre fundo claro.
export function HeroArt() {
  const uid = useId().replace(/:/g, '')
  return (
    <svg viewBox="0 0 520 620" focusable="false">
      <defs>
        <linearGradient id={`${uid}s`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#A9BBD4" stopOpacity=".62" />
          <stop offset="1" stopColor="#A9BBD4" stopOpacity=".1" />
        </linearGradient>
        <linearGradient id={`${uid}g`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#F2D68A" stopOpacity=".85" />
          <stop offset="1" stopColor="#F2D68A" stopOpacity=".16" />
        </linearGradient>
      </defs>
      <circle cx="190" cy="280" r="150" fill="none" stroke="#0F1B2D" strokeOpacity=".08" />
      <circle cx="360" cy="220" r="165" fill="none" stroke="#B8892B" strokeOpacity=".22" />
      <circle cx="275" cy="250" r="235" fill="none" stroke="#0F1B2D" strokeOpacity=".05" />
      {/* Telperion */}
      <path d="M190 150 C290 230 300 340 190 410 C80 340 90 230 190 150Z" fill={`url(#${uid}s)`} stroke="#6F87A8" strokeWidth="1.4" />
      <path d="M190 192 C258 246 262 328 190 378 C118 328 122 246 190 192Z" fill="none" stroke="#FFFFFF" strokeWidth="1.2" strokeOpacity=".7" />
      <path d="M190 234 C226 266 228 312 190 345 C152 312 154 266 190 234Z" fill="none" stroke="#FFFFFF" strokeWidth="1.2" strokeOpacity=".6" />
      <path d="M190 166 L190 404" stroke="#FFFFFF" strokeWidth="1.4" strokeOpacity=".8" strokeLinecap="round" />
      <path d="M190 410 L190 525 M146 585 C172 568 190 548 190 525 C190 548 208 568 234 585" fill="none" stroke="#6F87A8" strokeWidth="2" strokeLinecap="round" />
      {/* Laurelin */}
      <path d="M360 60 C470 150 482 285 360 372 C238 285 250 150 360 60Z" fill={`url(#${uid}g)`} stroke="#B8892B" strokeWidth="1.4" />
      <path d="M360 108 C438 172 444 270 360 332 C276 270 282 172 360 108Z" fill="none" stroke="#FFFFFF" strokeWidth="1.2" strokeOpacity=".75" />
      <path d="M360 154 C402 192 404 252 360 290 C316 252 318 192 360 154Z" fill="none" stroke="#FFFFFF" strokeWidth="1.2" strokeOpacity=".65" />
      <path d="M360 76 L360 366" stroke="#FFFFFF" strokeWidth="1.4" strokeOpacity=".85" strokeLinecap="round" />
      <path d="M360 372 L360 525 M316 585 C342 568 360 548 360 525 C360 548 378 568 404 585" fill="none" stroke="#B8892B" strokeWidth="2" strokeLinecap="round" />
      <path d="M36 590 H484" stroke="#0F1B2D" strokeOpacity=".18" />
      <circle cx="62" cy="118" r="2" fill="#6F87A8" fillOpacity=".7" />
      <circle cx="104" cy="52" r="1.5" fill="#6F87A8" fillOpacity=".5" />
      <circle cx="478" cy="44" r="2" fill="#B8892B" fillOpacity=".8" />
      <circle cx="500" cy="190" r="1.5" fill="#B8892B" fillOpacity=".6" />
      <circle cx="44" cy="330" r="1.5" fill="#6F87A8" fillOpacity=".5" />
      <circle cx="456" cy="470" r="1.8" fill="#B8892B" fillOpacity=".6" />
    </svg>
  )
}
