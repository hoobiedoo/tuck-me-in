import React, { useState } from "react";
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Alert,
  Image,
} from "react-native";
import { useNavigation, useRoute } from "@react-navigation/native";
import type { NativeStackNavigationProp } from "@react-navigation/native-stack";
import type { RouteProp } from "@react-navigation/native";
import { useAuth } from "../contexts/AuthContext";
import type { AuthStackParamList } from "../navigation/AuthStack";

const logo = require("../../assets/logo.png");

type Nav = NativeStackNavigationProp<AuthStackParamList, "Confirm">;
type Route = RouteProp<AuthStackParamList, "Confirm">;

export default function ConfirmScreen() {
  const navigation = useNavigation<Nav>();
  const route = useRoute<Route>();
  const email = route.params.email;
  const { confirmSignUp } = useAuth();
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleConfirm() {
    if (!code) {
      Alert.alert("Error", "Please enter the verification code.");
      return;
    }
    setLoading(true);
    try {
      await confirmSignUp(email, code.trim());
      Alert.alert("Success", "Email verified! You can now sign in.");
      navigation.navigate("SignIn");
    } catch (err: any) {
      Alert.alert("Verification Failed", err.message || "Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <View style={styles.container}>
      <Image
        source={logo}
        style={styles.logo}
        resizeMode="contain"
      />
      <Text style={styles.title}>Verify Email</Text>
      <Text style={styles.subtitle}>
        We sent a code to {email}
      </Text>

      <TextInput
        style={styles.input}
        placeholder="Verification Code"
        value={code}
        onChangeText={setCode}
        keyboardType="number-pad"
        textContentType="oneTimeCode"
      />

      <TouchableOpacity
        style={styles.button}
        onPress={handleConfirm}
        disabled={loading}
      >
        {loading ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.buttonText}>Verify</Text>
        )}
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: "center",
    padding: 24,
    backgroundColor: "#FBF8F3",
  },
  logo: {
    width: 100,
    height: 100,
    alignSelf: "center",
    marginBottom: 16,
  },
  title: {
    fontSize: 36,
    fontWeight: "bold",
    color: "#4E535B",
    textAlign: "center",
    marginBottom: 4,
  },
  subtitle: {
    fontSize: 16,
    color: "#7A7E85",
    textAlign: "center",
    marginBottom: 32,
  },
  input: {
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: "#D6D1CA",
    borderRadius: 8,
    padding: 14,
    fontSize: 16,
    marginBottom: 12,
    textAlign: "center",
    letterSpacing: 4,
  },
  button: {
    backgroundColor: "#5B9FB8",
    borderRadius: 8,
    padding: 16,
    alignItems: "center",
    marginTop: 8,
  },
  buttonText: {
    color: "#fff",
    fontSize: 18,
    fontWeight: "600",
  },
});
