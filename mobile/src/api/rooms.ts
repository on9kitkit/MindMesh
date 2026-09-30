import { apiClient, type StudyRoomApiClient } from "./client";
import { MalformedResponseError } from "./errors";
import {
  parseActiveRoomResponse,
  parseJoinByCodeResponse,
  parseQuizPreparationResponse,
  parseRoomMemberResponse,
  parseRoomMembersResponse,
  parseRoomResponse,
  type CreateRoomInput,
  type JoinByCodeResponse,
  type QuizPreparationResponse,
  type RoomMemberResponse,
  type RoomMembersResponse,
  type RoomResponse,
} from "./schemas";

const JOIN_CODE_PATTERN = /^[A-Z2-9]{6}$/;
// Two bounded 45-second generation attempts plus transport overhead.
export const QUIZ_PREPARATION_TIMEOUT_MS = 100_000;

export class InvalidJoinCodeError extends Error {
  constructor() {
    super("A room code must contain six letters or digits excluding 0 and 1.");
    this.name = "InvalidJoinCodeError";
  }
}

export function normalizeJoinCode(value: string): string {
  const normalized = value.trim().toUpperCase();
  if (!JOIN_CODE_PATTERN.test(normalized)) {
    throw new InvalidJoinCodeError();
  }
  return normalized;
}

function roomPath(roomId: string): string {
  return `/rooms/${encodeURIComponent(roomId)}`;
}

export async function createRoom(
  input: CreateRoomInput,
  client: StudyRoomApiClient = apiClient,
): Promise<RoomResponse> {
  const response = await client.requestJson("/rooms", {
    method: "POST",
    body: input,
  });
  return parseRoomResponse(response);
}

export async function joinRoomByCode(
  joinCode: string,
  client: StudyRoomApiClient = apiClient,
): Promise<JoinByCodeResponse> {
  const response = await client.requestJson("/rooms/join", {
    method: "POST",
    body: { join_code: normalizeJoinCode(joinCode) },
  });
  return parseJoinByCodeResponse(response);
}

export async function getActiveRoom(
  client: StudyRoomApiClient = apiClient,
): Promise<RoomResponse | null> {
  const response = await client.requestJson("/me/active-room");
  return parseActiveRoomResponse(response);
}

export async function getRoom(
  roomId: string,
  client: StudyRoomApiClient = apiClient,
): Promise<RoomResponse> {
  const response = await client.requestJson(roomPath(roomId));
  return parseRoomResponse(response);
}

export async function createRoomMember(
  roomId: string,
  client: StudyRoomApiClient = apiClient,
): Promise<RoomMemberResponse> {
  const response = await client.requestJson(`${roomPath(roomId)}/members`, {
    method: "POST",
    body: {},
  });
  return parseRoomMemberResponse(response);
}

export async function getRoomMembers(
  roomId: string,
  client: StudyRoomApiClient = apiClient,
): Promise<RoomMembersResponse> {
  const response = await client.requestJson(`${roomPath(roomId)}/members`);
  return parseRoomMembersResponse(response);
}

async function completeRoomLifecycle(
  roomId: string,
  action: "leave" | "close",
  client: StudyRoomApiClient,
): Promise<void> {
  const response = await client.requestJson(`${roomPath(roomId)}/${action}`, {
    method: "POST",
  });
  if (response !== undefined) {
    throw new MalformedResponseError(
      "The StudyRoom server returned an invalid room lifecycle response.",
    );
  }
}

export async function leaveRoom(
  roomId: string,
  client: StudyRoomApiClient = apiClient,
): Promise<void> {
  await completeRoomLifecycle(roomId, "leave", client);
}

export async function closeRoom(
  roomId: string,
  client: StudyRoomApiClient = apiClient,
): Promise<void> {
  await completeRoomLifecycle(roomId, "close", client);
}

export async function prepareQuiz(
  roomId: string,
  requestId: string,
  client: StudyRoomApiClient = apiClient,
): Promise<QuizPreparationResponse> {
  const response = await client.requestJson(
    `${roomPath(roomId)}/quiz-preparations`,
    {
      method: "POST",
      body: { request_id: requestId },
      timeoutMs: QUIZ_PREPARATION_TIMEOUT_MS,
    },
  );
  return parseQuizPreparationResponse(response);
}
