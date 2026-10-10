// 品牌：星图 + 萤火。名字只在这里定义，改名时只改 BRAND。
export const BRAND = {zh: '星萤', en: 'Starglow'};

/** 标志：一小片星图，其中一颗星像萤火一样亮起（表示“学会了”）。 */
export function LogoMark({size = 28}: {size?: number}) {
  return <svg className="logo-mark" width={size} height={size} viewBox="0 0 54 54" aria-hidden="true">
    <rect width="54" height="54" rx="13" fill="var(--brand-night)"/>
    <g stroke="var(--brand-line)" strokeWidth="2" opacity=".65"><line x1="10" y1="40" x2="22" y2="22"/><line x1="22" y1="22" x2="38" y2="30"/><line x1="38" y1="30" x2="44" y2="13"/></g>
    <circle cx="10" cy="40" r="3" fill="var(--brand-line)"/><circle cx="38" cy="30" r="3.2" fill="#E6F1FB"/><circle cx="44" cy="13" r="3" fill="var(--brand-line)"/>
    <circle className="logo-glow" cx="22" cy="22" r="9" fill="var(--glow)" opacity=".3"/><circle cx="22" cy="22" r="5" fill="var(--glow)"/>
  </svg>;
}

export function Wordmark() {
  return <span className="wordmark"><LogoMark/><span className="wordmark-zh">{BRAND.zh}</span><span className="wordmark-en">{BRAND.en}</span></span>;
}
