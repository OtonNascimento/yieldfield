import { createContext } from 'react';

export type Theme = 'light' | 'dark';

export interface ThemeContextValue {
  readonly theme: Theme;
  readonly setTheme: (theme: Theme) => void;
  readonly toggleTheme: () => void;
}

/** Null until a `ThemeProvider` is mounted; `useTheme` enforces that. */
export const ThemeContext = createContext<ThemeContextValue | null>(null);

/** localStorage key the theme choice persists under (§5A: theme is persisted). */
export const THEME_STORAGE_KEY = 'yieldfield-theme';
