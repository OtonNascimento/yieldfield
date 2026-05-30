import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { App } from '@/app/App';
import { ThemeProvider } from '@/design-system';

describe('App shell', () => {
  it('boots and renders the scaffold heading under the theme provider', () => {
    render(
      <ThemeProvider>
        <App />
      </ThemeProvider>,
    );
    expect(screen.getByRole('heading', { name: /scaffold is live/i })).toBeInTheDocument();
  });
});
