declare namespace chrome {
  namespace runtime {
    type MessageSender = {
      tab?: {
        id?: number;
        url?: string;
      };
    };

    const lastError: { message?: string } | undefined;

    const onMessage: {
      addListener(
        callback: (
          message: any,
          sender: MessageSender,
          sendResponse: (response?: unknown) => void,
        ) => boolean | void,
      ): void;
    };

    function sendMessage(message: any, callback?: (response?: unknown) => void): void;
    function getURL(path: string): string;
  }

  namespace scripting {
    type InjectionResult<T = unknown> = {
      frameId: number;
      result?: T;
    };

    function executeScript<T>(details: {
      target: {
        tabId: number;
      };
      world: "MAIN" | "ISOLATED";
      func: () => T;
    }): Promise<InjectionResult<Awaited<T>>[]>;
  }

  namespace tabs {
    function sendMessage(tabId: number, message: any): Promise<unknown>;
    function create(
      createProperties: {
        url?: string;
        active?: boolean;
      },
      callback?: (tab?: { id?: number; url?: string }) => void,
    ): void;
  }

  namespace downloads {
    type DownloadOptions = {
      url: string;
      filename?: string;
      conflictAction?: "uniquify" | "overwrite" | "prompt";
      saveAs?: boolean;
    };

    function download(
      options: DownloadOptions,
      callback?: (downloadId?: number) => void,
    ): void;
  }
}
