import * as React from "react";
import { BookOpenIcon, KeyboardIcon, MoonIcon, SearchIcon, SunIcon } from "lucide-react";
import { Link, Outlet, useLocation, useNavigate } from "react-router";

import { AppContext, type AppState } from "@/app/app-context";
import { ApiKeyDialog } from "@/app/api-key-dialog";
import { CommandPalette } from "@/app/command-palette";
import { NAV, NEW_CHAT_EVENT } from "@/app/nav";
import { ShortcutsDialog } from "@/app/shortcuts-dialog";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Separator } from "@/components/ui/separator";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { modKey } from "@/lib/format";
import { isTypingTarget, useInterval, useStored } from "@/lib/hooks";
import { useTheme } from "@/lib/theme";
import type { Health } from "@/lib/types";

function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={className}>
      <rect width="32" height="32" rx="8" className="fill-brand" />
      <path
        d="M9 21.5 15.2 9.6c.35-.67 1.25-.67 1.6 0L23 21.5"
        fill="none"
        className="stroke-brand-foreground"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="16" cy="18" r="2.4" className="fill-brand-foreground" />
    </svg>
  );
}

function ServerStatus({ health, offline }: { health: Health | null; offline: boolean }) {
  const { state } = useSidebar();
  const text = offline ? "server offline" : health ? health.model : "connecting…";
  const title = health
    ? `Server v${health.version} · default model ${health.model} · tools: ${health.tools.join(", ") || "none"}${health.auth ? " · API key required" : ""}`
    : offline
      ? "Cannot reach the server"
      : "Checking the server";
  return (
    <div
      className="flex min-w-0 items-center gap-2 px-2 py-1 text-xs text-muted-foreground group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0"
      title={title}
      role="status"
    >
      <span
        aria-hidden="true"
        className={`size-2 shrink-0 rounded-full ${offline ? "bg-destructive" : health ? "bg-success" : "animate-pulse bg-muted-foreground"}`}
      />
      {state === "expanded" ? (
        <span className="truncate font-mono">
          {text}
          {health?.auth ? " · key" : ""}
        </span>
      ) : (
        <span className="sr-only">{text}</span>
      )}
    </div>
  );
}

