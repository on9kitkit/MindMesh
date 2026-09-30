import { useCallback, useEffect, useRef, useState } from "react";
import {
  AccessibilityInfo,
  Animated,
  Pressable,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import type { ThemeTokens } from "../../theme";
import {
  effectivePetMotion,
  getPetCopy,
  getPetPaint,
  getPetReaction,
  type EffectivePetMotion,
  type PetAnimationVariant,
  type PetId,
  type PetOccasion,
  type PetPaint,
} from "./petPresentation";

/**
 * Original MindMesh artwork, drawn entirely with React Native shapes.
 * No subject avatars, image files, downloaded assets, or animation packages are used.
 * The parent supplies a confirmed, permitted animation tier; this component has
 * no knowledge of coins, purchases, ownership, or RevenueCat entitlement.
 */
export type PetCompanionProps = {
  petId: PetId;
  theme: ThemeTokens;
  occasion?: PetOccasion;
  animationVariant?: PetAnimationVariant;
  /** Supply true only from confirmed ownership and equipped cosmetic state. */
  equippedScarf?: boolean;
  animationsEnabled?: boolean;
  testID?: string;
};

type ShapeProps = {
  style: StyleProp<ViewStyle>;
  testID?: string;
};

function Shape({ style, testID }: ShapeProps) {
  return <View accessible={false} style={style} testID={testID} />;
}

function OwlArt({ paint, testID }: { paint: PetPaint; testID: string }) {
  const rim = { borderColor: paint.outline, borderWidth: 1.5 };
  return (
    <>
      <Shape style={[styles.owlLeftTuft, rim, { backgroundColor: paint.detail }]} />
      <Shape style={[styles.owlRightTuft, rim, { backgroundColor: paint.detail }]} />
      <Shape style={[styles.owlLeftWing, rim, { backgroundColor: paint.detail }]} />
      <Shape style={[styles.owlRightWing, rim, { backgroundColor: paint.detail }]} />
      <Shape
        style={[styles.owlBody, rim, { backgroundColor: paint.body }]}
        testID={`${testID}-owl-body`}
      />
      <Shape style={[styles.owlLeftFace, { backgroundColor: paint.face }]} />
      <Shape style={[styles.owlRightFace, { backgroundColor: paint.face }]} />
      <Shape style={[styles.owlLeftEye, { backgroundColor: paint.eye }]} />
      <Shape style={[styles.owlRightEye, { backgroundColor: paint.eye }]} />
      <Shape style={[styles.owlBeak, { backgroundColor: paint.detail }]} />
      <Shape style={[styles.owlLeftFoot, { backgroundColor: paint.detail }]} />
      <Shape style={[styles.owlRightFoot, { backgroundColor: paint.detail }]} />
    </>
  );
}

function TortoiseArt({ paint, testID }: { paint: PetPaint; testID: string }) {
  const rim = { borderColor: paint.outline, borderWidth: 1.5 };
  return (
    <>
      <Shape style={[styles.tortoiseTail, rim, { backgroundColor: paint.body }]} />
      <Shape style={[styles.tortoiseBackFoot, rim, { backgroundColor: paint.body }]} />
      <Shape style={[styles.tortoiseFrontFoot, rim, { backgroundColor: paint.body }]} />
      <Shape style={[styles.tortoiseBody, rim, { backgroundColor: paint.body }]} />
      <Shape style={[styles.tortoiseHead, rim, { backgroundColor: paint.face }]} />
      <Shape
        style={[styles.tortoiseShell, rim, { backgroundColor: paint.detail }]}
        testID={`${testID}-tortoise-shell`}
      />
      <Shape style={[styles.tortoiseShellCenter, { backgroundColor: paint.body }]} />
      <Shape style={[styles.tortoiseEye, { backgroundColor: paint.eye }]} />
    </>
  );
}

function FoxArt({ paint, testID }: { paint: PetPaint; testID: string }) {
  const rim = { borderColor: paint.outline, borderWidth: 1.5 };
  return (
    <>
      <Shape style={[styles.foxTail, rim, { backgroundColor: paint.body }]} />
      <Shape style={[styles.foxTailTip, { backgroundColor: paint.face }]} />
      <Shape style={[styles.foxBody, rim, { backgroundColor: paint.body }]} />
      <Shape style={[styles.foxLeftFoot, { backgroundColor: paint.detail }]} />
      <Shape style={[styles.foxRightFoot, { backgroundColor: paint.detail }]} />
      <Shape style={[styles.foxLeftEar, rim, { backgroundColor: paint.detail }]} />
      <Shape style={[styles.foxRightEar, rim, { backgroundColor: paint.detail }]} />
      <Shape
        style={[styles.foxHead, rim, { backgroundColor: paint.body }]}
        testID={`${testID}-fox-head`}
      />
      <Shape style={[styles.foxMuzzle, { backgroundColor: paint.face }]} />
      <Shape style={[styles.foxLeftEye, { backgroundColor: paint.eye }]} />
      <Shape style={[styles.foxRightEye, { backgroundColor: paint.eye }]} />
      <Shape style={[styles.foxNose, { backgroundColor: paint.eye }]} />
    </>
  );
}

function ScarfArt({
  petId,
  theme,
  testID,
}: {
  petId: PetId;
  theme: ThemeTokens;
  testID: string;
}) {
  const band = petId === "pet.owl"
    ? styles.owlScarfBand
    : petId === "pet.tortoise"
      ? styles.tortoiseScarfBand
      : styles.foxScarfBand;
  const tail = petId === "pet.owl"
    ? styles.owlScarfTail
    : petId === "pet.tortoise"
      ? styles.tortoiseScarfTail
      : styles.foxScarfTail;
  const knot = petId === "pet.owl"
    ? styles.owlScarfKnot
    : petId === "pet.tortoise"
      ? styles.tortoiseScarfKnot
      : styles.foxScarfKnot;
  const fabric = {
    backgroundColor: theme.colors.primary,
    borderColor: theme.colors.onPrimary,
    borderWidth: 1,
  };
  return (
    <>
      <Shape style={[tail, fabric]} testID={`${testID}-scarf-tail`} />
      <Shape style={[band, fabric]} testID={`${testID}-scarf-band`} />
      <Shape
        style={[knot, { backgroundColor: theme.colors.onPrimary, borderColor: theme.colors.primary, borderWidth: 1 }]}
        testID={`${testID}-scarf-knot`}
      />
    </>
  );
}

function PetArt({
  petId,
  paint,
  theme,
  equippedScarf,
  testID,
}: {
  petId: PetId;
  paint: PetPaint;
  theme: ThemeTokens;
  equippedScarf: boolean;
  testID: string;
}) {
  return (
    <>
      {petId === "pet.owl"
        ? <OwlArt paint={paint} testID={testID} />
        : petId === "pet.tortoise"
          ? <TortoiseArt paint={paint} testID={testID} />
          : <FoxArt paint={paint} testID={testID} />}
      {equippedScarf ? <ScarfArt petId={petId} testID={testID} theme={theme} /> : null}
    </>
  );
}

const MOTION_STEPS: Readonly<
  Record<PetAnimationVariant, ReadonlyArray<{ value: number; duration: number }>>
> = {
  basic: [
    { value: 1, duration: 170 },
    { value: 0, duration: 230 },
  ],
  "animation.earned_celebration": [
    { value: 1, duration: 170 },
    { value: 0, duration: 170 },
    { value: 0.7, duration: 150 },
    { value: 0, duration: 190 },
  ],
  "animation.pro_flourish": [
    { value: 1, duration: 170 },
    { value: -0.7, duration: 190 },
    { value: 0.8, duration: 180 },
    { value: 0, duration: 220 },
  ],
};

export function PetCompanion({
  petId,
  theme,
  occasion = "home",
  animationVariant = "basic",
  equippedScarf = false,
  animationsEnabled = true,
  testID = "pet-companion",
}: PetCompanionProps) {
  // Start still: an OS preference query must complete before any motion is allowed.
  const [reduceMotion, setReduceMotion] = useState(true);
  const [interacted, setInteracted] = useState(false);
  const poseRef = useRef<Animated.Value | null>(null);
  if (poseRef.current === null) poseRef.current = new Animated.Value(0);
  const pose = poseRef.current;
  const runningAnimation = useRef<Animated.CompositeAnimation | null>(null);
  const motion: EffectivePetMotion = effectivePetMotion(
    animationVariant,
    animationsEnabled,
    reduceMotion,
  );
  const copy = getPetCopy(petId);
  const paint = getPetPaint(petId, theme);
  const reaction = getPetReaction(petId, occasion, interacted, animationVariant);

  useEffect(() => {
    let mounted = true;
    let changedByEvent = false;
    const subscription = AccessibilityInfo.addEventListener(
      "reduceMotionChanged",
      (enabled) => {
        if (mounted) {
          changedByEvent = true;
          setReduceMotion(enabled);
        }
      },
    );
    void AccessibilityInfo.isReduceMotionEnabled()
      .then((enabled) => {
        if (mounted && !changedByEvent) setReduceMotion(enabled);
      })
      .catch(() => {
        if (mounted && !changedByEvent) setReduceMotion(true);
      });
    return () => {
      mounted = false;
      subscription.remove();
    };
  }, []);

  useEffect(() => setInteracted(false), [petId, occasion]);

  const playMotion = useCallback(() => {
    if (motion === "still") return;
    runningAnimation.current?.stop();
    pose.setValue(0);
    const animation = Animated.sequence(
      MOTION_STEPS[motion].map(({ value, duration }) =>
        Animated.timing(pose, {
          toValue: value,
          duration,
          useNativeDriver: true,
        }),
      ),
    );
    runningAnimation.current = animation;
    animation.start(({ finished }) => {
      if (runningAnimation.current === animation) {
        runningAnimation.current = null;
        if (finished) pose.setValue(0);
      }
    });
  }, [motion, pose]);

  useEffect(() => {
    if (motion === "still") {
      runningAnimation.current?.stop();
      runningAnimation.current = null;
      pose.setValue(0);
    } else if (occasion === "result") {
      playMotion();
    }
    return () => {
      runningAnimation.current?.stop();
      runningAnimation.current = null;
      pose.setValue(0);
    };
  }, [motion, occasion, petId, playMotion, pose]);

  const handlePress = () => {
    setInteracted(true);
    playMotion();
  };

  const turn = pose.interpolate({
    inputRange: [-1, 0, 1],
    outputRange: ["-8deg", "0deg", "8deg"],
  });
  const step = pose.interpolate({ inputRange: [-1, 0, 1], outputRange: [-5, 0, 5] });
  const hop = pose.interpolate({ inputRange: [-1, 0, 1], outputRange: [0, 0, -8] });

  return (
    <View
      style={[
        styles.card,
        {
          backgroundColor: theme.colors.surface,
          borderColor: theme.colors.border,
          borderRadius: theme.radii.lg,
          padding: theme.spacing.md,
        },
      ]}
      testID={testID}
    >
      <Pressable
        accessibilityHint={`Show ${copy.name}'s reaction`}
        accessibilityLabel={`Interact with ${copy.name}`}
        accessibilityRole="button"
        onPress={handlePress}
        style={styles.tapTarget}
        testID={`${testID}-tap`}
      >
        <Animated.View
          accessible={false}
          importantForAccessibility="no-hide-descendants"
          style={[
            styles.artFrame,
            {
              backgroundColor: paint.frame,
              borderColor: paint.frameBorder,
              borderRadius: theme.radii.lg,
            },
          ]}
          testID={`${testID}-art`}
        >
          <Animated.View
            style={[
              styles.artParts,
              petId === "pet.owl"
                ? { transform: [{ rotate: turn }] }
                : petId === "pet.tortoise"
                  ? { transform: [{ translateX: step }] }
                  : { transform: [{ translateY: hop }] },
            ]}
          >
            <PetArt
              equippedScarf={equippedScarf}
              paint={paint}
              petId={petId}
              testID={testID}
              theme={theme}
            />
          </Animated.View>
        </Animated.View>
      </Pressable>
      <Text
        accessibilityRole="header"
        style={[theme.typography.heading, { color: theme.colors.text, marginTop: theme.spacing.sm }]}
        testID={`${testID}-name`}
      >
        {copy.name} · {copy.personality}
      </Text>
      <Text
        accessibilityLiveRegion="polite"
        style={[theme.typography.body, { color: theme.colors.text, marginTop: theme.spacing.xs }]}
        testID={`${testID}-message`}
      >
        {reaction.message}
      </Text>
      {equippedScarf ? (
        <Text
          style={[theme.typography.caption, { color: theme.colors.mutedText, marginTop: theme.spacing.xs }]}
          testID={`${testID}-scarf-label`}
        >
          Wearing study scarf
        </Text>
      ) : null}
      {occasion === "result" || interacted ? (
        <Text
          style={[
            theme.typography.caption,
            { color: theme.colors.mutedText, marginTop: theme.spacing.xs },
          ]}
          testID={`${testID}-action`}
        >
          {reaction.action}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, alignItems: "center" },
  tapTarget: { minWidth: 120, minHeight: 120, alignItems: "center", justifyContent: "center" },
  artFrame: { width: 120, height: 120, borderWidth: 1, overflow: "hidden", alignItems: "center", justifyContent: "center" },
  artParts: { width: 112, height: 112 },
  owlLeftTuft: { position: "absolute", left: 27, top: 10, width: 24, height: 34, borderRadius: 8, transform: [{ rotate: "-27deg" }] },
  owlRightTuft: { position: "absolute", left: 61, top: 10, width: 24, height: 34, borderRadius: 8, transform: [{ rotate: "27deg" }] },
  owlLeftWing: { position: "absolute", left: 14, top: 50, width: 24, height: 41, borderRadius: 14, transform: [{ rotate: "14deg" }] },
  owlRightWing: { position: "absolute", left: 74, top: 50, width: 24, height: 41, borderRadius: 14, transform: [{ rotate: "-14deg" }] },
  owlBody: { position: "absolute", left: 23, top: 24, width: 66, height: 73, borderRadius: 33 },
  owlLeftFace: { position: "absolute", left: 30, top: 40, width: 27, height: 29, borderRadius: 15 },
  owlRightFace: { position: "absolute", left: 55, top: 40, width: 27, height: 29, borderRadius: 15 },
  owlLeftEye: { position: "absolute", left: 41, top: 49, width: 7, height: 7, borderRadius: 4 },
  owlRightEye: { position: "absolute", left: 65, top: 49, width: 7, height: 7, borderRadius: 4 },
  owlBeak: { position: "absolute", left: 52, top: 63, width: 9, height: 9, borderRadius: 2, transform: [{ rotate: "45deg" }] },
  owlLeftFoot: { position: "absolute", left: 38, top: 94, width: 13, height: 5, borderRadius: 3 },
  owlRightFoot: { position: "absolute", left: 62, top: 94, width: 13, height: 5, borderRadius: 3 },
  tortoiseTail: { position: "absolute", left: 7, top: 66, width: 20, height: 15, borderRadius: 6, transform: [{ rotate: "-30deg" }] },
  tortoiseBackFoot: { position: "absolute", left: 23, top: 83, width: 19, height: 16, borderRadius: 9 },
  tortoiseFrontFoot: { position: "absolute", left: 70, top: 83, width: 19, height: 16, borderRadius: 9 },
  tortoiseBody: { position: "absolute", left: 18, top: 60, width: 72, height: 34, borderRadius: 17 },
  tortoiseHead: { position: "absolute", left: 79, top: 52, width: 28, height: 28, borderRadius: 14 },
  tortoiseShell: { position: "absolute", left: 24, top: 33, width: 63, height: 56, borderRadius: 30 },
  tortoiseShellCenter: { position: "absolute", left: 39, top: 44, width: 33, height: 33, borderRadius: 16 },
  tortoiseEye: { position: "absolute", left: 96, top: 60, width: 5, height: 5, borderRadius: 3 },
  foxTail: { position: "absolute", left: 2, top: 58, width: 45, height: 26, borderRadius: 17, transform: [{ rotate: "-27deg" }] },
  foxTailTip: { position: "absolute", left: 4, top: 49, width: 17, height: 22, borderRadius: 10, transform: [{ rotate: "-27deg" }] },
  foxBody: { position: "absolute", left: 30, top: 60, width: 59, height: 34, borderRadius: 19 },
  foxLeftFoot: { position: "absolute", left: 43, top: 90, width: 15, height: 8, borderRadius: 4 },
  foxRightFoot: { position: "absolute", left: 69, top: 90, width: 15, height: 8, borderRadius: 4 },
  foxLeftEar: { position: "absolute", left: 36, top: 13, width: 19, height: 29, borderRadius: 7, transform: [{ rotate: "-24deg" }] },
  foxRightEar: { position: "absolute", left: 65, top: 13, width: 19, height: 29, borderRadius: 7, transform: [{ rotate: "24deg" }] },
  foxHead: { position: "absolute", left: 34, top: 28, width: 52, height: 47, borderRadius: 24 },
  foxMuzzle: { position: "absolute", left: 42, top: 52, width: 36, height: 20, borderRadius: 10 },
  foxLeftEye: { position: "absolute", left: 47, top: 45, width: 6, height: 6, borderRadius: 3 },
  foxRightEye: { position: "absolute", left: 68, top: 45, width: 6, height: 6, borderRadius: 3 },
  foxNose: { position: "absolute", left: 57, top: 57, width: 6, height: 5, borderRadius: 3 },
  owlScarfBand: { position: "absolute", left: 39, top: 72, width: 35, height: 10, borderRadius: 5 },
  owlScarfTail: { position: "absolute", left: 61, top: 78, width: 9, height: 17, borderRadius: 3, transform: [{ rotate: "-12deg" }] },
  owlScarfKnot: { position: "absolute", left: 58, top: 72, width: 9, height: 10, borderRadius: 5 },
  tortoiseScarfBand: { position: "absolute", left: 78, top: 70, width: 20, height: 10, borderRadius: 5 },
  tortoiseScarfTail: { position: "absolute", left: 85, top: 77, width: 8, height: 16, borderRadius: 3, transform: [{ rotate: "-16deg" }] },
  tortoiseScarfKnot: { position: "absolute", left: 84, top: 70, width: 9, height: 10, borderRadius: 5 },
  foxScarfBand: { position: "absolute", left: 44, top: 69, width: 33, height: 10, borderRadius: 5 },
  foxScarfTail: { position: "absolute", left: 65, top: 76, width: 9, height: 17, borderRadius: 3, transform: [{ rotate: "12deg" }] },
  foxScarfKnot: { position: "absolute", left: 61, top: 69, width: 9, height: 10, borderRadius: 5 },
});
