import type {
  JSONRPCMessage,
  MessageExtraInfo,
  Transport,
} from "@modelcontextprotocol/client";
import { JSONRPCMessageSchema } from "@modelcontextprotocol/core";

/**
 * The ext-apps `PostMessageTransport` without its debug logging. It logs every message, and the browser keeps what a
 * page logs for DevTools to show later, so every evidence file read through it would stay in memory.
 */
export class QuietPostMessageTransport implements Transport {
  onclose?: () => void;
  onerror?: (error: Error) => void;
  onmessage?: (message: JSONRPCMessage, extra?: MessageExtraInfo) => void;
  sessionId?: string;
  setProtocolVersion?: (version: string) => void;
  private readonly target: Window;
  private readonly source: MessageEventSource;

  /** Sends to `target` and hears only `source`: `window.parent` for both in a view, the view's frame in a host. */
  constructor(target: Window, source: MessageEventSource) {
    this.target = target;
    this.source = source;
  }

  private readonly listener = (event: MessageEvent) => {
    if (event.source !== this.source) {
      return;
    }
    const parsed = JSONRPCMessageSchema.safeParse(event.data);
    if (parsed.success) {
      this.onmessage?.(parsed.data);
    } else if (event.data?.jsonrpc === "2.0") {
      this.onerror?.(
        new Error(`Invalid JSON-RPC message received: ${parsed.error.message}`),
      );
    }
  };

  async start() {
    window.addEventListener("message", this.listener);
  }

  async send(message: JSONRPCMessage) {
    this.target.postMessage(message, "*");
  }

  async close() {
    window.removeEventListener("message", this.listener);
    this.onclose?.();
  }
}
