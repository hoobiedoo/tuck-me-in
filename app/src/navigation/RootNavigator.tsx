import React from "react";
import { ActivityIndicator, StyleSheet, View } from "react-native";
import { NavigationContainer } from "@react-navigation/native";
import { useAuth } from "../contexts/AuthContext";
import HouseholdSetupScreen from "../screens/HouseholdSetupScreen";
import AuthStack from "./AuthStack";
import MainStack from "./MainStack";

export default function RootNavigator() {
  const { isLoading, isAuthenticated, needsHousehold } = useAuth();

  if (isLoading) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator size="large" color="#5B9FB8" />
      </View>
    );
  }

  return (
    <NavigationContainer>
      {!isAuthenticated ? (
        <AuthStack />
      ) : needsHousehold ? (
        <HouseholdSetupScreen />
      ) : (
        <MainStack />
      )}
    </NavigationContainer>
  );
}

const styles = StyleSheet.create({
  loading: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#FBF8F3",
  },
});