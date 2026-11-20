import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { CssBaseline, ThemeProvider, createTheme } from '@mui/material'
import App from './App'
import { getUiLanguage } from './i18n'

document.documentElement.lang = getUiLanguage()

const theme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: '#2456a7' },
    background: { default: '#f5f7fb', paper: '#ffffff' },
    text: { primary: '#17243a', secondary: '#607086' },
    divider: '#e4e9f1',
  },
  shape: { borderRadius: 12 },
  typography: { fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif' },
  components: {
    MuiPaper: { styleOverrides: { root: { backgroundImage: 'none' } } },
    MuiButton: { defaultProps: { disableElevation: true }, styleOverrides: { root: { textTransform: 'none', fontWeight: 650 } } },
    MuiCard: { styleOverrides: { root: { border: '1px solid #e4e9f1', boxShadow: '0 4px 18px rgba(26,45,82,.035)' } } },
  },
})

const queryClient = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: true, retry: 1 } } })

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <QueryClientProvider client={queryClient}>
        <BrowserRouter basename={window.location.pathname.startsWith('/admin/queue') ? '/admin/queue' : '/queue'}><App /></BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  </React.StrictMode>,
)
