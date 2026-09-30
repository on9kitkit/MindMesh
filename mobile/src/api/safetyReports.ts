import { apiClient, type StudyRoomApiClient } from "./client";
import {
  parseSafetyReportResponse,
  type SafetyReportInput,
  type SafetyReportResponse,
} from "./schemas";

export async function submitSafetyReport(
  input: SafetyReportInput,
  client: StudyRoomApiClient = apiClient,
): Promise<SafetyReportResponse> {
  const response = await client.requestJson("/safety-reports", {
    method: "POST",
    body: {
      reported_user_id: input.reported_user_id,
      room_id: input.room_id,
      reason: input.reason,
      ...(input.details === undefined ? {} : { details: input.details }),
    },
  });
  return parseSafetyReportResponse(response);
}
