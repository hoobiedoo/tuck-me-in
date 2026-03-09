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
import { useAuth } from "../contexts/AuthContext";

const logo = require("../../assets/logo.png");

interface Props {
  inviteCode?: string;
}

export default function HouseholdSetupScreen({ inviteCode: initialCode }: Props) {
  const { user, createHousehold, joinHousehold, signOut } = useAuth();
  const hasInitialCode = !!(initialCode && initialCode.trim());
  const [mode, setMode] = useState<"choose" | "create" | "join">(
    hasInitialCode ? "join" : "choose"
  );
  const [householdName, setHouseholdName] = useState(
    user ? `${user.firstName}'s Family` : "My Family"
  );
  const [inviteCode, setInviteCode] = useState(
    initialCode ? initialCode.toUpperCase() : ""
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleCreate() {
    if (!householdName.trim()) {
      setError("Please enter a household name.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await createHousehold(householdName.trim());
    } catch (err: any) {
      setError(err.message || "Could not create household.");
    } finally {
      setLoading(false);
    }
  }

  async function handleJoin() {
    if (!inviteCode.trim()) {
      setError("Please enter an invite code.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await joinHousehold(inviteCode.trim());
    } catch (err: any) {
      setError("Invalid invite code. Please check and try again.");
    } finally {
      setLoading(false);
    }
  }

  if (mode === "create") {
    return (
      <View style={styles.container}>
        <Image source={logo} style={styles.logoSmall} />
        <Text style={styles.title}>Create Your Household</Text>
        <Text style={styles.subtitle}>
          You'll be the admin. You can invite family members later.
        </Text>

        <Text style={styles.label}>Household Name</Text>
        <TextInput
          style={styles.input}
          value={householdName}
          onChangeText={setHouseholdName}
          placeholder="e.g. The Smith Family"
          autoFocus
        />

        {error ? <Text style={styles.error}>{error}</Text> : null}

        <TouchableOpacity
          style={styles.primaryButton}
          onPress={handleCreate}
          disabled={loading}
        >
          {loading ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.primaryButtonText}>Create Household</Text>
          )}
        </TouchableOpacity>

        <TouchableOpacity onPress={() => { setMode("choose"); setError(""); }}>
          <Text style={styles.linkText}>Back</Text>
        </TouchableOpacity>
      </View>
    );
  }

  if (mode === "join") {
    return (
      <View style={styles.container}>
        <Image source={logo} style={styles.logoSmall} />
        <Text style={styles.title}>Join a Household</Text>
        <Text style={styles.subtitle}>
          Enter the invite code shared by your family member.
        </Text>

        <Text style={styles.label}>Invite Code</Text>
        <TextInput
          style={[styles.input, styles.codeInput]}
          value={inviteCode}
          onChangeText={(t) => setInviteCode(t.toUpperCase())}
          placeholder="e.g. ABC123"
          autoCapitalize="characters"
          maxLength={6}
          autoFocus
        />

        {error ? <Text style={styles.error}>{error}</Text> : null}

        <TouchableOpacity
          style={styles.primaryButton}
          onPress={handleJoin}
          disabled={loading}
        >
          {loading ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.primaryButtonText}>Join Household</Text>
          )}
        </TouchableOpacity>

        <TouchableOpacity onPress={() => { setMode("choose"); setError(""); }}>
          <Text style={styles.linkText}>Back</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Image source={logo} style={styles.logoLarge} />
      <Text style={styles.title}>Welcome to Tuck Me In!</Text>
      <Text style={styles.subtitle}>
        Are you starting a new household, or joining an existing one?
      </Text>

      <TouchableOpacity
        style={styles.choiceCard}
        onPress={() => setMode("create")}
      >
        <Text style={styles.choiceTitle}>Create a Household</Text>
        <Text style={styles.choiceDesc}>
          Start fresh. You'll be the admin and can invite family members.
        </Text>
      </TouchableOpacity>

      <TouchableOpacity
        style={styles.choiceCard}
        onPress={() => setMode("join")}
      >
        <Text style={styles.choiceTitle}>Join a Household</Text>
        <Text style={styles.choiceDesc}>
          Someone shared an invite code with you? Enter it to join their household.
        </Text>
      </TouchableOpacity>

      <TouchableOpacity style={styles.signOutLink} onPress={signOut}>
        <Text style={styles.signOutText}>Sign Out</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  logoLarge: {
    width: 120,
    height: 120,
    alignSelf: "center",
    marginBottom: 16,
  },
  logoSmall: {
    width: 80,
    height: 80,
    alignSelf: "center",
    marginBottom: 12,
  },
  container: {
    flex: 1,
    padding: 24,
    paddingTop: 80,
    backgroundColor: "#FBF8F3",
  },
  title: {
    fontSize: 28,
    fontWeight: "bold",
    color: "#4E535B",
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 16,
    color: "#7A7E85",
    marginBottom: 32,
    lineHeight: 22,
  },
  label: {
    fontSize: 14,
    fontWeight: "600",
    color: "#4E535B",
    marginBottom: 6,
  },
  input: {
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: "#D6D1CA",
    borderRadius: 8,
    padding: 14,
    fontSize: 16,
    marginBottom: 16,
  },
  codeInput: {
    fontSize: 24,
    letterSpacing: 4,
    textAlign: "center",
    fontWeight: "600",
  },
  error: {
    color: "#D94444",
    fontSize: 14,
    marginBottom: 12,
  },
  primaryButton: {
    backgroundColor: "#5B9FB8",
    borderRadius: 8,
    paddingVertical: 14,
    alignItems: "center",
    marginBottom: 16,
  },
  primaryButtonText: {
    color: "#fff",
    fontSize: 16,
    fontWeight: "600",
  },
  linkText: {
    color: "#5B9FB8",
    fontSize: 16,
    textAlign: "center",
    fontWeight: "600",
  },
  choiceCard: {
    backgroundColor: "#fff",
    borderRadius: 12,
    padding: 20,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: "#E8E3DC",
  },
  choiceTitle: {
    fontSize: 18,
    fontWeight: "600",
    color: "#3D4148",
    marginBottom: 4,
  },
  choiceDesc: {
    fontSize: 14,
    color: "#7A7E85",
    lineHeight: 20,
  },
  signOutLink: {
    marginTop: 24,
    alignItems: "center",
  },
  signOutText: {
    color: "#7A7E85",
    fontSize: 14,
  },
});
