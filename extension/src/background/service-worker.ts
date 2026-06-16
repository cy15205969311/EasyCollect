const API_BASE_URL = "http://localhost:8000";
const START_EXTRACTION_ACTION = "START_EXTRACTION";
const OPEN_DASHBOARD_ACTION = "OPEN_DASHBOARD";
const COLLECTION_STATUS_TYPE = "EASYCOLLECT_COLLECTION_STATUS";

type ExtractedProductData = {
  dataKey: string;
  platform: "1688" | "shopee";
  title: string | null;
  images: string[];
  raw: unknown;
};

type CollectPayload = ExtractedProductData & {
  source: "1688" | "shopee";
  url: string;
  capturedAt: string;
  ai_mode: boolean;
};

type StartExtractionMessage = {
  action?: string;
  ai_mode?: boolean;
  platform?: "1688" | "shopee";
  cached_data?: {
    platform?: "shopee";
    dataKey?: string;
    url?: string;
    capturedAt?: string;
    raw?: unknown;
  };
};

type BackendResponse = {
  status?: string;
  msg?: string;
  message?: string;
  product_id?: string;
};

type StartExtractionResult = {
  ok: boolean;
  product_id?: string;
  error?: string;
};

function extractProductData(): ExtractedProductData {
  const directKeys = [
    "FE_GLOBALS",
    "__FE_GLOBALS__",
    "__INITIAL_DATA__",
    "__pageData",
    "__pageData__",
    "wingxViewData",
    "globalData",
    "__INITIAL_STATE__",
    "__SHOPEE_ITEM_V3__",
    "__SHOP_INITIAL_STATE__",
  ];

  function isPlainObject(value: unknown): value is Record<string, unknown> {
    return Object.prototype.toString.call(value) === "[object Object]";
  }

  function toPlainData(value: unknown, depth = 0, seen = new WeakSet<object>()): unknown {
    if (
      value == null ||
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean"
    ) {
      return value;
    }

    if (typeof value === "bigint") {
      return String(value);
    }

    if (typeof value !== "object") {
      return undefined;
    }

    if (seen.has(value)) {
      return "[Circular]";
    }

    if (depth > 8) {
      return "[MaxDepth]";
    }

    seen.add(value);

    if (Array.isArray(value)) {
      return value.slice(0, 300).map((item) => toPlainData(item, depth + 1, seen));
    }

    if (!isPlainObject(value)) {
      try {
        return JSON.parse(JSON.stringify(value));
      } catch {
        return String(value);
      }
    }

    const output: Record<string, unknown> = {};

    Object.keys(value)
      .slice(0, 500)
      .forEach((key) => {
        try {
          const child = toPlainData(value[key], depth + 1, seen);

          if (child !== undefined) {
            output[key] = child;
          }
        } catch {
          output[key] = "[Unreadable]";
        }
      });

    return output;
  }

  function safeJsonClone(value: unknown): unknown {
    const seen = new WeakSet<object>();

    try {
      const jsonText = JSON.stringify(value, (_key, child) => {
        if (typeof child === "bigint") {
          return String(child);
        }

        if (typeof child === "function" || typeof child === "symbol") {
          return undefined;
        }

        if (child && typeof child === "object") {
          if (seen.has(child)) {
            return undefined;
          }
          seen.add(child);
        }

        return child;
      });

      return jsonText ? JSON.parse(jsonText) : null;
    } catch {
      return toPlainData(value);
    }
  }

  function getByPath(value: unknown, path: string[]): unknown {
    let current = value;
    for (const key of path) {
      if (!current || typeof current !== "object") {
        return undefined;
      }
      current = (current as Record<string, unknown>)[key];
    }
    return current;
  }

  function setByPath(target: Record<string, unknown>, path: string[], value: unknown): void {
    if (value == null) {
      return;
    }

    let current: Record<string, unknown> = target;
    path.slice(0, -1).forEach((key) => {
      if (!isPlainObject(current[key])) {
        current[key] = {};
      }
      current = current[key] as Record<string, unknown>;
    });

    current[path[path.length - 1]] = safeJsonClone(value);
  }

  function findNodesByKey(value: unknown, targetKeys: Set<string>, limit = 12): unknown[] {
    const matches: unknown[] = [];
    const seen = new WeakSet<object>();

    function walk(node: unknown): void {
      if (!node || typeof node !== "object" || seen.has(node) || matches.length >= limit) {
        return;
      }

      seen.add(node);

      if (Array.isArray(node)) {
        node.forEach(walk);
        return;
      }

      const record = node as Record<string, unknown>;
      for (const [key, child] of Object.entries(record)) {
        if (targetKeys.has(key)) {
          matches.push(child);
          if (matches.length >= limit) {
            return;
          }
        }
        walk(child);
        if (matches.length >= limit) {
          return;
        }
      }
    }

    walk(value);
    return matches;
  }

  function findEntriesByKey(
    value: unknown,
    targetKeys: Set<string>,
    limit = 12,
  ): { key: string; value: unknown }[] {
    const matches: { key: string; value: unknown }[] = [];
    const seen = new WeakSet<object>();

    function walk(node: unknown): void {
      if (!node || typeof node !== "object" || seen.has(node) || matches.length >= limit) {
        return;
      }

      seen.add(node);

      if (Array.isArray(node)) {
        node.forEach(walk);
        return;
      }

      const record = node as Record<string, unknown>;
      for (const [key, child] of Object.entries(record)) {
        if (targetKeys.has(key)) {
          matches.push({ key, value: child });
          if (matches.length >= limit) {
            return;
          }
        }
        walk(child);
        if (matches.length >= limit) {
          return;
        }
      }
    }

    walk(value);
    return matches;
  }

  function build1688CleanPayload(payload: unknown): unknown {
    const cleanPayload: Record<string, unknown> = {};
    const businessPaths = [
      ["globalData"],
      ["dataJson"],
      ["tradeModel"],
      ["model"],
      ["model", "offerDetail"],
      ["model", "skuModel"],
      ["model", "tradeModel"],
      ["model", "tradeModel", "tradeWithoutPromotion"],
      ["result", "global", "globalData"],
      ["result", "global", "globalData", "model"],
      ["result", "global", "globalData", "model", "offerDetail"],
      ["result", "global", "globalData", "model", "skuModel"],
      ["result", "global", "globalData", "model", "tradeModel"],
      ["result", "data", "Root", "fields", "dataJson"],
      ["result", "data", "Root", "fields", "dataJson", "skuModel"],
      ["result", "data", "mainPrice", "fields", "finalPriceModel"],
    ];

    for (const path of businessPaths) {
      const value = getByPath(payload, path);
      if (value != null) {
        setByPath(cleanPayload, path, value);
      }
    }

    const skuPropsNodes = findNodesByKey(payload, new Set(["skuProps"]), 8);
    if (skuPropsNodes.length) {
      cleanPayload.skuProps = safeJsonClone(skuPropsNodes[0]);
      cleanPayload.__easycollect_skuProps = safeJsonClone(skuPropsNodes);
    }

    const skuMapNodes = findEntriesByKey(
      payload,
      new Set(["skuMap", "skuInfoMap", "skuMapOriginal", "skuInfoMapOriginal"]),
      12,
    );
    skuMapNodes.forEach((entry, index) => {
      setByPath(cleanPayload, ["__easycollect_skuMaps", String(index), entry.key], entry.value);
    });

    if (!Object.keys(cleanPayload).length) {
      return safeJsonClone(payload);
    }

    return cleanPayload;
  }

  function containsOfferMarker(value: unknown, depth = 0, seen = new WeakSet<object>()): boolean {
    if (!value || typeof value !== "object" || depth > 4 || seen.has(value)) {
      return false;
    }

    seen.add(value);

    let keys: string[] = [];
    try {
      keys = Object.keys(value);
    } catch {
      return false;
    }

    const joinedKeys = keys.join("|").toLowerCase();
    if (
      joinedKeys.includes("offerdomain") ||
      joinedKeys.includes("offerid") ||
      joinedKeys.includes("offeridstr") ||
      joinedKeys.includes("subject") ||
      joinedKeys.includes("sku") ||
      joinedKeys.includes("images") ||
      joinedKeys.includes("product")
    ) {
      return true;
    }

    return keys.slice(0, 80).some((key) => {
      try {
        return containsOfferMarker((value as Record<string, unknown>)[key], depth + 1, seen);
      } catch {
        return false;
      }
    });
  }

  function walkObject(value: unknown, visitor: (key: string, node: unknown) => void): void {
    const seen = new WeakSet<object>();

    function visit(node: unknown, key = ""): void {
      if (!node || typeof node !== "object" || seen.has(node)) {
        return;
      }

      seen.add(node);
      visitor(key, node);

      if (Array.isArray(node)) {
        node.slice(0, 80).forEach((item, index) => visit(item, String(index)));
        return;
      }

      Object.entries(node as Record<string, unknown>)
        .slice(0, 160)
        .forEach(([childKey, childValue]) => visit(childValue, childKey));
    }

    visit(value);
  }

  function pickTitle(raw: unknown): string | null {
    const candidates = ["title", "subject", "offerTitle", "productTitle", "name"];
    let title: string | null = null;

    walkObject(raw, (_key, node) => {
      if (title || !node || typeof node !== "object" || Array.isArray(node)) {
        return;
      }

      const record = node as Record<string, unknown>;

      for (const candidate of candidates) {
        const value = record[candidate];

        if (typeof value === "string" && value.trim().length > 0) {
          title = value.trim();
          return;
        }
      }
    });

    return title;
  }

  function pickImages(raw: unknown): string[] {
    const images = new Set<string>();
    const imageUrlRegex = /^https?:\/\/.+(?:\.(?:jpg|jpeg|png|webp)(?:[?#].*)?|\/file\/[a-zA-Z0-9_-]+)$/i;

    walkObject(raw, (_key, node) => {
      if (images.size >= 30) {
        return;
      }

      if (typeof node === "string" && imageUrlRegex.test(node)) {
        images.add(node);
        return;
      }

      if (Array.isArray(node)) {
        node.forEach((item) => {
          if (typeof item === "string" && imageUrlRegex.test(item)) {
            images.add(item);
          }
        });
      }
    });

    return Array.from(images);
  }

  function detectPlatform(): "1688" | "shopee" {
    return window.location.hostname.includes("shopee") ? "shopee" : "1688";
  }

  function readJsonFromScripts(markers: string[]): unknown | null {
    const scripts = Array.from(document.scripts);

    for (const script of scripts) {
      const text = script.textContent ?? "";
      if (!markers.some((marker) => text.includes(marker))) {
        continue;
      }

      if (script.type === "application/json" && text.trim()) {
        try {
          return JSON.parse(text);
        } catch {
          // Continue to assignment parsing below.
        }
      }

      const assignmentMatch = text.match(
        /(?:window\.)?(__INITIAL_STATE__|__SHOPEE_ITEM_V3__|__SHOP_INITIAL_STATE__)\s*=\s*(\{[\s\S]*?\});?\s*(?:<\/script>)?$/m,
      );
      if (assignmentMatch?.[2]) {
        try {
          return JSON.parse(assignmentMatch[2]);
        } catch {
          // Ignore malformed or non-JSON assignments.
        }
      }
    }

    return null;
  }

  function buildShopeeDomFallback(): Record<string, unknown> {
    const title =
      document.querySelector<HTMLMetaElement>('meta[property="og:title"]')?.content ??
      document.querySelector<HTMLMetaElement>('meta[name="twitter:title"]')?.content ??
      document.title;
    const description =
      document.querySelector<HTMLMetaElement>('meta[property="og:description"]')?.content ??
      document.querySelector<HTMLMetaElement>('meta[name="description"]')?.content ??
      "";
    const image =
      document.querySelector<HTMLMetaElement>('meta[property="og:image"]')?.content ??
      document.querySelector<HTMLMetaElement>('meta[name="twitter:image"]')?.content ??
      "";

    return {
      item: {
        name: title,
        description,
        images: image ? [image] : [],
      },
      dom_price: readShopeeDomPrice(),
      domFallback: true,
    };
  }

  function readShopeeDomPrice(): string {
    const text = document.body?.innerText || "";
    const pricePattern = /\b(?:RM|MYR)\s*\d+(?:[.,]\d{1,2})?(?:\s*[-–~]\s*(?:RM|MYR)?\s*\d+(?:[.,]\d{1,2})?)?/i;
    return text.match(pricePattern)?.[0]?.trim() || "";
  }

  function extractShopeeProductData(): ExtractedProductData {
    const shopeeKeys = [
      "__INITIAL_STATE__",
      "__SHOPEE_ITEM_V3__",
      "__SHOP_INITIAL_STATE__",
      "__NEXT_DATA__",
    ];
    const candidates: { dataKey: string; payload: unknown; score: number }[] = [];

    function scoreShopeeCandidate(value: unknown, depth = 0, seen = new WeakSet<object>()): number {
      if (!value || typeof value !== "object" || depth > 6 || seen.has(value)) {
        return 0;
      }

      seen.add(value);

      let keys: string[] = [];
      try {
        keys = Object.keys(value);
      } catch {
        return 0;
      }

      const joinedKeys = keys.join("|").toLowerCase();
      let score = 0;
      if (joinedKeys.includes("tier_variations")) score += 180;
      if (joinedKeys.includes("models")) score += 180;
      if (joinedKeys.includes("itemid") || joinedKeys.includes("item_id")) score += 80;
      if (joinedKeys.includes("shopid") || joinedKeys.includes("shop_id")) score += 60;
      if (joinedKeys.includes("price_min") || joinedKeys.includes("price")) score += 80;
      if (joinedKeys.includes("stock")) score += 60;
      if (joinedKeys.includes("images") || joinedKeys.includes("image")) score += 80;
      if (joinedKeys.includes("name") || joinedKeys.includes("title")) score += 40;

      for (const key of keys.slice(0, 120)) {
        try {
          score += scoreShopeeCandidate((value as Record<string, unknown>)[key], depth + 1, seen);
        } catch {
          // Ignore noisy nested getters.
        }
      }

      return score;
    }

    for (const key of shopeeKeys) {
      try {
        const value = (window as unknown as Record<string, unknown>)[key];
        if (value && typeof value === "object") {
          candidates.push({ dataKey: key, payload: value, score: scoreShopeeCandidate(value) + 800 });
        }
      } catch {
        // Ignore protected getters.
      }
    }

    const scriptPayload = readJsonFromScripts([
      "__INITIAL_STATE__",
      "__SHOPEE_ITEM_V3__",
      "tier_variations",
      "models",
    ]);
    if (scriptPayload) {
      candidates.push({ dataKey: "script_state", payload: scriptPayload, score: scoreShopeeCandidate(scriptPayload) + 500 });
    }

    const matched = candidates.sort((left, right) => right.score - left.score)[0];
    const raw = toPlainData(matched?.payload ?? buildShopeeDomFallback());
    const rawRecord = isPlainObject(raw) ? raw : { data: raw };
    rawRecord.dom_price = readShopeeDomPrice();

    return {
      dataKey: matched?.dataKey ?? "dom_fallback",
      platform: "shopee",
      title: pickTitle(rawRecord),
      images: pickImages(rawRecord),
      raw: rawRecord,
    };
  }

  function scoreCandidate(value: unknown, depth = 0, seen = new WeakSet<object>()): number {
    if (!value || typeof value !== "object" || depth > 5 || seen.has(value)) {
      return 0;
    }

    seen.add(value);

    let keys: string[] = [];
    try {
      keys = Object.keys(value);
    } catch {
      return 0;
    }

    const joinedKeys = keys.join("|").toLowerCase();
    let score = Math.min(keys.length, 80);

    if (
      keys.includes("cache") &&
      keys.includes("test") &&
      typeof (value as Record<string, unknown>).cache === "object"
    ) {
      score -= 500;
    }

    if (
      joinedKeys.includes("assets") &&
      joinedKeys.includes("modules") &&
      joinedKeys.includes("combo")
    ) {
      score -= 500;
    }

    if (joinedKeys.includes("feglobals")) score += 120;
    if (joinedKeys.includes("globaldata")) score += 120;
    if (joinedKeys.includes("offerdomain")) score += 100;
    if (joinedKeys.includes("tempmodel")) score += 80;
    if (joinedKeys.includes("offername")) score += 90;
    if (joinedKeys.includes("subject")) score += 80;
    if (joinedKeys.includes("title")) score += 50;
    if (joinedKeys.includes("crossborderimages")) score += 100;
    if (joinedKeys.includes("picurls")) score += 90;
    if (joinedKeys.includes("images")) score += 70;
    if (joinedKeys.includes("refprice")) score += 80;
    if (joinedKeys.includes("price")) score += 50;
    if (joinedKeys.includes("offerid")) score += 20;

    for (const key of keys.slice(0, 80)) {
      try {
        score += scoreCandidate((value as Record<string, unknown>)[key], depth + 1, seen);
      } catch {
        // Ignore noisy nested getters.
      }
    }

    return score;
  }

  function readDirectCandidates(): { dataKey: string; payload: unknown; score: number }[] {
    const candidates: { dataKey: string; payload: unknown; score: number }[] = [];

    for (const key of directKeys) {
      try {
        const value = (window as unknown as Record<string, unknown>)[key];

        if (value && typeof value === "object") {
          const directScoreBoost = key.toLowerCase().includes("lofty") ? 0 : 500;
          candidates.push({
            dataKey: key,
            payload: value,
            score: scoreCandidate(value) + directScoreBoost,
          });
        }
      } catch {
        // Ignore protected getters or inaccessible globals.
      }
    }

    return candidates;
  }

  function scanWindowCandidates(): { dataKey: string; payload: unknown; score: number }[] {
    const globalWindow = window as unknown as Record<string, unknown>;
    const candidates: { dataKey: string; payload: unknown; score: number }[] = [];

    for (const key of Object.keys(globalWindow)) {
      try {
        const value = globalWindow[key];

        if (value && typeof value === "object" && containsOfferMarker(value)) {
          candidates.push({ dataKey: key, payload: value, score: scoreCandidate(value) });
        }
      } catch {
        // Ignore noisy globals that throw when read.
      }
    }

    return candidates;
  }

  if (detectPlatform() === "shopee") {
    return extractShopeeProductData();
  }

  const matched = [...readDirectCandidates(), ...scanWindowCandidates()].sort(
    (left, right) => right.score - left.score,
  )[0];

  if (!matched) {
    throw new Error("No 1688 product data found on window.");
  }

  const raw = build1688CleanPayload(matched.payload);

  return {
    dataKey: matched.dataKey,
    platform: "1688",
    title: pickTitle(raw),
    images: pickImages(raw),
    raw,
  };
}

async function postToBackend(payload: CollectPayload): Promise<BackendResponse | null> {
  const response = await fetch(`${API_BASE_URL}/api/collect`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  const data = (await response.json().catch(() => null)) as BackendResponse | null;

  if (!response.ok) {
    throw new Error(data ? JSON.stringify(data) : `Backend returned ${response.status}`);
  }

  return data;
}

async function notifyTab(tabId: number, status: "success" | "error", message?: string): Promise<void> {
  await chrome.tabs
    .sendMessage(tabId, {
      type: COLLECTION_STATUS_TYPE,
      status,
      message,
    })
    .catch(() => undefined);
}

async function handleStartExtraction(
  message: StartExtractionMessage,
  sender: chrome.runtime.MessageSender,
): Promise<StartExtractionResult> {
  const tabId = sender.tab?.id;
  const tabUrl = sender.tab?.url ?? "";

  if (!tabId) {
    return { ok: false, error: "Missing sender tab id." };
  }

  const aiMode = message.ai_mode === true;
  const cachedShopeeData = message.cached_data;
  let extracted: ExtractedProductData | undefined;

  if (message.platform === "shopee" && cachedShopeeData?.raw) {
    extracted = {
      dataKey: cachedShopeeData.dataKey ?? "network_interceptor",
      platform: "shopee",
      title: null,
      images: [],
      raw: cachedShopeeData.raw,
    };
  } else {
    const injectionResults = await chrome.scripting.executeScript({
      target: { tabId },
      world: "MAIN",
      func: extractProductData,
    });

    extracted = injectionResults[0]?.result as ExtractedProductData | undefined;
  }

  if (!extracted) {
    throw new Error("MAIN world extraction returned no data.");
  }

  const payload: CollectPayload = {
    source: extracted.platform,
    url: tabUrl,
    capturedAt: new Date().toISOString(),
    ai_mode: aiMode,
    ...extracted,
  };

  console.log("[EasyCollect] extracted product data:", {
    dataKey: payload.dataKey,
    platform: payload.platform,
    title: payload.title,
    imageCount: payload.images.length,
    aiMode: payload.ai_mode,
    url: payload.url,
  });

  const backendResult = await postToBackend(payload);

  await notifyTab(tabId, "success", backendResult?.message ?? backendResult?.msg ?? "采集成功，已入库！");
  return {
    ok: true,
    product_id: backendResult?.product_id,
  };
}

function safeSendResponse(
  sendResponse: (response?: unknown) => void,
  response: StartExtractionResult,
): void {
  try {
    sendResponse(response);
  } catch (error) {
    console.warn("[EasyCollect] sendResponse failed; sender may have gone away:", error);
  }
}

chrome.runtime.onMessage.addListener((message: StartExtractionMessage, sender, sendResponse) => {
  if (message?.action === OPEN_DASHBOARD_ACTION) {
    try {
      chrome.tabs.create({ url: chrome.runtime.getURL("dashboard.html") });
      safeSendResponse(sendResponse, { ok: true });
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Failed to open dashboard";
      console.error("[EasyCollect] open dashboard failed:", error);
      safeSendResponse(sendResponse, { ok: false, error: errorMessage });
    }

    return true;
  }

  if (message?.action !== START_EXTRACTION_ACTION) {
    return false;
  }

  void (async () => {
    try {
      const result = await handleStartExtraction(message, sender);
      safeSendResponse(sendResponse, result);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Unknown extraction error";
      console.error("[EasyCollect] extraction pipeline failed:", error);
      if (sender.tab?.id) {
        await notifyTab(sender.tab.id, "error", errorMessage);
      }
      safeSendResponse(sendResponse, { ok: false, error: errorMessage });
    }
  })();

  return true;
});

export {};
