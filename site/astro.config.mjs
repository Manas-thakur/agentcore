// @ts-check
import starlight from "@astrojs/starlight";
import { defineConfig } from "astro/config";
import starlightLinksValidator from "starlight-links-validator";

const repo = "https://github.com/Manas-thakur/agentcore";

// Landing page at the site root (src/pages/index.astro); docs under /docs/ (Starlight).
export default defineConfig({
  site: "https://manas-thakur.github.io",
  base: "/agentcore",
  trailingSlash: "ignore",
  vite: {
    // Screenshots live in ../docs/screenshots (shared with the README).
    server: { fs: { allow: [".."] } },
  },
  integrations: [
    starlight({
      title: "AgentCore",
      description:
        "A from-scratch agentic AI platform in plain Python: runtime, tools, evals, RAG, vector indexes, workflow graphs, multi-agent and observability, with a web app.",
      logo: { src: "./src/assets/logo.svg", alt: "AgentCore" },
      favicon: "/favicon.svg",
      social: [{ icon: "github", label: "GitHub", href: repo }],
      editLink: { baseUrl: `${repo}/edit/main/site/` },
      lastUpdated: false,
      customCss: ["./src/styles/starlight.css"],
      plugins: [starlightLinksValidator({ errorOnRelativeLinks: false })],
      sidebar: [
        {
          label: "Start here",
          items: [
            { label: "Introduction", slug: "docs" },
            { label: "Installation", slug: "docs/installation" },
            { label: "Quickstart (offline)", slug: "docs/quickstart" },
            { label: "New project: agentcore init", slug: "docs/project" },
          ],
        },
        {
          label: "Concepts",
          items: [
            { label: "How it fits together", slug: "docs/concepts" },
            { label: "Runtime", slug: "docs/modules/runtime" },
            { label: "Tools", slug: "docs/modules/tools" },
            { label: "Eval", slug: "docs/modules/eval" },
            { label: "RAG", slug: "docs/modules/rag" },
            { label: "Vector indexes", slug: "docs/modules/indexes" },
            { label: "Workflow graphs", slug: "docs/modules/graph" },
            { label: "Multi-agent", slug: "docs/modules/agents" },
            { label: "Observability", slug: "docs/modules/obs" },
          ],
        },
        {
          label: "Guides",
          items: [
            { label: "Web app", slug: "docs/web-app" },
            { label: "Ollama and OpenAI-compatible models", slug: "docs/models" },
            { label: "Configuration", slug: "docs/configuration" },
            { label: "Deployment", slug: "docs/deployment" },
          ],
        },
        {
          label: "Reference",
          items: [
            { label: "CLI", slug: "docs/reference/cli" },
            { label: "HTTP API", slug: "docs/reference/http-api" },
            { label: "Trace query language", slug: "docs/reference/query-language" },
          ],
        },
        {
          label: "Project",
          items: [
            { label: "Troubleshooting and FAQ", slug: "docs/troubleshooting" },
            { label: "Changelog", slug: "docs/changelog" },
            { label: "Contributing", slug: "docs/contributing" },
          ],
        },
      ],
    }),
  ],
});
