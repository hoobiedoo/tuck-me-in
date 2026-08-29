import React, { useState } from "react";
import {
  ActivityIndicator,
  Image,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useNavigation } from "@react-navigation/native";
import type { NativeStackNavigationProp } from "@react-navigation/native-stack";
import { useAuth } from "../contexts/AuthContext";
import type { AuthStackParamList } from "../navigation/AuthStack";

const logo = require("../../assets/logo.png");
type Nav = NativeStackNavigationProp<AuthStackParamList, "ForgotPassword">;

type Step = "email" | "reset" | "complete";

export default function ForgotPasswordScreen() {
  const navigation = useNavigation<Nav>();
  const { forgotPassword, confirmPassword } = useAuth();
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSendCode() {
    if (!email.trim()) {
      setError("Please enter your email address.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await forgotPassword(email.trim().toLowerCase());
      setStep("reset");
    } catch (err: any) {
      setError(err.message || "Could not send a reset code.");
    } finally {
      setLoading(false);
    }
  }

  async function handleResetPassword() {
    if (!code.trim() || !newPassword) {
      setError("Please enter the verification code and a new password.");
      return;
    }
    if (newPassword.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await confirmPassword(email.trim().toLowerCase(), code.trim(), newPassword);
      setStep("complete");
    } catch (err: any) {
      setError(err.message || "Could not reset your password.");
    } finally {
      setLoading(false);
    }
  }

  if (step === "complete") {
    return (
      <View style={styles.container}>
        <Image source={logo} style={styles.logo} resizeMode="contain" />
        <Text style={styles.title}>Password reset</Text>
        <Text style={styles.subtitle}>Your password has been changed successfully.</Text>
        <TouchableOpacity style={styles.button} onPress={() => navigation.navigate("SignIn")}>
          <Text style={styles.buttonText}>Return to Sign In</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Image source={logo} style={styles.logo} resizeMode="contain" />
      <Text style={styles.title}>Reset your password</Text>
      <Text style={styles.subtitle}>
        {step === "email"
          ? "Enter your email and we will send you a verification code."
          : "Enter the code from your email and choose a new password."}
      </Text>

      <TextInput
        style={styles.input}
        placeholder="Email"
        value={email}
        onChangeText={(value) => {
          setEmail(value);
          setError("");
        }}
        autoCapitalize="none"
        keyboardType="email-address"
        editable={step === "email"}
      />

      {step === "reset" ? (
        <>
          <TextInput
            style={styles.input}
            placeholder="Verification code"
            value={code}
            onChangeText={(value) => {
              setCode(value);
              setError("");
            }}
            keyboardType="number-pad"
          />
          <View style={styles.passwordInputContainer}>
            <TextInput
              style={styles.passwordInput}
              placeholder="New password"
              value={newPassword}
              onChangeText={(value) => {
                setNewPassword(value);
                setError("");
              }}
              secureTextEntry={!showNewPassword}
            />
            <TouchableOpacity
              style={styles.passwordToggle}
              onPress={() => setShowNewPassword((visible) => !visible)}
              accessibilityLabel={showNewPassword ? "Hide password" : "Show password"}
            >
              <Ionicons name={showNewPassword ? "eye-off-outline" : "eye-outline"} size={22} color="#7A7E85" />
            </TouchableOpacity>
          </View>
        </>
      ) : null}

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <TouchableOpacity
        style={styles.button}
        onPress={step === "email" ? handleSendCode : handleResetPassword}
        disabled={loading}
      >
        {loading ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.buttonText}>{step === "email" ? "Send Reset Code" : "Reset Password"}</Text>
        )}
      </TouchableOpacity>

      <TouchableOpacity style={styles.link} onPress={() => navigation.navigate("SignIn")}>
        <Text style={styles.linkText}>Back to Sign In</Text>
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
    fontSize: 30,
    fontWeight: "bold",
    color: "#4E535B",
    textAlign: "center",
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 16,
    color: "#7A7E85",
    textAlign: "center",
    marginBottom: 28,
  },
  input: {
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: "#D6D1CA",
    borderRadius: 8,
    padding: 14,
    fontSize: 16,
    marginBottom: 12,
  },
  passwordInputContainer: {
    position: "relative",
    marginBottom: 12,
  },
  passwordInput: {
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: "#D6D1CA",
    borderRadius: 8,
    padding: 14,
    paddingRight: 48,
    fontSize: 16,
  },
  passwordToggle: {
    position: "absolute",
    right: 12,
    top: 0,
    bottom: 0,
    justifyContent: "center",
    paddingHorizontal: 4,
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
  error: {
    color: "#D94444",
    fontSize: 14,
    marginBottom: 4,
  },
  link: {
    marginTop: 20,
    alignItems: "center",
  },
  linkText: {
    color: "#5B9FB8",
    fontSize: 14,
    fontWeight: "600",
  },
});
