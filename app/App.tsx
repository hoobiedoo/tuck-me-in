import "./global";
import React, { useState } from "react";
import { ActivityIndicator, View, StyleSheet } from "react-native";
import { StatusBar } from "expo-status-bar";
import { registerRootComponent } from "expo";
import { AuthProvider, useAuth } from "./src/contexts/AuthContext";
import SignInScreen from "./src/screens/SignInScreen";
import SignUpScreen from "./src/screens/SignUpScreen";
import ConfirmScreen from "./src/screens/ConfirmScreen";
import HomeScreen from "./src/screens/HomeScreen";
import StoryLibraryScreen from "./src/screens/StoryLibraryScreen";
import RecordStoryScreen from "./src/screens/RecordStoryScreen";
import StoryRequestsScreen from "./src/screens/StoryRequestsScreen";
import HouseholdScreen from "./src/screens/HouseholdScreen";

type AuthScreen = "signIn" | "signUp" | "confirm";
type AppScreen = "home" | "library" | "record" | "requests" | "household";

interface RecordContext {
  initialTitle?: string;
  requestId?: string;
}

function AppNavigator() {
  const { isLoading, isAuthenticated } = useAuth();
  const [screen, setScreen] = useState<AuthScreen>("signIn");
  const [appScreen, setAppScreen] = useState<AppScreen>("home");
  const [confirmEmail, setConfirmEmail] = useState("");
  const [recordContext, setRecordContext] = useState<RecordContext>({});

  if (isLoading) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator size="large" color="#7c3aed" />
      </View>
    );
  }

  if (isAuthenticated) {
    switch (appScreen) {
      case "library":
        return <StoryLibraryScreen onBack={() => setAppScreen("home")} />;
      case "record":
        return (
          <RecordStoryScreen
            onBack={() => { setAppScreen("home"); setRecordContext({}); }}
            initialTitle={recordContext.initialTitle}
            requestId={recordContext.requestId}
          />
        );
      case "requests":
        return (
          <StoryRequestsScreen
            onBack={() => setAppScreen("home")}
            onRecord={(title, requestId) => {
              setRecordContext({ initialTitle: title, requestId });
              setAppScreen("record");
            }}
          />
        );
      case "household":
        return <HouseholdScreen onBack={() => setAppScreen("home")} />;
      default:
        return <HomeScreen onNavigate={(s) => setAppScreen(s as AppScreen)} />;
    }
  }

  switch (screen) {
    case "signUp":
      return (
        <SignUpScreen
          onNavigateSignIn={() => setScreen("signIn")}
          onSignUpSuccess={(email) => {
            setConfirmEmail(email);
            setScreen("confirm");
          }}
        />
      );
    case "confirm":
      return (
        <ConfirmScreen
          email={confirmEmail}
          onConfirmSuccess={() => setScreen("signIn")}
        />
      );
    default:
      return (
        <SignInScreen onNavigateSignUp={() => setScreen("signUp")} />
      );
  }
}

function App() {
  return (
    <AuthProvider>
      <StatusBar style="dark" />
      <AppNavigator />
    </AuthProvider>
  );
}

registerRootComponent(App);

const styles = StyleSheet.create({
  loading: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "#f8f4ff",
  },
});
