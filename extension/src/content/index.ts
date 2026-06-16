const ROOT_ID = "easycollect-shadow-root";
const START_EXTRACTION_ACTION = "START_EXTRACTION";
const OPEN_DASHBOARD_ACTION = "OPEN_DASHBOARD";
const COLLECTION_STATUS_TYPE = "EASYCOLLECT_COLLECTION_STATUS";
const SHOPEE_API_DATA_TYPE = "EASYCOLLECT_SHOPEE_API_DATA";

type CollectionStatusMessage = {
  type: typeof COLLECTION_STATUS_TYPE;
  status: "success" | "error";
  message?: string;
};

type CollectMode = "fast" | "ai";

type StartExtractionResponse = {
  ok: boolean;
  error?: string;
};

type CachedShopeeData = {
  platform: "shopee";
  dataKey: string;
  url: string;
  capturedAt: string;
  raw: unknown;
};

type ShopeeApiMessage = {
  source?: "easycollect-interceptor";
  type?: typeof SHOPEE_API_DATA_TYPE;
  url?: string;
  payload?: unknown;
  capturedAt?: string;
};

type UnknownRecord = Record<string, unknown>;

declare global {
  interface Window {
    __EASYCOLLECT_CACHED_DATA__?: CachedShopeeData;
  }
}

let activeButton: HTMLButtonElement | null = null;
let fastButton: HTMLButtonElement | null = null;
let aiButton: HTMLButtonElement | null = null;
let libraryButton: HTMLButtonElement | null = null;
let toastTimer: number | undefined;

function labelForMode(mode: CollectMode): string {
  return mode === "ai" ? "\u2728 AI \u6df1\u5ea6\u91c7\u96c6" : "\u26a1 \u6781\u901f\u91c7\u96c6";
}

function setButtonsDisabled(disabled: boolean): void {
  [fastButton, aiButton].forEach((button) => {
    if (button) {
      button.disabled = disabled;
      button.style.opacity = disabled ? "0.72" : "1";
      button.style.cursor = disabled ? "wait" : "pointer";
    }
  });
}

function setActiveButtonText(text: string): void {
  if (activeButton) {
    activeButton.textContent = text;
  }
}

function showToast(message: string, status: "success" | "error" = "success"): void {
  const toastId = "easycollect-toast";
  const oldToast = document.getElementById(toastId);
  if (oldToast) {
    oldToast.remove();
  }

  if (toastTimer) {
    window.clearTimeout(toastTimer);
  }

  const toast = document.createElement("div");
  toast.id = toastId;
  toast.textContent = message;
  toast.setAttribute(
    "style",
    [
      "position:fixed",
      "right:16px",
      "bottom:72px",
      "z-index:2147483647",
      "padding:10px 14px",
      "border-radius:8px",
      "box-shadow:0 12px 30px rgba(15,23,42,.22)",
      "color:#fff",
      "font:600 13px/1.35 system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif",
      `background:${status === "success" ? "#059669" : "#dc2626"}`,
      "max-width:280px",
    ].join(";"),
  );

  document.documentElement.appendChild(toast);
  toastTimer = window.setTimeout(() => toast.remove(), 2600);
}

function resetButtonSoon(): void {
  window.setTimeout(() => {
    setButtonsDisabled(false);
    if (fastButton) fastButton.textContent = labelForMode("fast");
    if (aiButton) aiButton.textContent = labelForMode("ai");
    activeButton = null;
  }, 1800);
}

function detectPlatform(): "1688" | "shopee" {
  return window.location.hostname.includes("shopee") ? "shopee" : "1688";
}

function isRecord(value: unknown): value is UnknownRecord {
  return Object.prototype.toString.call(value) === "[object Object]";
}

