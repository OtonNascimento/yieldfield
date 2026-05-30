import { useContext } from 'react';

import { ThemeContext, type ThemeContextValue } from './themeContext';

/** Access the current theme and its controls. Must be used under a ThemeProvider. */
export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (context === null) {
    throw new Error('useTheme must be used within a ThemeProvider (§5A).');
  }
  return context;
}
