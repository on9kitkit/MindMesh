import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import type { ThemeTokens } from "../../theme";
import { PetCompanion } from "./PetCompanion";
import { PET_IDS, getPetCopy, type PetAnimationVariant, type PetId } from "./petPresentation";
import {
  EARNED_CELEBRATION_ID,
  PRO_FLOURISH_ID,
  STUDY_SCARF_ID,
  confirmedBalance,
  getAvailableAnimationVariant,
  getPetReviewPrompt,
  getPreviewPet,
  getPurchaseOffer,
  isPetId,
  type ConfirmedPetGallery,
  type PetGalleryState,
  type PetReviewChoice,
  type ProAvailability,
  type PurchasablePetItemId,
  type PurchaseOffer,
} from "./petGalleryPresentation";

export type PetGalleryProps = {
  theme: ThemeTokens;
  state: PetGalleryState;
  proAvailability: ProAvailability;
  /** Externally supplied presentation preference; Pro is not wallet ownership. */
  selectedAnimationVariant: PetAnimationVariant;
  animationsEnabled: boolean;
  onRequestStarterClaim: (petId: PetId) => void | Promise<void>;
  onRequestPurchase: (itemId: PurchasablePetItemId) => void | Promise<void>;
  onRequestEquipPet: (petId: PetId) => void | Promise<void>;
  onRequestScarfEquipped: (equipped: boolean) => void | Promise<void>;
  onRequestAnimationVariant: (variant: PetAnimationVariant) => void | Promise<void>;
  onRequestAnimationsEnabled: (enabled: boolean) => void;
  onRetryLoad?: () => void;
  testID?: string;
};

const ITEM_NAMES: Readonly<Record<PurchasablePetItemId, string>> = {
  "pet.owl": "Owl",
  "pet.tortoise": "Tortoise",
  "pet.fox": "Fox",
  [STUDY_SCARF_ID]: "Study scarf",
  [EARNED_CELEBRATION_ID]: "Earned celebration",
};

function GalleryText({
  children,
  theme,
  muted = false,
  role,
  testID,
}: {
  children: ReactNode;
  theme: ThemeTokens;
  muted?: boolean;
  role?: "alert" | "header";
  testID?: string;
}) {
  return (
    <Text
      accessibilityRole={role}
      style={[
        role === "header" ? theme.typography.heading : theme.typography.body,
        { color: muted ? theme.colors.mutedText : theme.colors.text },
      ]}
      testID={testID}
    >
      {children}
    </Text>
  );
}

function GalleryButton({
  label,
  onPress,
  theme,
  disabled = false,
  secondary = false,
  testID,
}: {
  label: string;
  onPress: () => void;
  theme: ThemeTokens;
  disabled?: boolean;
  secondary?: boolean;
  testID?: string;
}) {
  return (
    <Pressable
      accessibilityLabel={label}
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={[
        styles.button,
        {
          backgroundColor: disabled
            ? theme.colors.surfaceElevated
            : secondary
              ? theme.colors.surfaceElevated
              : theme.colors.primary,
          borderColor: disabled || secondary ? theme.colors.border : theme.colors.primary,
          borderRadius: theme.radii.md,
        },
      ]}
      testID={testID}
    >
      <Text
        style={[
          theme.typography.body,
          {
            color: disabled
              ? theme.colors.mutedText
              : secondary
                ? theme.colors.text
                : theme.colors.onPrimary,
            fontWeight: "700",
            textAlign: "center",
          },
        ]}
      >
        {label}
      </Text>
    </Pressable>
  );
}

function GalleryItem({
  title,
  detail,
  theme,
  children,
  testID,
}: {
  title: string;
  detail: string;
  theme: ThemeTokens;
  children?: ReactNode;
  testID: string;
}) {
  return (
    <View
      style={[
        styles.item,
        {
          backgroundColor: theme.colors.surface,
          borderColor: theme.colors.border,
          borderRadius: theme.radii.md,
          padding: theme.spacing.md,
          gap: theme.spacing.sm,
        },
      ]}
      testID={testID}
    >
      <Text style={[theme.typography.heading, { color: theme.colors.text }]}>{title}</Text>
      <GalleryText muted theme={theme}>{detail}</GalleryText>
      {children}
    </View>
  );
}