function findBalancedJson(text: string, startIndex: number): string | null {
  if (startIndex < 0 || text[startIndex] !== "{") {
    return null;
  }

  let depth = 0;
  let inString = false;
  let escaped = false;
  let quote: '"' | "'" | null = null;

  for (let index = startIndex; index < text.length; index += 1) {
    const char = text[index];

    if (inString) {
      if (escaped) {
        escaped = false;
        continue;
      }

      if (char === "\\") {
        escaped = true;
        continue;
      }

      if (char === quote) {
        inString = false;
        quote = null;
      }

      continue;
    }

    if (char === '"' || char === "'") {
      inString = true;
      quote = char;
      continue;
    }

    if (char === "{") {
      depth += 1;
      continue;
    }

    if (char === "}") {
      depth -= 1;
      if (depth === 0) {
        return text.slice(startIndex, index + 1);
      }
    }
  }

  return null;
}

function tryParseJson(jsonText: string): unknown | null {
  try {
    return JSON.parse(jsonText);
  } catch {
    return null;
  }
}

function scoreShopeeItemCandidate(value: unknown): number {
  if (!isRecord(value)) {
    return 0;
  }

  let score = 0;
  if (typeof value.name === "string" || typeof value.title === "string") score += 40;
  if (Array.isArray(value.images)) score += 70;
  if (typeof value.image === "string") score += 30;
  if (Array.isArray(value.tier_variations)) score += 120;
  if (Array.isArray(value.models)) score += 120;
  if (value.itemid || value.item_id) score += 60;
  if (value.shopid || value.shop_id) score += 40;
  if (value.price || value.price_min || value.price_max) score += 50;
  if (value.stock || value.normal_stock) score += 30;
  return score;
}

function findShopeeItemPayload(raw: unknown): UnknownRecord | null {
  const directPaths = [
    ["data", "item"],
    ["data", "item_info"],
    ["data", "itemInfo"],
    ["item"],
    ["item_info"],
    ["itemInfo"],
  ];

  for (const path of directPaths) {
    let current: unknown = raw;
    for (const key of path) {
      current = isRecord(current) ? current[key] : undefined;
    }

    if (scoreShopeeItemCandidate(current) > 0) {
      return current as UnknownRecord;
    }
  }

  let best: UnknownRecord | null = null;
  let bestScore = 0;
  const seen = new WeakSet<object>();

  function walk(node: unknown, depth = 0): void {
    if (!node || typeof node !== "object" || depth > 10 || seen.has(node)) {
      return;
    }

    seen.add(node);

    if (isRecord(node)) {
      const score = scoreShopeeItemCandidate(node);
      if (score > bestScore) {
        best = node;
        bestScore = score;
      }

      Object.values(node).forEach((child) => walk(child, depth + 1));
      return;
    }

    if (Array.isArray(node)) {
      node.slice(0, 400).forEach((child) => walk(child, depth + 1));
    }
  }

  walk(raw);
  return best;
}

function parseShopeeJsonCandidatesFromText(text: string): unknown[] {
  const candidates: unknown[] = [];
  const assignmentPattern =
    /(?:window\.)?(?:__INITIAL_STATE__|__SHOPEE_ITEM_V3__|__SHOP_INITIAL_STATE__|__NEXT_DATA__)\s*=\s*/g;

  for (const match of text.matchAll(assignmentPattern)) {
    const objectStart = text.indexOf("{", match.index + match[0].length);
    const jsonText = findBalancedJson(text, objectStart);
    if (!jsonText) {
      continue;
    }

    const parsed = tryParseJson(jsonText);
    if (parsed) {
      candidates.push(parsed);
    }
  }

  const itemObjectPattern = /"item"\s*:\s*(\{\s*"itemid"[\s\S]{0,600000}?\})/g;
  for (const match of text.matchAll(itemObjectPattern)) {
    if (!match[1]) {
      continue;
    }

    const objectStart = text.indexOf(match[1], match.index);
    const jsonText = findBalancedJson(text, objectStart);
    const parsed = jsonText ? tryParseJson(jsonText) : null;
    if (parsed) {
      candidates.push({ item: parsed });
      candidates.push(parsed);
    }
  }

  const markers = [
    '"tier_variations"',
    "tier_variations",
    '"models"',
    '"itemid"',
    "itemid",
    '"item_id"',
    '"shopid"',
    '"price"',
    '"price_min"',
    '"images"',
  ];
  for (const marker of markers) {
    let markerIndex = text.indexOf(marker);
    while (markerIndex !== -1) {
      const openings: number[] = [];
      for (
        let index = markerIndex;
        index >= 0 && openings.length < 60 && markerIndex - index < 800000;
        index -= 1
      ) {
        if (text[index] === "{") {
          openings.push(index);
        }
      }

      for (const opening of openings) {
        const jsonText = findBalancedJson(text, opening);
        if (!jsonText || !jsonText.includes(marker)) {
          continue;
        }

        const parsed = tryParseJson(jsonText);
        if (parsed) {
          candidates.push(parsed);
          break;
        }
      }

      markerIndex = text.indexOf(marker, markerIndex + marker.length);
    }
  }

  return candidates;
}

