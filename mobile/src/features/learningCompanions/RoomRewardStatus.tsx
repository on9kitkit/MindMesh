import { useEffect, useRef, useState } from "react";

import { getRewardOverview, getRewardSourceStatus } from "../../api/learningCompanions";
import type { RewardSourceKind } from "../../api/learningCompanions";
import { getUserFacingErrorMessage } from "../../api/errors";
import { useStudioTheme } from "../../appearance/StudioThemeContext";
import { StudioButton, StudioCard, StudioStack, StudioText } from "../../components/studio/StudioPrimitives";
import { rewardStatusCopy, type RewardDisplayStatus } from "./rewardPresentation";

type StatusState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; status: RewardDisplayStatus; confirmedBalance: number };

export function RewardSourceStatusCard({
  sourceKind,
  sourceId,
  userId,
}: { sourceKind: RewardSourceKind; sourceId: string; userId: string }) {
  const theme = useStudioTheme();
  const requestVersion = useRef(0);
  const [reloadKey, setReloadKey] = useState(0);
  const [state, setState] = useState<StatusState>({ kind: "loading" });

  useEffect(() => {
    const version = ++requestVersion.current;
    setState({ kind: "loading" });
    void (async () => {
      try {
        const [source, overview] = await Promise.all([
          getRewardSourceStatus(sourceKind, sourceId),
          getRewardOverview(),
        ]);
        if (requestVersion.current === version) {
          setState({
            kind: "ready",
            status: source.status,
            confirmedBalance: overview.balance,
          });
        }
      } catch (error: unknown) {
        if (requestVersion.current === version) {
          setState({ kind: "error", message: getUserFacingErrorMessage(error) });
        }
      }
    })();
    return () => { requestVersion.current += 1; };
  }, [reloadKey, sourceKind, sourceId, userId]);

  return (
    <StudioCard style={{ marginTop: theme.spacing.lg }}>
      <StudioStack>
        <StudioText variant="heading">Daily study reward</StudioText>
        {state.kind === "loading" ? (
          <StudioText tone="muted">Checking this quiz with the server...</StudioText>
        ) : null}
        {state.kind === "error" ? (
          <StudioText accessibilityRole="alert" tone="error">{state.message}</StudioText>
        ) : null}
        {state.kind === "ready" ? (
          <>
            <StudioText tone={state.status === "reward_delayed" ? "error" : "muted"}>
              {rewardStatusCopy(state.status)}
            </StudioText>
            <StudioText tone="muted">Confirmed balance: {state.confirmedBalance} coins</StudioText>
          </>
        ) : null}
        <StudioButton
          label="Refresh reward status"
          variant="secondary"
          onPress={() => setReloadKey((current) => current + 1)}
        />
      </StudioStack>
    </StudioCard>
  );
}

export function RoomRewardStatus({
  sessionId,
  userId,
}: { sessionId: string; userId: string }) {
  return <RewardSourceStatusCard sourceKind="room" sourceId={sessionId} userId={userId} />;
}
