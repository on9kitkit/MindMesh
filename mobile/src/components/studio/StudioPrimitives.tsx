import {
  PropsWithChildren,
  type ReactNode,
} from "react";
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleProp,
  StyleSheet,
  Text,
  TextInput,
  TextInputProps,
  TextStyle,
  View,
  ViewStyle,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useStudioTheme } from "../../appearance/StudioThemeContext";
import {
  studioButtonPresentation,
  studioChoicePresentation,
  type StudioButtonVariant,
} from "../../appearance/studioPresentation";
import type {
  ThemeTokens,
  ThemeTypeStyle,
} from "../../theme";

type StudioScreenProps = PropsWithChildren<{
  contentStyle?: StyleProp<ViewStyle>;
  scroll?: boolean;
}>;

export function StudioScreen({
  children,
  contentStyle,
  scroll = true,
}: StudioScreenProps) {
  const theme = useStudioTheme();
  const screenPadding = {
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.xl,
  };
  const content = scroll ? (
    <ScrollView
      contentContainerStyle={[styles.scrollContent, screenPadding, contentStyle]}
      keyboardShouldPersistTaps="handled"
      showsVerticalScrollIndicator={false}
    >
      <View style={styles.readableContent}>{children}</View>
    </ScrollView>
  ) : (
    <View style={[styles.content, screenPadding, contentStyle]}>
      <View style={styles.readableContent}>{children}</View>
    </View>
  );

  return (
    <SafeAreaView
      edges={["top", "bottom"]}
      style={[styles.safeArea, { backgroundColor: theme.colors.background }]}
    >
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={styles.flex}
      >
        {content}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

type StudioTextProps = PropsWithChildren<{
  color?: string;
  tone?: "primary" | "muted" | "error" | "success";
  accessibilityRole?: "header" | "alert" | "text";
  accessibilityLiveRegion?: "none" | "polite" | "assertive";
  style?: StyleProp<TextStyle>;
  variant?: keyof ThemeTokens["typography"];
}>;

function textStyle(
  theme: ThemeTokens,
  variant: keyof ThemeTokens["typography"],
): ThemeTypeStyle {
  return theme.typography[variant];
}

export function StudioText({
  accessibilityLiveRegion,
  accessibilityRole,
  children,
  color,
  tone,
  style,
  variant = "body",
}: StudioTextProps) {
  const theme = useStudioTheme();
  const toneColors: Record<NonNullable<StudioTextProps["tone"]>, string> = {
    primary: theme.colors.primary,
    muted: theme.colors.mutedText,
    error: theme.colors.error,
    success: theme.colors.success,
  };
  return (
    <Text
      accessibilityLiveRegion={accessibilityLiveRegion}
      accessibilityRole={accessibilityRole}
      style={[
        textStyle(theme, variant),
        { color: color ?? (tone ? toneColors[tone] : theme.colors.text) },
        style,
      ]}
    >
      {children}
    </Text>
  );
}

type StudioCardProps = PropsWithChildren<{
  style?: StyleProp<ViewStyle>;
}>;

export function StudioCard({ children, style }: StudioCardProps) {
  const theme = useStudioTheme();
  return (
    <View
      style={[
        styles.card,
        {
          backgroundColor: theme.colors.surface,
          borderColor: theme.colors.border,
          borderRadius: theme.radii.lg,
          padding: theme.spacing.lg,
        },
        style,
      ]}
    >
      {children}
    </View>
  );
}

export type StudioButtonProps = {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  variant?: StudioButtonVariant;
  testID?: string;
};

export type { StudioButtonPresentation, StudioButtonVariant } from "../../appearance/studioPresentation";

export function StudioButton({
  disabled = false,
  label,
  onPress,
  testID,
  variant = "primary",
}: StudioButtonProps) {
  const theme = useStudioTheme();
  const presentation = studioButtonPresentation(theme, variant, disabled);
  return (
    <Pressable
      accessibilityLabel={label}
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      testID={testID}
      style={({ pressed }) => [
        presentation.button,
        pressed && !disabled && { opacity: 0.82 },
      ]}
    >
      <Text style={presentation.label}>{label}</Text>
    </Pressable>
  );
}

export type StudioTextFieldProps = {
  accessibilityLabel?: string;
  label: string;
  value: string;
  onChangeText: (value: string) => void;
  placeholder?: string;
  secureTextEntry?: boolean;
  keyboardType?: TextInputProps["keyboardType"];
  autoCapitalize?: TextInputProps["autoCapitalize"];
  autoComplete?: TextInputProps["autoComplete"];
  autoCorrect?: boolean;
  editable?: boolean;
  maxLength?: number;
  multiline?: boolean;
  numberOfLines?: number;
  onBlur?: TextInputProps["onBlur"];
  error?: string;
  accessibilityHint?: string;
  containerStyle?: StyleProp<ViewStyle>;
  inputStyle?: StyleProp<TextStyle>;
  textAlignVertical?: TextInputProps["textAlignVertical"];
};

export function StudioTextField({
  accessibilityLabel,
  accessibilityHint,
  autoCapitalize,
  autoComplete,
  autoCorrect,
  containerStyle,
  editable = true,
  error,
  inputStyle,
  keyboardType,
  label,
  maxLength,
  multiline = false,
  numberOfLines,
  onBlur,
  onChangeText,
  placeholder,
  secureTextEntry,
  textAlignVertical,
  value,
}: StudioTextFieldProps) {
  const theme = useStudioTheme();
  const hasError = error !== undefined;
  return (
    <View style={containerStyle}>
      <StudioText color={theme.colors.mutedText} variant="label">
        {label}
      </StudioText>
      <TextInput
        accessibilityHint={accessibilityHint}
        accessibilityLabel={accessibilityLabel ?? label}
        accessibilityState={{ disabled: !editable }}
        autoCapitalize={autoCapitalize}
        autoComplete={autoComplete}
        autoCorrect={autoCorrect}
        cursorColor={theme.colors.primary}
        editable={editable}
        keyboardAppearance={theme.scheme === "dark" ? "dark" : "light"}
        keyboardType={keyboardType}
        maxLength={maxLength}
        multiline={multiline}
        numberOfLines={numberOfLines}
        onBlur={onBlur}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={theme.colors.mutedText}
        selectionColor={theme.colors.primary}
        secureTextEntry={secureTextEntry}
        textAlignVertical={textAlignVertical}
        style={[
          styles.input,
          {
            backgroundColor: theme.colors.input,
            borderColor: hasError ? theme.colors.error : theme.colors.border,
            borderRadius: theme.radii.md,
            color: theme.colors.text,
            paddingHorizontal: theme.spacing.md,
            paddingVertical: theme.spacing.sm,
          },
          inputStyle,
        ]}
        value={value}
      />
      {hasError ? (
        <StudioText
          accessibilityRole="alert"
          color={theme.colors.error}
          style={{ marginTop: theme.spacing.xs }}
          variant="caption"
        >
          {error}
        </StudioText>
      ) : null}
    </View>
  );
}

export type StudioChoiceRowProps = {
  title: string;
  description?: string;
  selected: boolean;
  disabled?: boolean;
  onPress: () => void;
  accessibilityLabel?: string;
  testID?: string;
};

export type { StudioChoicePresentation } from "../../appearance/studioPresentation";

export function StudioChoiceRow({
  accessibilityLabel,
  description,
  disabled = false,
  onPress,
  selected,
  testID,
  title,
}: StudioChoiceRowProps) {
  const theme = useStudioTheme();
  const presentation = studioChoicePresentation(theme, selected, disabled);
  const trimmedDescription = description?.trim();
  return (
    <Pressable
      accessibilityLabel={
        accessibilityLabel ??
        (trimmedDescription ? `${title}, ${trimmedDescription}` : title)
      }
      accessibilityRole="radio"
      accessibilityState={{ checked: selected, disabled }}
      disabled={disabled}
      onPress={onPress}
      testID={testID}
      style={({ pressed }) => [
        presentation.row,
        pressed && !disabled && { borderColor: theme.colors.primaryPressed },
      ]}
    >
      <View style={presentation.indicator}>
        {selected ? <View style={presentation.indicatorMark} /> : null}
      </View>
      <View style={styles.choiceText}>
        <Text style={presentation.title}>{title}</Text>
        {description ? (
          <Text style={presentation.description}>{description}</Text>
        ) : null}
      </View>
    </Pressable>
  );
}

export function StudioStack({ children }: { children: ReactNode }) {
  const theme = useStudioTheme();
  return <View style={{ gap: theme.spacing.sm }}>{children}</View>;
}

const styles = StyleSheet.create({
  safeArea: { flex: 1 },
  flex: { flex: 1 },
  scrollContent: {
    flexGrow: 1,
  },
  content: {
    flex: 1,
  },
  readableContent: {
    alignSelf: "center",
    maxWidth: 720,
    width: "100%",
  },
  card: {
    borderWidth: 1,
  },
  input: {
    borderWidth: 1,
    fontSize: 16,
    minHeight: 52,
  },
  choiceText: {
    flex: 1,
  },
});
