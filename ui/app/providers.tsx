"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CssBaseline, ThemeProvider, createTheme } from "@mui/material";
import { ReactNode, useState } from "react";

const theme = createTheme({
  palette: {
    mode: "dark",
    primary: {
      main: "#ff1f3d",
      light: "#ff4d64",
      dark: "#b40019"
    },
    secondary: {
      main: "#f7f7f7",
      dark: "#c7c7c7"
    },
    error: {
      main: "#ff334f"
    },
    success: {
      main: "#22c55e"
    },
    warning: {
      main: "#f5b301"
    },
    background: {
      default: "#050506",
      paper: "#0c0d10"
    },
    text: {
      primary: "#f8f8f8",
      secondary: "#a3a3a3"
    },
    divider: "rgba(255, 255, 255, 0.12)",
    action: {
      hover: "rgba(255, 31, 61, 0.12)",
      selected: "rgba(255, 31, 61, 0.18)"
    }
  },
  shape: {
    borderRadius: 8
  },
  typography: {
    fontFamily: "Arial, Helvetica, sans-serif",
    h1: {
      fontWeight: 900,
      letterSpacing: 0
    },
    h2: {
      fontWeight: 800,
      letterSpacing: 0
    },
    button: {
      fontWeight: 800,
      letterSpacing: 0,
      textTransform: "none"
    }
  },
  components: {
    MuiCard: {
      styleOverrides: {
        root: {
          backgroundImage: "linear-gradient(180deg, rgba(255, 31, 61, 0.06), rgba(255, 31, 61, 0) 36%)",
          border: "1px solid rgba(255, 255, 255, 0.13)",
          boxShadow: "0 18px 48px rgba(0, 0, 0, 0.46)"
        }
      }
    },
    MuiButton: {
      defaultProps: {
        disableElevation: true
      },
      styleOverrides: {
        root: {
          minHeight: 40,
          borderRadius: 6
        },
        contained: {
          backgroundImage: "linear-gradient(135deg, #ff1f3d, #b40019)",
          color: "#ffffff",
          fontWeight: 900,
          "&:hover": {
            backgroundImage: "linear-gradient(135deg, #ff4d64, #d6001f)"
          }
        }
      }
    },
    MuiTextField: {
      defaultProps: {
        size: "small"
      }
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          backgroundColor: "rgba(0, 0, 0, 0.34)"
        }
      }
    },
    MuiChip: {
      styleOverrides: {
        root: {
          borderRadius: 6,
          border: "1px solid rgba(255, 255, 255, 0.14)"
        }
      }
    },
    MuiTableCell: {
      styleOverrides: {
        root: {
          borderBottomColor: "rgba(255, 255, 255, 0.09)"
        },
        head: {
          backgroundColor: "#101114"
        }
      }
    }
  }
});

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            retry: 1
          }
        }
      })
  );

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </ThemeProvider>
    </QueryClientProvider>
  );
}
