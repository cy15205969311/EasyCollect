const API_BASE_URL = "http://localhost:8000";
const START_EXTRACTION_ACTION = "START_EXTRACTION";
const COLLECTION_STATUS_TYPE = "EASYCOLLECT_COLLECTION_STATUS";

type ExtractedProductData = {
  dataKey: string;
  title: string | null;
  images: string[];
  raw: unknown;
};

type CollectPayload = ExtractedProductData & {
  source: "1688";
  url: string;
  capturedAt: string;
  ai_mode: boolean;
};

type StartExtractionMessage = {
  action?: string;
  ai_mode?: boolean;
};

type BackendResponse = {
  status?: string;
  msg?: string;
  download_url?: string;
};

function extract1688ProductData(): ExtractedProductData {
  const directKeys = [
    "FE_GLOBALS",
    "__FE_GLOBALS__",
    "__INITIAL_DATA__",
    "__pageData",
    "__pageData__",
    "wingxViewData",
    "globalData",
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
    const imageUrlRegex = /^https?:\/\/.+\.(?:jpg|jpeg|png|webp)(?:[?#].*)?$/i;

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

  const matched = [...readDirectCandidates(), ...scanWindowCandidates()].sort(
    (left, right) => right.score - left.score,
  )[0];

  if (!matched) {
    throw new Error("No 1688 product data found on window.");
  }

  const raw = toPlainData(matched.payload);

  return {
    dataKey: matched.dataKey,
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

function triggerBrowserDownload(downloadUrl: string): Promise<number | undefined> {
  return new Promise((resolve, reject) => {
    const filename = decodeURIComponent(downloadUrl.split("/").pop() ?? "EasyCollect_export.zip");

    chrome.downloads.download(
      {
        url: downloadUrl,
        filename,
        conflictAction: "uniquify",
        saveAs: false,
      },
      (downloadId) => {
        const runtimeError = chrome.runtime.lastError;

        if (runtimeError) {
          reject(new Error(runtimeError.message));
          return;
        }

        resolve(downloadId);
      },
    );
  });
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
  sendResponse: (response?: unknown) => void,
): Promise<void> {
  const tabId = sender.tab?.id;
  const tabUrl = sender.tab?.url ?? "";

  if (!tabId) {
    sendResponse({ ok: false, error: "Missing sender tab id." });
    return;
  }

  sendResponse({ ok: true });

  try {
    const aiMode = message.ai_mode === true;
    const injectionResults = await chrome.scripting.executeScript({
      target: { tabId },
      world: "MAIN",
      func: extract1688ProductData,
    });

    const extracted = injectionResults[0]?.result as ExtractedProductData | undefined;

    if (!extracted) {
      throw new Error("MAIN world extraction returned no data.");
    }

    const payload: CollectPayload = {
      source: "1688",
      url: tabUrl,
      capturedAt: new Date().toISOString(),
      ai_mode: aiMode,
      ...extracted,
    };

    console.log("[EasyCollect] extracted product data:", {
      dataKey: payload.dataKey,
      title: payload.title,
      imageCount: payload.images.length,
      aiMode: payload.ai_mode,
      url: payload.url,
    });

    const backendResult = await postToBackend(payload);

    if (backendResult?.download_url) {
      const downloadId = await triggerBrowserDownload(backendResult.download_url);
      console.log("[EasyCollect] export download started:", downloadId);
    }

    await notifyTab(tabId, "success");
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown extraction error";
    console.error("[EasyCollect] extraction pipeline failed:", error);
    await notifyTab(tabId, "error", message);
  }
}

chrome.runtime.onMessage.addListener((message: StartExtractionMessage, sender, sendResponse) => {
  if (message?.action !== START_EXTRACTION_ACTION) {
    return false;
  }

  void handleStartExtraction(message, sender, sendResponse);
  return true;
});

export {};
