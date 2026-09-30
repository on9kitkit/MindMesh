import { Stack, usePathname } from "expo-router";
import { StatusBar } from "expo-status-bar";

import {
  StudioThemeProvider,
  useStudioTheme,
} from "../src/appearance/StudioThemeContext";
import { SessionProvider } from "../src/features/session/SessionContext";
import { SessionRouteCoordinator } from "../src/features/session/SessionRouteCoordinator";
import { colors } from "../src/theme";
import { AuthProvider } from "../src/auth/AuthContext";
import { RevenueCatProvider } from "../src/revenuecat/RevenueCatContext";

export default function RootLayout() {
  const pathname = usePathname();
  const appearanceEnabled =
    pathname === "/" || pathname === "/sign-in" || pathname === "/waiting-room" ||
    pathname === "/quiz" || pathname === "/results" || pathname === "/sign-up" ||
    pathname === "/auth/callback" || pathname === "/account" ||
    pathname === "/privacy" || pathname === "/support" || pathname === "/report" ||
    pathname === "/pro" || pathname === "/solo" || pathname === "/pets";

  return (
    <AuthProvider>
      <RevenueCatProvider>
        <SessionProvider>
          <SessionRouteCoordinator />
          <StudioThemeProvider preferenceEnabled={appearanceEnabled}>
            <ThemeAwareRoutes appearanceEnabled={appearanceEnabled} />
          </StudioThemeProvider>
        </SessionProvider>
      </RevenueCatProvider>
    </AuthProvider>
  );
}

function ThemeAwareRoutes({ appearanceEnabled }: { appearanceEnabled: boolean }) {
  const theme = useStudioTheme();
  return (
    <>
      <StatusBar style={theme.scheme === "dark" ? "light" : "dark"} />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: {
            backgroundColor: appearanceEnabled
              ? theme.colors.background
              : colors.background,
          },
        }}
      />
    </>
  );
}
