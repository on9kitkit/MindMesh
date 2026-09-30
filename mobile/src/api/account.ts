import { apiClient, type StudyRoomApiClient } from "./client";
import {
  parseAccountDeletionResponse,
  type AccountDeletionResponse,
} from "./schemas";

export async function deleteAccount(
  client: StudyRoomApiClient = apiClient,
): Promise<AccountDeletionResponse> {
  const response = await client.requestJson("/me", {
    method: "DELETE",
    body: { confirmation: "DELETE" },
  });
  return parseAccountDeletionResponse(response);
}
