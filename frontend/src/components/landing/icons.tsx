// אייקונים ואיורים דקורטיביים לדף הנחיתה: אייקוני שלבים, אייקוני יכולות ואיורי תחומים.

/* ----------------------- אייקוני שלבים (לבנים) ------------------- */
export function StepIcon({ k }: { k: string }) {
  if (k === 'google')
    return (<svg aria-hidden="true" focusable="false" width="28" height="28" viewBox="0 0 24 24" fill="none"><path d="M12 5a7 7 0 107 7h-6.6" stroke="#fff" strokeWidth="2.3" strokeLinecap="round" /></svg>)
  if (k === 'ai')
    return (<svg aria-hidden="true" focusable="false" width="28" height="28" viewBox="0 0 24 24" fill="none"><path d="M12 3l1.7 4.6L18 9l-4.3 1.6L12 15l-1.7-4.4L6 9l4.3-1.4L12 3z" fill="#fff" /><path d="M18.5 14l.7 1.9 2 .6-2 .7-.7 1.9-.7-1.9-2-.7 2-.6.7-1.9z" fill="#fff" opacity=".9" /></svg>)
  if (k === 'whatsapp')
    return (<svg aria-hidden="true" focusable="false" width="28" height="28" viewBox="0 0 24 24" fill="none"><path d="M6 5h12a2 2 0 012 2v7a2 2 0 01-2 2h-7l-4 3.4V16H6a2 2 0 01-2-2V7a2 2 0 012-2z" fill="#fff" /><circle cx="9" cy="10.5" r="1.1" fill="#46a23f" /><circle cx="12" cy="10.5" r="1.1" fill="#46a23f" /><circle cx="15" cy="10.5" r="1.1" fill="#46a23f" /></svg>)
  if (k === 'config')
    return (<svg aria-hidden="true" focusable="false" width="28" height="28" viewBox="0 0 24 24" fill="none"><path d="M4 7h7M15 7h5M4 12h11M19 12h1M4 17h3M11 17h9" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" /><circle cx="13" cy="7" r="2.1" fill="#3f9a39" stroke="#fff" strokeWidth="1.8" /><circle cx="17" cy="12" r="2.1" fill="#3f9a39" stroke="#fff" strokeWidth="1.8" /><circle cx="9" cy="17" r="2.1" fill="#3f9a39" stroke="#fff" strokeWidth="1.8" /></svg>)
  if (k === 'live')
    return (<svg aria-hidden="true" focusable="false" width="28" height="28" viewBox="0 0 24 24" fill="none"><path d="M12 2.5c2.8 1.6 4.2 4.4 4.2 7.8 0 1.5-.5 2.9-1.3 3.9H9.1c-.8-1-1.3-2.4-1.3-3.9C7.8 6.9 9.2 4.1 12 2.5z" fill="#fff" /><circle cx="12" cy="8.4" r="1.5" fill="#3f9a39" /><path d="M9.2 15l-1.7 4 3-1.4M14.8 15l1.7 4-3-1.4" stroke="#fff" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" fill="none" /></svg>)
  return (<svg aria-hidden="true" focusable="false" width="28" height="28" viewBox="0 0 24 24" fill="none"><circle cx="9" cy="8.5" r="2.6" fill="#fff" /><circle cx="16" cy="9.5" r="2" fill="#fff" opacity=".9" /><path d="M4.5 18c0-2.5 2-4.3 4.5-4.3s4.5 1.8 4.5 4.3" stroke="#fff" strokeWidth="2" strokeLinecap="round" fill="none" /><path d="M14.5 17.6c.2-2 1.7-3.4 3.7-3.4 1.6 0 2.9.9 3.4 2.3" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" fill="none" opacity=".9" /></svg>)
}

/* ---------------------- אייקוני יכולות (קו) --------------------- */
export function FeatIcon({ k }: { k: string }) {
  const p = { width: 24, height: 24, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }
  if (k === 'leads')
    return (<svg aria-hidden="true" focusable="false" {...p}><circle cx="9" cy="8" r="3" /><path d="M3.5 19a5.5 5.5 0 0111 0" /><path d="M16 6.2a3 3 0 010 5.6" /><path d="M18.5 19a5.5 5.5 0 00-3-4.9" /></svg>)
  if (k === 'calendar')
    return (<svg aria-hidden="true" focusable="false" {...p}><rect x="4" y="5" width="16" height="15" rx="2" /><path d="M4 9.5h16M8 3v3.5M16 3v3.5" /><rect x="7.5" y="12.5" width="3" height="3" rx=".6" fill="currentColor" stroke="none" /></svg>)
  if (k === 'handoff')
    return (<svg aria-hidden="true" focusable="false" {...p}><path d="M5 5h14a2 2 0 012 2v6.5a2 2 0 01-2 2h-8L7 19v-3.5H5a2 2 0 01-2-2V7a2 2 0 012-2z" /><path d="M8.5 10.2h.01M12 10.2h.01M15.5 10.2h.01" /></svg>)
  if (k === 'ai')
    return (<svg aria-hidden="true" focusable="false" {...p}><path d="M12 3l1.7 4.6L18 9l-4.3 1.6L12 15l-1.7-4.4L6 9l4.3-1.4L12 3z" fill="currentColor" stroke="none" /><path d="M18.4 14.2l.6 1.7 1.8.6-1.8.6-.6 1.7-.6-1.7-1.8-.6 1.8-.6.6-1.7z" fill="currentColor" stroke="none" /></svg>)
  if (k === 'dashboard')
    return (<svg aria-hidden="true" focusable="false" {...p}><rect x="5" y="8" width="14" height="10" rx="3" /><path d="M12 8V5.5" /><circle cx="12" cy="4" r="1.3" fill="currentColor" stroke="none" /><circle cx="9.6" cy="13" r="1.1" fill="currentColor" stroke="none" /><circle cx="14.4" cy="13" r="1.1" fill="currentColor" stroke="none" /><path d="M3.2 12v2.5M20.8 12v2.5" /></svg>)
  return (<svg aria-hidden="true" focusable="false" {...p}><circle cx="12" cy="12" r="8.5" /><path d="M3.6 12h16.8M12 3.5c2.4 2.3 2.4 14.7 0 17M12 3.5c-2.4 2.3-2.4 14.7 0 17" /></svg>)
}

/* ============ תמונות מונפשות לכל תחום (איורים צבעוניים) ========= */
export function UseCaseArt({ k }: { k: string }) {
  const org = { transformBox: 'fill-box' as const, transformOrigin: 'center' }
  if (k === 'health')
    return (
      <svg aria-hidden="true" focusable="false" viewBox="0 0 140 92" fill="none">
        <circle cx="22" cy="24" r="6" fill="#fff" opacity=".55" className="bx-flo" style={org} />
        <circle cx="118" cy="64" r="7" fill="currentColor" opacity=".22" className="bx-flo2" style={org} />
        <g className="bx-beat" style={org}><path d="M70 70c-17-10-27-20-27-33a14 14 0 0127-7 14 14 0 0127 7c0 13-10 23-27 33z" fill="currentColor" /></g>
        <path d="M26 50h20l5-12 7 24 6-14 4 8h42" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" className="bx-draw" />
        <g className="bx-flo2" style={org}><rect x="98" y="15" width="18" height="18" rx="5" fill="#fff" /><path d="M107 20v8M103 24h8" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" /></g>
      </svg>
    )
  if (k === 'beauty')
    return (
      <svg aria-hidden="true" focusable="false" viewBox="0 0 140 92" fill="none">
        <g className="bx-twk" style={org}><path d="M26 18l2.4 6.6 6.6 2.4-6.6 2.4-2.4 6.6-2.4-6.6-6.6-2.4 6.6-2.4z" fill="#fff" /></g>
        <g className="bx-twk2" style={org}><path d="M114 58l2 5.6 5.6 2-5.6 2-2 5.6-2-5.6-5.6-2 5.6-2z" fill="currentColor" /></g>
        <g className="bx-sway" style={{ transformBox: 'fill-box', transformOrigin: '70px 72px' }}>
          <circle cx="54" cy="72" r="8" stroke="currentColor" strokeWidth="3.4" fill="none" />
          <circle cx="72" cy="72" r="8" stroke="currentColor" strokeWidth="3.4" fill="none" />
          <path d="M58 67l40-40M68 67L30 30" stroke="currentColor" strokeWidth="3.4" strokeLinecap="round" />
          <circle cx="63" cy="52" r="3" fill="currentColor" />
        </g>
      </svg>
    )
  if (k === 'insurance')
    return (
      <svg aria-hidden="true" focusable="false" viewBox="0 0 140 92" fill="none">
        <circle cx="20" cy="22" r="6" fill="currentColor" opacity=".2" className="bx-flo" style={org} />
        <circle cx="120" cy="66" r="5" fill="#fff" opacity=".6" className="bx-flo2" style={org} />
        <g className="bx-flo" style={org}>
          <path d="M70 14l30 10v18c0 18-13 30-30 36-17-6-30-18-30-36V24z" fill="currentColor" />
          <path d="M58 46l9 9 19-19" stroke="#fff" strokeWidth="4.4" strokeLinecap="round" strokeLinejoin="round" />
        </g>
      </svg>
    )
  if (k === 'service')
    return (
      <svg aria-hidden="true" focusable="false" viewBox="0 0 140 92" fill="none">
        <circle cx="24" cy="24" r="6" fill="#fff" opacity=".55" className="bx-flo" style={org} />
        <circle cx="116" cy="68" r="6" fill="currentColor" opacity=".2" className="bx-flo2" style={org} />
        <circle cx="70" cy="46" r="17" stroke="currentColor" strokeWidth="9" fill="none" strokeDasharray="6 7.6" className="bx-spin" style={org} />
        <circle cx="70" cy="46" r="8" fill="#fff" stroke="currentColor" strokeWidth="4" />
      </svg>
    )
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 140 92" fill="none">
      <circle cx="70" cy="40" r="23" fill="currentColor" opacity=".16" className="bx-glow" style={org} />
      <g className="bx-twk" style={org}><path d="M70 8v6M49 18l4 4M91 18l-4 4M40 40h6M94 40h6" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" /></g>
      <g className="bx-flo" style={org}>
        <path d="M70 22a16 16 0 00-9 29c2 1.5 3 3 3 5v2h12v-2c0-2 1-3.5 3-5a16 16 0 00-9-29z" fill="currentColor" />
        <rect x="64" y="60" width="12" height="5" rx="2" fill="currentColor" />
        <rect x="66" y="67" width="8" height="4" rx="2" fill="currentColor" />
      </g>
      <g className="bx-twk2" style={org}><rect x="20" y="72" width="6" height="10" rx="2" fill="#fff" /><rect x="29" y="66" width="6" height="16" rx="2" fill="#fff" /><rect x="38" y="60" width="6" height="22" rx="2" fill="#fff" /></g>
    </svg>
  )
}
