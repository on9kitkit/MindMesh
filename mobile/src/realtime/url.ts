import { ApiConfigurationError } from "../api/errors";
import { normalizeApiBaseUrl } from "../api/client";
import { parseCanonicalUuid } from "./protocol";

export function deriveRoomWebSocketUrl(
  apiBaseUrl: string,
  roomId: string,
): string {
  const url = new URL(normalizeApiBaseUrl(apiBaseUrl));
  if (url.username || url.password) {
    throw new ApiConfigurationError(
      "The API base URL must not include credentials.",
    );
  }

  if (url.protocol === "http:") {
    url.protocol = "ws:";
  } else if (url.protocol === "https:") {
    url.protocol = "wss:";
  } else {
    throw new ApiConfigurationError(
      "The API base URL must use HTTP or HTTPS.",
    );
  }

  const normalizedPath = url.pathname.replace(/\/+$/, "");
  url.pathname = `${normalizedPath}/ws/rooms/${encodeURIComponent(
    parseCanonicalUuid(roomId, "room WebSocket ID"),
  )}`;
  url.search = "";
  url.hash = "";
  return url.toString();
}
