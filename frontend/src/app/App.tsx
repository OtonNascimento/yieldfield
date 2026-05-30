import { type CSSProperties, type ReactElement } from 'react';

import { useTheme } from '@/design-system';

// The Slice 0 shell: proves the app boots, the design-system theme contract works
// (the [data-theme] flip), and that UI is styled exclusively through tokens — no
// hard-coded color anywhere. Real product UI (findings, dashboard) lands in Slice 4.
const pageStyle: CSSProperties = {
  minHeight: '100vh',
  margin: 0,
  padding: '3rem',
  background: 'var(--ds-bg)',
  color: 'var(--ds-text)',
  fontFamily: 'var(--ds-font-sans)',
};

const cardStyle: CSSProperties = {
  maxWidth: '32rem',
  padding: '1.5rem',
  borderRadius: '6px',
  border: '1px solid var(--ds-line)',
  background: 'var(--ds-surface)',
};

const buttonStyle: CSSProperties = {
  marginTop: '1rem',
  padding: '0.5rem 0.9rem',
  borderRadius: '4px',
  border: '1px solid var(--ds-line)',
  background: 'var(--ds-surface-raised)',
  color: 'var(--ds-text)',
  fontFamily: 'var(--ds-font-sans)',
  cursor: 'pointer',
};

export function App(): ReactElement {
  const { theme, toggleTheme } = useTheme();

  return (
    <main style={pageStyle}>
      <section style={cardStyle}>
        <p
          style={{
            fontFamily: 'var(--ds-font-mono)',
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            fontSize: '0.7rem',
            color: 'var(--ds-text-muted)',
            margin: 0,
          }}
        >
          Yieldfield · Slice 0
        </p>
        <h1 style={{ fontFamily: 'var(--ds-font-serif)', margin: '0.5rem 0 0' }}>
          Scaffold is live
        </h1>
        <p style={{ color: 'var(--ds-text-muted)' }}>
          The design-system layer, theme contract, and token boundary are wired. Current theme:{' '}
          <strong>{theme}</strong>.
        </p>
        <button type="button" style={buttonStyle} onClick={toggleTheme}>
          Toggle theme
        </button>
      </section>
    </main>
  );
}
