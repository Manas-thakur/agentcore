import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router";

import "./index.css";
import { AppLayout } from "@/app/layout";
import { RouteError } from "@/app/route-error";
import { SkeletonRows } from "@/components/app/common";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThemeProvider } from "@/lib/theme";

const PlaygroundPage = lazy(() => import("@/pages/playground"));
const TracesPage = lazy(() => import("@/pages/traces"));
const EvalsPage = lazy(() => import("@/pages/evals"));
const OverviewPage = lazy(() => import("@/pages/overview"));
const ToolsPage = lazy(() => import("@/pages/tools"));
const SettingsPage = lazy(() => import("@/pages/settings"));

function Lazy({ children }: { children: React.ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="p-6">
          <SkeletonRows rows={8} />
        </div>
      }
    >
      {children}
    </Suspense>
  );
}

// Pre-0.3 links used hash routes (#/traces/<id>?query=...): turn them into real paths.
if (window.location.hash.startsWith("#/")) {
  window.history.replaceState(null, "", window.location.hash.slice(1));
}

const router = createBrowserRouter([
  {
    path: "/",
    element: <AppLayout />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Navigate to="/playground" replace /> },
      { path: "playground/:sessionId?", element: <Lazy><PlaygroundPage /></Lazy> },
      { path: "traces/:traceId?", element: <Lazy><TracesPage /></Lazy> },
      { path: "evals", element: <Lazy><EvalsPage /></Lazy> },
      { path: "overview", element: <Lazy><OverviewPage /></Lazy> },
      { path: "tools/:toolName?", element: <Lazy><ToolsPage /></Lazy> },
      { path: "settings", element: <Lazy><SettingsPage /></Lazy> },
      { path: "*", element: <Navigate to="/playground" replace /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <TooltipProvider delayDuration={300}>
        <RouterProvider router={router} />
        <Toaster position="bottom-right" closeButton />
      </TooltipProvider>
    </ThemeProvider>
  </StrictMode>,
);
