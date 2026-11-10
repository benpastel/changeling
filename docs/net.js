"use strict";

// A websocket that reconnects with backoff, sending `hello()` each time it opens
// so the server can put us back in our seat.

// the server closes a tab with this code when the same player opens another;
// reconnecting would just take the seat back and close the other one
const REPLACED = 4000;

function getWebSocketServer() {
  if (window.location.hostname === "localhost") {
    // locally, the game server listens on the port after the page's: 8000 => 8001
    return `ws://localhost:${parseInt(window.location.port) + 1}/`;
  } else {
    // otherwise the server that served the page
    return `wss://${window.location.host}/`;
  }
}

class Net {
  constructor(hello, onMessage, onStatus) {
    this.hello = hello;
    this.onMessage = onMessage;
    this.onStatus = onStatus;
    this.websocket = null;
    this.backoff = 500;
  }

  connect() {
    this.onStatus("connecting");
    const websocket = new WebSocket(getWebSocketServer());
    this.websocket = websocket;

    websocket.addEventListener("open", () => {
      this.backoff = 500;
      this.onStatus("open");
      websocket.send(JSON.stringify(this.hello()));
    });

    websocket.addEventListener("message", ({ data }) => {
      this.onMessage(JSON.parse(data));
    });

    websocket.addEventListener("close", ({ code }) => {
      this.websocket = null;
      if (code === REPLACED) {
        this.onStatus("replaced");
        return;
      }
      this.onStatus("closed");
      window.setTimeout(() => this.connect(), this.backoff);
      this.backoff = Math.min(this.backoff * 2, 8000);
    });
  }

  send(event) {
    // messages while disconnected are dropped; the server replays our state on reconnect
    if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
      this.websocket.send(JSON.stringify(event));
    }
  }
}

export { Net };
