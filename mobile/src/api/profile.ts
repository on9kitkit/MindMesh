import { apiClient, type StudyRoomApiClient } from "./client";
import { parseProfileResponse, type ProfileResponse } from "./schemas";

export async function updateProfile(
  displayName: string,
  client: StudyRoomApiClient = apiClient,
): Promise<ProfileResponse> {
  const response = await client.requestJson("/me/profile", {
    method: "PUT",
    body: { display_name: displayName },
  });
  return parseProfileResponse(response);
}

export async function getProfile(
  client: StudyRoomApiClient = apiClient,
): Promise<ProfileResponse> {
  const response = await client.requestJson("/me");
  return parseProfileResponse(response);
}