function readShopeeSsrData(): CachedShopeeData | undefined {
  if (detectPlatform() !== "shopee") {
    return undefined;
  }

  const candidates: { item: UnknownRecord; score: number; dataKey: string }[] = [];

  for (const script of Array.from(document.scripts)) {
    const text = script.textContent?.trim();
    if (!text) {
      continue;
    }

    if (script.type === "application/json") {
      const parsed = tryParseJson(text);
      const item = findShopeeItemPayload(parsed);
      if (item) {
        candidates.push({
          item,
          score: scoreShopeeItemCandidate(item) + 80,
          dataKey: "ssr_json_script",
        });
      }
    }

    if (
      !text.includes("tier_variations") &&
      !text.includes('"itemid"') &&
      !text.includes("itemid") &&
      !text.includes('"shopid"') &&
      !text.includes('"price"') &&
      !text.includes("__INITIAL_STATE__") &&
      !text.includes("__SHOPEE_ITEM_V3__")
    ) {
      continue;
    }

    for (const parsed of parseShopeeJsonCandidatesFromText(text)) {
      const item = findShopeeItemPayload(parsed);
      if (item) {
        candidates.push({
          item,
          score: scoreShopeeItemCandidate(item) + 120,
          dataKey: "ssr_script",
        });
      }
    }
  }

  if (!candidates.length) {
    const html = document.documentElement.innerHTML;
    if (html.includes("tier_variations") || html.includes("itemid")) {
      for (const parsed of parseShopeeJsonCandidatesFromText(html)) {
        const item = findShopeeItemPayload(parsed);
        if (item) {
          candidates.push({
            item,
            score: scoreShopeeItemCandidate(item),
            dataKey: "ssr_html",
          });
        }
      }
    }
  }

  const matched = candidates.sort((left, right) => right.score - left.score)[0];
  if (!matched) {
    return undefined;
  }

  return {
    platform: "shopee",
    dataKey: matched.dataKey,
    url: window.location.href,
    capturedAt: new Date().toISOString(),
    raw: {
      platform: "shopee",
      data: matched.item,
    },
  };
}

function requestExtraction(aiMode: boolean): Promise<StartExtractionResponse> {
  const platform = detectPlatform();
  const cachedData =
    platform === "shopee"
      ? readShopeeSsrData() ?? window.__EASYCOLLECT_CACHED_DATA__
      : window.__EASYCOLLECT_CACHED_DATA__;

  if (cachedData?.dataKey?.startsWith("ssr_")) {
    window.__EASYCOLLECT_CACHED_DATA__ = cachedData;
    console.info("[EasyCollect] using Shopee SSR payload:", cachedData.dataKey);
  }

  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(
      {
        action: START_EXTRACTION_ACTION,
        ai_mode: aiMode,
        platform,
        cached_data: cachedData,
      },
      (response) => {
      const runtimeError = chrome.runtime.lastError;

      if (runtimeError) {
        reject(new Error(runtimeError.message));
        return;
      }

      resolve(response as StartExtractionResponse);
      },
    );
  });
}

window.addEventListener("message", (event: MessageEvent<ShopeeApiMessage>) => {
  if (
    event.source !== window ||
    event.data?.source !== "easycollect-interceptor" ||
    event.data?.type !== SHOPEE_API_DATA_TYPE
  ) {
    return;
  }

  window.__EASYCOLLECT_CACHED_DATA__ = {
    platform: "shopee",
    dataKey: "network_interceptor",
    url: event.data.url ?? window.location.href,
    capturedAt: event.data.capturedAt ?? new Date().toISOString(),
    raw: event.data.payload,
  };

  console.info("[EasyCollect] cached Shopee API payload:", event.data.url);
});

