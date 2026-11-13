import {
  FlaskConicalIcon,
  LayoutDashboardIcon,
  MessagesSquareIcon,
  SettingsIcon,
  WaypointsIcon,
  WrenchIcon,
  type LucideIcon,
} from "lucide-react";

import { modKey } from "@/lib/format";

export interface NavItem {
  id: string;
  label: string;
  path: string;
  icon: LucideIcon;
  section: "Build" | "Observe" | "Evaluate" | null;
  key: string;
  description: string;
}

export const NAV: NavItem[] = [
  {
    id: "playground",
    label: "Playground",
    path: "/playground",
    icon: MessagesSquareIcon,
    section: "Build",
    key: "p",
    description: "Chat with the agent and see every step it takes",
  },
  {
    id: "tools",
    label: "Tools",
    path: "/tools",
    icon: WrenchIcon,
    section: "Build",
    key: "l",
    description: "Tool schemas and a try-it form",
  },
  {
    id: "traces",
    label: "Traces",
    path: "/traces",
    icon: WaypointsIcon,
    section: "Observe",
    key: "t",
    description: "Search, filter and inspect agent runs",
  },
  {
    id: "overview",
    label: "Overview",
    path: "/overview",
    icon: LayoutDashboardIcon,
    section: "Observe",
    key: "o",
    description: "Runs, latency, tokens and cost over time",
  },
  {
    id: "evals",
    label: "Evals",
    path: "/evals",
    icon: FlaskConicalIcon,
    section: "Evaluate",
    key: "e",
    description: "Run suites, compare runs, catch regressions",
  },
  {
    id: "settings",
    label: "Settings",
    path: "/settings",
    icon: SettingsIcon,
    section: null,
    key: "s",
    description: "Theme, API key and server configuration",
  },
];

export const SHORTCUTS: { group: string; keys: [string[], string][] }[] = [
  {
    group: "Everywhere",
    keys: [
      [[modKey, "K"], "Command palette: views, actions, traces, chats, eval suites"],
      [["?"], "Show keyboard shortcuts"],
      [["N"], "New chat"],
      [["G", "P"], "Go to Playground"],
      [["G", "T"], "Go to Traces"],
      [["G", "E"], "Go to Evals"],
      [["G", "O"], "Go to Overview"],
      [["G", "L"], "Go to Tools"],
      [["G", "S"], "Go to Settings"],
      [["Shift", "T"], "Toggle light / dark theme"],
      [[modKey, "B"], "Collapse / expand the sidebar"],
    ],
  },
  {
    group: "Traces",
    keys: [
      [["/"], "Focus the query bar"],
      [["J"], "Next trace"],
      [["K"], "Previous trace"],
      [["Enter"], "Open the selected trace in the side peek"],
      [["Esc"], "Close the side peek"],
      [["1", "2", "3"], "Peek tabs: Preview, Attributes, JSON"],
      [["R"], "Refresh"],
    ],
  },
  {
    group: "Playground",
    keys: [
      [["Enter"], "Send message"],
      [["Shift", "Enter"], "New line"],
      [["/"], "Focus the composer"],
      [["."], "Show / hide run settings"],
    ],
  },
  {
    group: "Evals",
    keys: [
      [["←", "↑", "→", "↓"], "Move between matrix cells"],
      [["Enter"], "Open the case in the side peek"],
      [["Esc"], "Close the side peek"],
    ],
  },
];

export const NEW_CHAT_EVENT = "agentcore:new-chat";
