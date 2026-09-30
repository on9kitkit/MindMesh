import { apiClient, type StudyRoomApiClient } from "./client";
import {
  parseSessionReviewResponse,
  type SessionReviewResponse,
} from "./schemas";

/**
 * Load the durable private review for one finished session. The server
 * returns only the viewer's own responses, marks, and feedback; this
 * response never contains another participant's exact answers.
 */
export async function getSessionReview(
  roomId: string,
  sessionId: string,
  client: StudyRoomApiClient = apiClient,
): Promise<SessionReviewResponse> {
  const response = await client.requestJson(
    `/rooms/${encodeURIComponent(roomId)}/sessions/${encodeURIComponent(sessionId)}/review`,
  );
  return parseSessionReviewResponse(response);
}