async function collectCurrentPage(button: HTMLButtonElement, mode: CollectMode): Promise<void> {
  activeButton = button;
  setButtonsDisabled(true);
  button.textContent =
    mode === "ai"
      ? "AI\u91cd\u5199\u6253\u5305\u4e2d..."
      : "\u6781\u901f\u91c7\u96c6\u6253\u5305\u4e2d...";

  try {
    const response = await requestExtraction(mode === "ai");

    if (!response?.ok) {
      throw new Error(response?.error ?? "Failed to start extraction.");
    }
  } catch (error) {
    console.error("[EasyCollect] failed to start extraction:", error);
    button.textContent = "\u5931\u8d25";
    resetButtonSoon();
  }
}

function openProductLibrary(): void {
  chrome.runtime.sendMessage({ action: OPEN_DASHBOARD_ACTION }, () => {
    const runtimeError = chrome.runtime.lastError;
    if (runtimeError) {
      console.error("[EasyCollect] failed to open dashboard:", runtimeError.message);
      showToast("商品库打开失败，请刷新插件后重试", "error");
    }
  });
}

function mountShadowButton(): void {
  if (document.getElementById(ROOT_ID)) {
    return;
  }

  const host = document.createElement("div");
  host.id = ROOT_ID;
  host.style.position = "fixed";
  host.style.right = "16px";
  host.style.bottom = "16px";
  host.style.zIndex = "2147483647";

  const shadow = host.attachShadow({ mode: "open" });
  const wrapper = document.createElement("div");
  wrapper.setAttribute(
    "style",
    [
      "display:flex",
      "gap:8px",
      "align-items:center",
      "font:600 13px/1.2 system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif",
    ].join(";"),
  );

  function applyButtonStyle(
    button: HTMLButtonElement,
    background: string,
    minWidth = 108,
  ): void {
    button.setAttribute(
      "style",
      [
        "border:0",
        "border-radius:8px",
        `background:${background}`,
        "color:#ffffff",
        "font:600 13px/1.2 system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif",
        "padding:10px 12px",
        "box-shadow:0 10px 24px rgba(15,23,42,.22)",
        "cursor:pointer",
        `min-width:${minWidth}px`,
        "white-space:nowrap",
      ].join(";"),
    );
  }

  function createCollectButton(mode: CollectMode): HTMLButtonElement {
    const button = document.createElement("button");
    button.textContent = labelForMode(mode);
    button.type = "button";
    applyButtonStyle(
      button,
      mode === "ai" ? "linear-gradient(135deg,#7c3aed,#db2777)" : "#059669",
    );
    button.addEventListener("click", () => {
      void collectCurrentPage(button, mode);
    });
    return button;
  }

  function createLibraryButton(): HTMLButtonElement {
    const button = document.createElement("button");
    button.textContent = "\ud83d\udce6 \u6211\u7684\u5546\u54c1\u5e93";
    button.type = "button";
    applyButtonStyle(button, "#2563eb", 118);
    button.addEventListener("click", openProductLibrary);
    return button;
  }

  fastButton = createCollectButton("fast");
  aiButton = createCollectButton("ai");
  libraryButton = createLibraryButton();
  wrapper.append(fastButton, aiButton, libraryButton);
  shadow.appendChild(wrapper);
  document.documentElement.appendChild(host);
}

chrome.runtime.onMessage.addListener((message: CollectionStatusMessage) => {
  if (message?.type !== COLLECTION_STATUS_TYPE) {
    return false;
  }

  if (message.status === "success") {
    setActiveButtonText("已入库!");
    showToast(message.message || "采集成功，已入库！");
  } else {
    console.error("[EasyCollect] collection failed:", message.message);
    setActiveButtonText("\u5931\u8d25");
    showToast(message.message || "采集失败，请稍后重试", "error");
  }

  resetButtonSoon();
  return false;
});

mountShadowButton();

export {};