function AppSidebar({ health, offline, openPalette, openShortcuts }: {
  health: Health | null;
  offline: boolean;
  openPalette: () => void;
  openShortcuts: () => void;
}) {
  const { pathname } = useLocation();
  const { setOpenMobile } = useSidebar();
  const sections = ["Build", "Observe", "Evaluate"] as const;
  const settings = NAV.find((n) => n.id === "settings")!;
  const active = (path: string) => pathname === path || pathname.startsWith(`${path}/`);
  const close = () => setOpenMobile(false);
  return (
    <Sidebar collapsible="icon" variant="sidebar">
      <SidebarHeader className="gap-3">
        <Link to="/playground" className="flex items-center gap-2 px-1 pt-1" onClick={close} aria-label="AgentCore home">
          <Logo className="size-7 shrink-0" />
          <span className="truncate font-semibold tracking-tight group-data-[collapsible=icon]:hidden">AgentCore</span>
          {health ? (
            <span className="ml-auto font-mono text-[10px] text-muted-foreground group-data-[collapsible=icon]:hidden">
              v{health.version}
            </span>
          ) : null}
        </Link>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              tooltip={`Search (${modKey} K)`}
              onClick={() => {
                close();
                openPalette();
              }}
              className="border bg-background text-muted-foreground shadow-xs hover:text-foreground"
              aria-keyshortcuts="Control+K Meta+K"
            >
              <SearchIcon />
              <span>Search</span>
              <Kbd className="ml-auto">{modKey} K</Kbd>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        {sections.map((section) => (
          <SidebarGroup key={section}>
            <SidebarGroupLabel>{section}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {NAV.filter((n) => n.section === section).map((n) => (
                  <SidebarMenuItem key={n.id}>
                    <SidebarMenuButton asChild isActive={active(n.path)} tooltip={`${n.label} (G ${n.key.toUpperCase()})`}>
                      <Link
                        to={n.path}
                        onClick={close}
                        aria-current={active(n.path) ? "page" : undefined}
                        aria-keyshortcuts={`G ${n.key.toUpperCase()}`}
                      >
                        <n.icon />
                        <span>{n.label}</span>
                        <span className="ml-auto font-mono text-[10px] text-muted-foreground opacity-0 transition-opacity group-hover/menu-item:opacity-100">
                          G {n.key.toUpperCase()}
                        </span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton asChild isActive={active(settings.path)} tooltip="Settings (G S)">
              <Link to={settings.path} onClick={close} aria-current={active(settings.path) ? "page" : undefined}>
                <settings.icon />
                <span>Settings</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton tooltip="Keyboard shortcuts (?)" onClick={openShortcuts} aria-keyshortcuts="Shift+?">
              <KeyboardIcon />
              <span>Shortcuts</span>
              <Kbd className="ml-auto">?</Kbd>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton asChild tooltip="API docs (OpenAPI)">
              <a href="/docs" target="_blank" rel="noopener noreferrer">
                <BookOpenIcon />
                <span>API docs</span>
              </a>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
        <ServerStatus health={health} offline={offline} />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}

function ThemeButton() {
  const { resolved, toggle } = useTheme();
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="ghost" size="icon-sm" onClick={toggle} aria-label="Toggle colour theme (Shift T)">
          {resolved === "dark" ? <SunIcon /> : <MoonIcon />}
        </Button>
      </TooltipTrigger>
      <TooltipContent>Toggle theme (Shift T)</TooltipContent>
    </Tooltip>
  );
}

function TopBar({ openPalette }: { openPalette: () => void }) {
  const { pathname } = useLocation();
  const current = NAV.find((n) => pathname === n.path || pathname.startsWith(`${n.path}/`));
  return (
    <header className="sticky top-0 z-20 flex h-12 shrink-0 items-center gap-2 border-b bg-background/85 px-3 backdrop-blur supports-[backdrop-filter]:bg-background/70">
      <SidebarTrigger aria-label="Toggle navigation" />
      <Separator orientation="vertical" className="mr-1 data-[orientation=vertical]:h-4" />
      {current ? (
        <div className="flex min-w-0 items-center gap-2 text-sm">
          <current.icon className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          <span className="truncate font-medium">{current.label}</span>
          <span className="hidden truncate text-muted-foreground md:inline">· {current.description}</span>
        </div>
      ) : null}
      <div className="ml-auto flex items-center gap-1">
        <Button
          variant="outline"
          size="sm"
          onClick={openPalette}
          className="hidden w-48 justify-start gap-2 font-normal text-muted-foreground sm:flex"
        >
          <SearchIcon />
          Search…
          <Kbd className="ml-auto">{modKey} K</Kbd>
        </Button>
        <Button variant="ghost" size="icon-sm" onClick={openPalette} aria-label="Search and commands" className="sm:hidden">
          <SearchIcon />
        </Button>
        <ThemeButton />
      </div>
    </header>
  );
}

export function AppLayout() {
  const navigate = useNavigate();
  const theme = useTheme();
  const [paletteOpen, setPaletteOpen] = React.useState(false);
  const [shortcutsOpen, setShortcutsOpen] = React.useState(false);
  const [health, setHealth] = React.useState<Health | null>(null);
  const [offline, setOffline] = React.useState(false);
  const [sidebarOpen, setSidebarOpen] = useStored("sidebar.open", true);

  const refreshHealth = React.useCallback(() => {
    fetch("/health")
      .then((r) => r.json() as Promise<Health>)
      .then((h) => {
        setHealth(h);
        setOffline(false);
      })
      .catch(() => setOffline(true));
  }, []);
  React.useEffect(refreshHealth, [refreshHealth]);
  useInterval(refreshHealth, 30_000);

  const newChat = React.useCallback(() => {
    if (window.location.pathname === "/playground") window.dispatchEvent(new CustomEvent(NEW_CHAT_EVENT));
    else navigate("/playground", { state: { newChat: Date.now() } });
  }, [navigate]);

  // Global keys: Ctrl/Cmd+K, ?, N, Shift+T and the G-prefixed view switcher.
  React.useEffect(() => {
    let gAt = 0;
    const on = (ev: KeyboardEvent) => {
      if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && ev.key.toLowerCase() === "k") {
        ev.preventDefault();
        setPaletteOpen((o) => !o);
        return;
      }
      if (ev.defaultPrevented || ev.ctrlKey || ev.metaKey || ev.altKey || isTypingTarget(ev.target)) return;
      if (document.querySelector("[role=dialog][data-state=open]")) return;
      if (gAt && Date.now() - gAt < 1200) {
        gAt = 0;
        const item = NAV.find((n) => n.key === ev.key.toLowerCase());
        if (item) {
          ev.preventDefault();
          navigate(item.path);
        }
        return;
      }
      gAt = 0;
      if (ev.key === "?") {
        ev.preventDefault();
        setShortcutsOpen(true);
      } else if (ev.key === "g") {
        gAt = Date.now();
      } else if (ev.key === "n") {
        ev.preventDefault();
        newChat();
      } else if (ev.key === "T" && ev.shiftKey) {
        ev.preventDefault();
        theme.toggle();
      }
    };
    document.addEventListener("keydown", on);
    return () => document.removeEventListener("keydown", on);
  }, [navigate, newChat, theme]);

  const { pathname } = useLocation();
  React.useEffect(() => {
    const n = NAV.find((x) => pathname === x.path || pathname.startsWith(`${x.path}/`));
    document.title = n ? `${n.label} · AgentCore` : "AgentCore";
  }, [pathname]);

  const value: AppState = React.useMemo(
    () => ({
      health,
      offline,
      refreshHealth,
      openPalette: () => setPaletteOpen(true),
      openShortcuts: () => setShortcutsOpen(true),
      newChat,
    }),
    [health, offline, refreshHealth, newChat],
  );

  return (
    <AppContext.Provider value={value}>
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-background px-3 py-2 focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:ring-2 focus:ring-ring"
      >
        Skip to content
      </a>
      <SidebarProvider open={sidebarOpen} onOpenChange={setSidebarOpen} className="h-svh overflow-hidden">
        <AppSidebar
          health={health}
          offline={offline}
          openPalette={() => setPaletteOpen(true)}
          openShortcuts={() => setShortcutsOpen(true)}
        />
        <SidebarInset className="min-h-0 min-w-0 overflow-hidden">
          <TopBar openPalette={() => setPaletteOpen(true)} />
          <main id="main" tabIndex={-1} className="flex min-h-0 flex-1 flex-col overflow-hidden outline-none">
            <Outlet />
          </main>
        </SidebarInset>
      </SidebarProvider>
      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        openShortcuts={() => setShortcutsOpen(true)}
        newChat={newChat}
      />
      <ShortcutsDialog open={shortcutsOpen} onOpenChange={setShortcutsOpen} />
      <ApiKeyDialog />
    </AppContext.Provider>
  );
}
