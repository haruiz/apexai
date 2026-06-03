"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CssBaseline, ThemeProvider, createTheme } from "@mui/material";
import { ReactNode, useState } from "react";

const theme = createTheme({
  palette: {
    mode: "dark",
    primary: {
      main: "#72f4ff",
      light: "#a8fbff",
      dark: "#29b7c7"
    },
    secondary: {
      main: "#ff6a00",
      dark: "#b84900"
    },
    error: {
      main: "#ff3d4d"
    },
    success: {
      main: "#62e6bc"
    },
    warning: {
      main: "#ffb300"
    },
    background: {
      default: "#151712",
      paper: "#0a0d12"
    },
    text: {
      primary: "#f7f4ea",
      secondary: "#a5a8b3"
    },
    divider: "rgba(255, 255, 255, 0.1)",
    action: {
      hover: "rgba(114, 244, 255, 0.12)",
      selected: "rgba(114, 244, 255, 0.18)"
    }
  },
  shape: {
    borderRadius: 8
  },
  typography: {
    fontFamily: "Outfit, Inter, Arial, Helvetica, sans-serif",
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
          backgroundColor: "rgba(10, 13, 18, 0.84)",
          backgroundImage:
            "radial-gradient(circle at 92% 18%, rgba(255, 106, 0, 0.12), transparent 30%), linear-gradient(180deg, rgba(22, 24, 20, 0.92), rgba(8, 10, 13, 0.92))",
          border: "1px solid rgba(255, 255, 255, 0.1)",
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
          backgroundImage: "linear-gradient(135deg, #72f4ff, #29b7c7)",
          color: "#001316",
          fontWeight: 900,
          "&:hover": {
            backgroundImage: "linear-gradient(135deg, #a8fbff, #72f4ff)"
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
          backgroundColor: "rgba(8, 10, 14, 0.72)"
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
          backgroundColor: "#111625"
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
