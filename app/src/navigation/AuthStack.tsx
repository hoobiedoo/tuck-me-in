import React from "react";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import ConfirmScreen from "../screens/ConfirmScreen";
import ForgotPasswordScreen from "../screens/ForgotPasswordScreen";
import SignInScreen from "../screens/SignInScreen";
import SignUpScreen from "../screens/SignUpScreen";

export type AuthStackParamList = {
  SignIn: undefined;
  SignUp: undefined;
  Confirm: { email: string };
  ForgotPassword: undefined;
};

const Stack = createNativeStackNavigator<AuthStackParamList>();

export default function AuthStack() {
  return (
    <Stack.Navigator screenOptions={{ headerShown: false }}>
      <Stack.Screen name="SignIn" component={SignInScreen} />
      <Stack.Screen name="SignUp" component={SignUpScreen} />
      <Stack.Screen name="Confirm" component={ConfirmScreen} />
      <Stack.Screen name="ForgotPassword" component={ForgotPasswordScreen} />
    </Stack.Navigator>
  );
}