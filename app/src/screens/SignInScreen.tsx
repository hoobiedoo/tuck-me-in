import React, { useState } from "react";
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Image,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useNavigation } from "@react-navigation/native";
import type { NativeStackNavigationProp } from "@react-navigation/native-stack";
import { useAuth } from "../contexts/AuthContext";
import type { AuthStackParamList } from "../navigation/AuthStack";

const logo = require("../../assets/logo.png");

type Nav = NativeStackNavigationProp<AuthStackParamList, "SignIn">;

export default function SignInScreen() {
  const navigation = useNavigation<Nav>();
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSignIn() {
    if (!email || !password) {
      setError("Please enter email and password.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await signIn(email.trim().toLowerCase(), password);
    } catch (err: any) {
      setError(err.message || "Please try again.");
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
      <Text style={styles.subtitle}>Sign in to your account</Text>

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
        textContentType="emailAddress"
      />
      <View style={styles.passwordInputContainer}>
        <TextInput
          style={styles.passwordInput}
          placeholder="Password"
          value={password}
          onChangeText={(value) => {
            setPassword(value);
            setError("");
          }}
          secureTextEntry={!showPassword}
          textContentType="password"
        />
        <TouchableOpacity
          style={styles.passwordToggle}
          onPress={() => setShowPassword((visible) => !visible)}
          accessibilityLabel={showPassword ? "Hide password" : "Show password"}
        >
          <Ionicons name={showPassword ? "eye-off-outline" : "eye-outline"} size={22} color="#7A7E85" />
        </TouchableOpacity>
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <TouchableOpacity
        style={styles.button}
        onPress={handleSignIn}
        disabled={loading}
      >
        {loading ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.buttonText}>Sign In</Text>
        )}
      </TouchableOpacity>

      <TouchableOpacity onPress={() => navigation.navigate("SignUp")} style={styles.link}>
        <Text style={styles.linkText}>
          Don't have an account? <Text style={styles.linkBold}>Sign Up</Text>
        </Text>
      </TouchableOpacity>

      <TouchableOpacity onPress={() => navigation.navigate("ForgotPassword")} style={styles.link}>
        <Text style={styles.linkBold}>Forgot password?</Text>
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
    width: 120,
    height: 120,
    alignSelf: "center",
    marginBottom: 8,
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
    fontSize: 14,
    color: "#7A7E85",
  },
  linkBold: {
    color: "#5B9FB8",
    fontWeight: "600",
  },
});