function offerLabel(offer: PurchaseOffer, name: string): string {
  switch (offer.status) {
    case "owned":
      return "Owned";
    case "free-starter":
      return `Review ${name} as your free starter`;
    case "available":
      return `Review ${name} purchase for ${offer.price} coins`;
    case "insufficient":
      return `Need ${offer.shortfall} more coins for ${name}`;
    case "unavailable":
      return `Purchase unavailable for ${name}`;
  }
}

function catalogPriceLabel(snapshot: ConfirmedPetGallery, itemId: PurchasablePetItemId) {
  const price = snapshot.catalogPrices[itemId];
  return typeof price === "number" && Number.isSafeInteger(price) && price > 0
    ? `${price} coins`
    : "Price unavailable";
}

function canReview(offer: PurchaseOffer): boolean {
  return offer.status === "free-starter" || offer.status === "available";
}

/** A presentation surface: request callbacks and confirmed props own all mutations. */
export function PetGallery({
  theme,
  state,
  proAvailability,
  selectedAnimationVariant,
  animationsEnabled,
  onRequestStarterClaim,
  onRequestPurchase,
  onRequestEquipPet,
  onRequestScarfEquipped,
  onRequestAnimationVariant,
  onRequestAnimationsEnabled,
  onRetryLoad,
  testID = "pet-gallery",
}: PetGalleryProps) {
  const [reviewChoice, setReviewChoice] = useState<PetReviewChoice | null>(null);
  const [locallySubmitting, setLocallySubmitting] = useState(false);
  const submittedRef = useRef(false);
  const submissionSequence = useRef(0);
  const pending = state.status === "ready" ? state.pending : null;
  const operationError = state.status === "ready" ? state.operationError : null;

  useEffect(() => {
    if (state.status !== "ready") setReviewChoice(null);
    if (state.status !== "ready" || pending !== null || operationError !== null) {
      submittedRef.current = false;
      setLocallySubmitting(false);
    }
  }, [state.status, pending, operationError]);

  const submit = (request: () => void | Promise<void>) => {
    if (state.status !== "ready" || pending !== null || submittedRef.current) return;
    submittedRef.current = true;
    setLocallySubmitting(true);
    const sequence = ++submissionSequence.current;
    try {
      void Promise.resolve(request()).then(
        () => {
          if (submissionSequence.current === sequence) {
            submittedRef.current = false;
            setLocallySubmitting(false);
          }
        },
        () => {
          if (submissionSequence.current === sequence) {
            submittedRef.current = false;
            setLocallySubmitting(false);
          }
        },
      );
    } catch {
      submittedRef.current = false;
      setLocallySubmitting(false);
    }
  };

  const containerStyle = [
    styles.container,
    { backgroundColor: theme.colors.background, gap: theme.spacing.md },
  ];
  if (state.status === "loading") {
    return (
      <View style={containerStyle} testID={testID}>
        <GalleryText role="header" theme={theme}>Companions</GalleryText>
        <GalleryText theme={theme} testID={`${testID}-loading`}>
          Loading your confirmed pets and coin balance…
        </GalleryText>
      </View>
    );
  }
  if (state.status === "error") {
    return (
      <View style={containerStyle} testID={testID}>
        <GalleryText role="header" theme={theme}>Companions</GalleryText>
        <GalleryText role="alert" theme={theme} testID={`${testID}-error`}>
          {state.message}
        </GalleryText>
        {onRetryLoad ? (
          <GalleryButton
            label="Retry loading companions"
            onPress={onRetryLoad}
            secondary
            testID={`${testID}-retry`}
            theme={theme}
          />
        ) : null}
      </View>
    );
  }

  const { snapshot } = state;
  const busy = pending !== null || locallySubmitting;
  const balance = confirmedBalance(snapshot);
  const preview = getPreviewPet(snapshot);
  const availableAnimation = preview.status === "preview-only"
    ? "basic"
    : getAvailableAnimationVariant(snapshot, selectedAnimationVariant, proAvailability);
  const reviewPrompt = getPetReviewPrompt(snapshot, reviewChoice);
  const activeReview = reviewPrompt !== null && reviewChoice !== null
    ? reviewChoice
    : null;
  const earnedOwned = snapshot.ownedCosmeticIds.includes(EARNED_CELEBRATION_ID);
  const scarfOwned = snapshot.ownedCosmeticIds.includes(STUDY_SCARF_ID);
  const hasPet = preview.status !== "preview-only";
  const hasEquippedPet = preview.status === "equipped";
  const equippedScarf = hasEquippedPet && scarfOwned && snapshot.scarfEquipped;

  const purchaseButton = (itemId: PurchasablePetItemId) => {
    const offer = getPurchaseOffer(snapshot, itemId);
    const name = ITEM_NAMES[itemId];
    if (offer.status === "owned") return null;
    const label = offerLabel(offer, name);
    return (
      <GalleryButton
        disabled={busy || !canReview(offer)}
        label={label}
        onPress={() => {
          if (busy) return;
          if (offer.status === "free-starter" && isPetId(itemId)) {
            setReviewChoice({ kind: "starter", petId: itemId });
          } else if (offer.status === "available") {
            setReviewChoice({ kind: "purchase", itemId, quotedPrice: offer.price });
          }
        }}
        testID={`${testID}-offer-${itemId}`}
        theme={theme}
      />
    );
  };

  return (
    <View style={containerStyle} testID={testID}>
      <GalleryText role="header" theme={theme}>Companions</GalleryText>
      <GalleryText theme={theme} testID={`${testID}-balance`}>
        {balance === null ? "Confirmed coin balance unavailable" : `Confirmed balance: ${balance} coins`}
      </GalleryText>
      {pending !== null || locallySubmitting ? (
        <GalleryText theme={theme} testID={`${testID}-pending`}>
          Request pending. Your balance and owned items will update only after confirmation.
        </GalleryText>
      ) : null}
      {operationError !== null ? (
        <GalleryText role="alert" theme={theme} testID={`${testID}-operation-error`}>
          {operationError}
        </GalleryText>
      ) : null}

      <PetCompanion
        animationVariant={availableAnimation}
        animationsEnabled={animationsEnabled}
        equippedScarf={equippedScarf}
        petId={preview.petId}
        testID={`${testID}-preview`}
        theme={theme}
      />
      <GalleryText muted theme={theme} testID={`${testID}-preview-status`}>
        {preview.status === "equipped"
          ? `${getPetCopy(preview.petId).name} is equipped.`
          : preview.status === "owned"
            ? `${getPetCopy(preview.petId).name} is owned; equip it to make it your companion.`
            : "Owl preview only. Choose a starter below to own a pet."}
      </GalleryText>
      {equippedScarf ? (
        <GalleryText muted theme={theme} testID={`${testID}-scarf-status`}>
          Study scarf is equipped.
        </GalleryText>
      ) : null}

      <GalleryText role="header" theme={theme}>Choose a pet</GalleryText>
      {PET_IDS.map((petId) => {
        const name = getPetCopy(petId).name;
        const offer = getPurchaseOffer(snapshot, petId);
        const equipped = snapshot.equippedPetId === petId && offer.status === "owned";
        const detail =
          offer.status === "owned"
            ? equipped ? "Owned and equipped" : "Owned permanently"
            : offer.status === "free-starter"
              ? "Your one free starter choice"
              : offer.status === "unavailable"
                ? "Purchase unavailable"
                : `${offer.price} coins · permanent ownership`;
        return (
          <GalleryItem
            detail={`${getPetCopy(petId).personality} · ${detail}`}
            key={petId}
            testID={`${testID}-item-${petId}`}
            theme={theme}
            title={name}
          >
            {offer.status === "owned" ? (
              <GalleryButton
                disabled={equipped || busy}
                label={equipped ? `${name} equipped` : `Equip ${name}`}
                onPress={() => submit(() => onRequestEquipPet(petId))}
                secondary
                testID={`${testID}-equip-${petId}`}
                theme={theme}
              />
            ) : purchaseButton(petId)}
          </GalleryItem>
        );
      })}

      <GalleryText role="header" theme={theme}>Cosmetics and motion</GalleryText>
      <GalleryItem
        detail={scarfOwned
          ? "Owned permanently · fits every pet"
          : `One scarf for every pet · ${catalogPriceLabel(snapshot, STUDY_SCARF_ID)}`}
        testID={`${testID}-item-${STUDY_SCARF_ID}`}
        theme={theme}
        title="Study scarf"
      >
        {scarfOwned ? (
          <GalleryButton
            disabled={!hasEquippedPet || busy}
            label={equippedScarf ? "Remove study scarf" : "Wear study scarf"}
            onPress={() => submit(() => onRequestScarfEquipped(!snapshot.scarfEquipped))}
            secondary
            testID={`${testID}-equip-scarf`}
            theme={theme}
          />
        ) : purchaseButton(STUDY_SCARF_ID)}
      </GalleryItem>
      <GalleryItem
        detail={earnedOwned
          ? "Owned permanently · works with every owned pet"
          : `A richer result reaction for owned pets · ${catalogPriceLabel(snapshot, EARNED_CELEBRATION_ID)}`}
        testID={`${testID}-item-${EARNED_CELEBRATION_ID}`}
        theme={theme}
        title="Earned celebration"
      >
        {earnedOwned ? (
          <GalleryButton
            disabled={!hasPet || busy || selectedAnimationVariant === EARNED_CELEBRATION_ID}
            label={selectedAnimationVariant === EARNED_CELEBRATION_ID
              ? "Earned celebration selected"
              : "Use earned celebration"}
            onPress={() => submit(() => onRequestAnimationVariant(EARNED_CELEBRATION_ID))}
            secondary
            testID={`${testID}-select-earned`}
            theme={theme}
          />
        ) : purchaseButton(EARNED_CELEBRATION_ID)}
      </GalleryItem>
      <GalleryItem
        detail={proAvailability === "active"
          ? "Pro-only presentation while Pro is confirmed active"
          : proAvailability === "unknown"
            ? "Pro status unavailable. Earned items remain owned."
            : "Pro required. Earned items remain owned."}
        testID={`${testID}-item-${PRO_FLOURISH_ID}`}
        theme={theme}
        title="Pro flourish"
      >
        <GalleryButton
          disabled={!hasPet || busy || proAvailability !== "active" || selectedAnimationVariant === PRO_FLOURISH_ID}
          label={proAvailability !== "active"
            ? "Pro flourish unavailable"
            : selectedAnimationVariant === PRO_FLOURISH_ID
              ? "Pro flourish selected"
              : "Use Pro flourish"}
          onPress={() => {
            if (!busy && proAvailability === "active") {
              onRequestAnimationVariant(PRO_FLOURISH_ID);
            }
          }}
          secondary
          testID={`${testID}-select-pro`}
          theme={theme}
        />
      </GalleryItem>
      {selectedAnimationVariant === PRO_FLOURISH_ID && proAvailability !== "active" ? (
        <GalleryText muted theme={theme} testID={`${testID}-pro-paused`}>
          Pro flourish is paused. Your earned or basic reaction is shown instead.
        </GalleryText>
      ) : null}
      <GalleryButton
        disabled={!hasPet || busy || selectedAnimationVariant === "basic"}
        label={selectedAnimationVariant === "basic" ? "Basic reaction selected" : "Use basic reaction"}
        onPress={() => submit(() => onRequestAnimationVariant("basic"))}
        secondary
        testID={`${testID}-select-basic`}
        theme={theme}
      />
      <GalleryButton
        disabled={busy}
        label={animationsEnabled ? "Turn pet animations off" : "Turn pet animations on"}
        onPress={() => onRequestAnimationsEnabled(!animationsEnabled)}
        secondary
        testID={`${testID}-motion-toggle`}
        theme={theme}
      />
      <GalleryText muted theme={theme}>
        Your device's reduced-motion setting always keeps the pet still. Its words stay visible.
      </GalleryText>

      {activeReview !== null ? (
        <View
          style={[
            styles.review,
            {
              backgroundColor: theme.colors.surfaceElevated,
              borderColor: theme.colors.border,
              borderRadius: theme.radii.md,
              padding: theme.spacing.md,
              gap: theme.spacing.sm,
            },
          ]}
          testID={`${testID}-review`}
        >
          <GalleryText role="header" theme={theme}>Confirm your choice</GalleryText>
          <GalleryText theme={theme} testID={`${testID}-review-copy`}>
            {reviewPrompt}
          </GalleryText>
          <GalleryButton
            disabled={busy}
            label={activeReview.kind === "starter"
              ? `Confirm ${ITEM_NAMES[activeReview.petId]} as free starter`
              : `Confirm purchase of ${ITEM_NAMES[activeReview.itemId]}`}
            onPress={() => submit(() => {
              if (activeReview.kind === "starter") {
                onRequestStarterClaim(activeReview.petId);
              } else {
                onRequestPurchase(activeReview.itemId);
              }
            })}
            testID={`${testID}-confirm`}
            theme={theme}
          />
          <GalleryButton
            disabled={busy}
            label="Cancel choice"
            onPress={() => setReviewChoice(null)}
            secondary
            testID={`${testID}-cancel`}
            theme={theme}
          />
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { width: "100%" },
  item: { borderWidth: 1 },
  button: {
    minHeight: 44,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  review: { borderWidth: 1 },
});
