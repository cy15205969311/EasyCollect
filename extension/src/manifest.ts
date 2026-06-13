import type { ManifestV3Export } from "@crxjs/vite-plugin";

const manifest: ManifestV3Export = {
  manifest_version: 3,
  name: "EasyCollect",
  version: "0.1.0",
  description: "1688 product data collection and normalization helper",
  permissions: ["activeTab", "downloads", "scripting", "storage"],
  host_permissions: ["https://*.1688.com/*", "http://localhost:8000/*"],
  background: {
    service_worker: "src/background/service-worker.ts",
    type: "module",
  },
  content_scripts: [
    {
      matches: ["https://*.1688.com/*"],
      js: ["src/content/index.ts"],
      run_at: "document_start",
    },
  ],
  action: {
    default_popup: "index.html",
    default_title: "EasyCollect",
  },
};

export default manifest;
