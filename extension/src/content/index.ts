const ROOT_ID = "easycollect-shadow-root";
const START_EXTRACTION_ACTION = "START_EXTRACTION";
const COLLECTION_STATUS_TYPE = "EASYCOLLECT_COLLECTION_STATUS";

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

let activeButton: HTMLButtonElement | null = null;
let fastButton: HTMLButtonElement | null = null;
let aiButton: HTMLButtonElement | null = null;

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

function resetButtonSoon(): void {
  window.setTimeout(() => {
    setButtonsDisabled(false);
    if (fastButton) fastButton.textContent = labelForMode("fast");
    if (aiButton) aiButton.textContent = labelForMode("ai");
    activeButton = null;
  }, 1800);
}

function requestExtraction(aiMode: boolean): Promise<StartExtractionResponse> {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage({ action: START_EXTRACTION_ACTION, ai_mode: aiMode }, (response) => {
      const runtimeError = chrome.runtime.lastError;

      if (runtimeError) {
        reject(new Error(runtimeError.message));
        return;
      }

      resolve(response as StartExtractionResponse);
    });
  });
}

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

  function createButton(mode: CollectMode): HTMLButtonElement {
    const button = document.createElement("button");
    button.textContent = labelForMode(mode);
    button.type = "button";
    button.setAttribute(
      "style",
      [
        "border:0",
        "border-radius:8px",
        mode === "ai"
          ? "background:linear-gradient(135deg,#7c3aed,#db2777)"
          : "background:#059669",
        "color:#ffffff",
        "font:600 13px/1.2 system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif",
        "padding:10px 12px",
        "box-shadow:0 10px 24px rgba(15,23,42,.22)",
        "cursor:pointer",
        "min-width:108px",
        "white-space:nowrap",
      ].join(";"),
    );
    button.addEventListener("click", () => {
      void collectCurrentPage(button, mode);
    });
    return button;
  }

  fastButton = createButton("fast");
  aiButton = createButton("ai");
  wrapper.append(fastButton, aiButton);
  shadow.appendChild(wrapper);
  document.documentElement.appendChild(host);
}

chrome.runtime.onMessage.addListener((message: CollectionStatusMessage) => {
  if (message?.type !== COLLECTION_STATUS_TYPE) {
    return false;
  }

  if (message.status === "success") {
    setActiveButtonText("\u6210\u529f!");
  } else {
    console.error("[EasyCollect] collection failed:", message.message);
    setActiveButtonText("\u5931\u8d25");
  }

  resetButtonSoon();
  return false;
});

mountShadowButton();

export {};
