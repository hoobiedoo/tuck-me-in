import { Alert, Platform } from "react-native";

/**
 * react-native-web's Alert.alert is a no-op stub (see
 * react-native-web/src/exports/Alert/index.js) — it never shows anything
 * and never fires button callbacks. Route through this instead of Alert
 * directly anywhere the result needs to actually be seen (or a callback
 * actually needs to fire) on web, not just native.
 */
export function notify(title: string, message?: string, onDismiss?: () => void) {
  if (Platform.OS === "web") {
    window.alert(message ? `${title}\n\n${message}` : title);
    onDismiss?.();
  } else {
    Alert.alert(title, message, onDismiss ? [{ text: "OK", onPress: onDismiss }] : undefined);
  }
}
