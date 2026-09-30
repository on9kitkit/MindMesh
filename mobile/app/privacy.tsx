import { router } from "expo-router";
import { StyleSheet } from "react-native";

import {
  StudioButton,
  StudioCard,
  StudioScreen,
  StudioStack,
  StudioText,
} from "../src/components/studio/StudioPrimitives";
import { spacing } from "../src/theme";

export default function PrivacyRoute() {
  return (
    <StudioScreen>
      <StudioText variant="eyebrow">STUDYROOM</StudioText>
      <StudioText variant="title" style={styles.title}>Privacy</StudioText>
      <StudioText tone="muted" style={styles.description}>
        This short notice describes what StudyRoom currently uses to provide
        rooms, quizzes, solo practice, earned rewards, pets, subscriptions,
        support, and safety reporting.
      </StudioText>

      <StudioCard style={styles.card}>
        <StudioStack>
        <StudioText variant="heading">What we use</StudioText>
        <StudioText tone="muted" style={styles.body}>
          StudyRoom uses your Supabase identity, email, authentication session,
          display name, room memberships, quiz participation, answers, results,
          timestamps, and necessary service metadata. RevenueCat and the store
          handle purchase and entitlement records used for StudyRoom Pro. Solo
          progress, confirmed coin and streak records, and pet ownership and
          equipment are also stored for the new study features.
        </StudioText>
        </StudioStack>
      </StudioCard>

      <StudioCard style={styles.card}>
        <StudioStack>
        <StudioText variant="heading">Why we use it</StudioText>
        <StudioText tone="muted" style={styles.body}>
          We use this information to authenticate you, run invite-only rooms,
          calculate session results, provide subscription access, operate the
          service, and respond to support or safety concerns.
        </StudioText>
        </StudioStack>
      </StudioCard>

      <StudioCard style={styles.card}>
        <StudioStack>
        <StudioText variant="heading">What we do not collect</StudioText>
        <StudioText tone="muted" style={styles.body}>
          StudyRoom does not currently collect location, contacts, photos,
          advertising IDs, direct messages, chat, or public profiles. Room
          participants see display names and the room or quiz state needed for
          multiplayer. Exact answers and feedback stay viewer-private. Your own
          bounded practice summary may combine your still-retained results
          from previous rooms; there is no public performance directory.
          Your own drawing workspace stays in this app&apos;s memory and is not
          sent with an answer. It clears when you move to a new question or end
          the attempt.
        </StudioText>
        </StudioStack>
      </StudioCard>

      <StudioCard style={styles.card}>
        <StudioStack>
          <StudioText variant="heading">Your practice summary</StudioText>
          <StudioText tone="muted" style={styles.body}>
            When you are signed in, Account &amp; settings can calculate your
            own marks and topic counts on demand from finished adaptive GCSE
            sessions you participated in, including previous rooms you have
            left or that closed. It shows accuracy
            only for graded answers, separately counts unanswered and ungraded
            questions, and may include exact repeats. This creates no separate
            saved analytics profile. Existing room-data purge or account
            deletion can remove these source results, so the summary is not a
            lifetime history. These sampled StudyRoom results are not an AQA
            grade or full-syllabus assessment.
          </StudioText>
        </StudioStack>
      </StudioCard>

      <StudioCard style={styles.card}>
        <StudioStack>
        <StudioText variant="heading">Adaptive quizzes and AI marking</StudioText>
        <StudioText tone="muted" style={styles.body}>
          Generating an adaptive GCSE quiz sends the selected subject, topic,
          mark budget, and a bounded list of recent question prompts to OpenAI
          to reduce repetition. Marking a written answer sends the
          question, any source extract, the hidden marking rubric, and the
          student&apos;s answer. These requests carry no account, profile,
          room, or provider identifiers. We ask OpenAI not to store them,
          but this is not a guarantee of zero provider retention.
          Generated content, answers, and results remain stored by StudyRoom
          under the deletion and retention notice below.
        </StudioText>
        </StudioStack>
      </StudioCard>

      <StudioCard style={styles.card}>
        <StudioStack>
        <StudioText variant="heading">Deletion</StudioText>
        <StudioText tone="muted" style={styles.body}>
          You can start account deletion from Account & settings. StudyRoom
          removes or anonymizes local account data under its current deletion
          contract and schedules linked provider cleanup. Deleting StudyRoom
          does not cancel an App Store or Google Play subscription. Current
          retention periods are not yet automated. Solo
          educational questions, answers, and marks become eligible for
          retention purge 30 days after a completed, abandoned, or failed
          attempt; an attempt awaiting marking is not silently expired.
          Minimal earned-reward, study-day, and pet-ownership records remain
          until account deletion. Purge processing may occur after the
          eligibility date rather than at the exact 30-day instant.
        </StudioText>
        </StudioStack>
      </StudioCard>

      <StudioButton
        label="Support & Safety"
        onPress={() => router.push("/support")}
        variant="secondary"
      />
    </StudioScreen>
  );
}

const styles = StyleSheet.create({
  title: {
    marginTop: spacing.xs,
  },
  description: {
    marginTop: spacing.sm,
  },
  card: {
    marginTop: spacing.md,
  },
  body: {
    marginTop: spacing.sm,
  },
});
