const MESSAGE_TYPE = "EASYCOLLECT_SHOPEE_API_DATA";

type ShopeeInterceptMessage = {
  source: "easycollect-interceptor";
  type: typeof MESSAGE_TYPE;
  url: string;
  payload: unknown;
  capturedAt: string;
};

declare global {
  interface Window {
    __EASYCOLLECT_INTERCEPTOR_INSTALLED__?: boolean;
  }

  interface XMLHttpRequest {
    __easycollect_url__?: string;
  }
}

function isShopeeProductApi(url: string): boolean {
  const parsedUrl = new URL(url, window.location.href);
  const normalizedPath = parsedUrl.pathname.toLowerCase();
  const normalizedFullUrl = parsedUrl.toString().toLowerCase();
  const ignoredMarkers = ["recommend", "tracking", "batch", "ads", "similar", "bundle"];

  if (ignoredMarkers.some((marker) => normalizedFullUrl.includes(marker))) {
    return false;
  }

  return normalizedPath === "/api/v4/item/get" || normalizedPath.endsWith("/api/v4/item/get");
}

function toAbsoluteUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") {
    return new URL(input, window.location.href).toString();
  }

  if (input instanceof URL) {
    return input.toString();
  }

  return new URL(input.url, window.location.href).toString();
}

function postShopeePayload(url: string, payload: unknown): void {
  const message: ShopeeInterceptMessage = {
    source: "easycollect-interceptor",
    type: MESSAGE_TYPE,
    url,
    payload,
    capturedAt: new Date().toISOString(),
  };

  const targetWindow = globalThis.window;
  if (targetWindow && typeof targetWindow.postMessage === "function") {
    targetWindow.postMessage(message, "*");
  }
}

function installFetchInterceptor(): void {
  const nativeFetch = window.fetch.bind(window);

  window.fetch = async (...args) => {
    const response = await nativeFetch(...args);

    try {
      const requestUrl = toAbsoluteUrl(args[0]);
      if (isShopeeProductApi(requestUrl)) {
        response
          .clone()
          .json()
          .then((payload) => postShopeePayload(requestUrl, payload))
          .catch(() => undefined);
      }
    } catch {
      // Keep the page request path untouched even if our observer fails.
    }

    return response;
  };
}

function installXhrInterceptor(): void {
  const nativeOpen = XMLHttpRequest.prototype.open;
  const nativeSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function open(
    method: string,
    url: string | URL,
    async?: boolean,
    username?: string | null,
    password?: string | null,
  ): void {
    const requestUrl = new URL(String(url), window.location.href).toString();
    this.__easycollect_url__ = requestUrl;
    return nativeOpen.call(this, method, url, async ?? true, username ?? null, password ?? null);
  };

  XMLHttpRequest.prototype.send = function send(body?: Document | XMLHttpRequestBodyInit | null): void {
    const requestUrl = this.__easycollect_url__;

    if (requestUrl && isShopeeProductApi(requestUrl)) {
      this.addEventListener("load", () => {
        try {
          const contentType = this.getResponseHeader("content-type") ?? "";
          const isJson = contentType.includes("json") || typeof this.responseText === "string";
          if (!isJson || !this.responseText) {
            return;
          }

          postShopeePayload(requestUrl, JSON.parse(this.responseText));
        } catch {
          // Ignore non-JSON or unreadable XHR responses.
        }
      });
    }

    return nativeSend.call(this, body);
  };
}

if (!window.__EASYCOLLECT_INTERCEPTOR_INSTALLED__) {
  window.__EASYCOLLECT_INTERCEPTOR_INSTALLED__ = true;
  installFetchInterceptor();
  installXhrInterceptor();
}

export {};
