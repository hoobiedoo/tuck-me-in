import React from "react";
import {
  View,
  Text,
  Image,
  TouchableOpacity,
  StyleSheet,
} from "react-native";

import { useAuth } from "../contexts/AuthContext";

const logo = require("../../assets/logo.png");

interface Props {
  onNavigate: (screen: string) => void;
}

export default function HomeScreen({ onNavigate }: Props) {
  const { user, signOut } = useAuth();

  return (
    <View style={styles.container}>
      <View style={styles.headerRow}>
        <Image source={logo} style={styles.logo} resizeMode="contain" />
        <View>
          <Text style={styles.greeting}>
            Welcome, {user?.firstName || "Reader"}!
          </Text>
          <Text style={styles.subtitle}>Your bedtime story hub</Text>
        </View>
      </View>

      <TouchableOpacity style={styles.card} onPress={() => onNavigate("library")}>
        <Text style={styles.cardTitle}>Story Library</Text>
        <Text style={styles.cardDesc}>Browse and play recorded stories</Text>
      </TouchableOpacity>

      <TouchableOpacity style={styles.card} onPress={() => onNavigate("record")}>
        <Text style={styles.cardTitle}>Record a Story</Text>
        <Text style={styles.cardDesc}>Read and record a new bedtime story</Text>
      </TouchableOpacity>

      <TouchableOpacity style={styles.card} onPress={() => onNavigate("requests")}>
        <Text style={styles.cardTitle}>Story Requests</Text>
        <Text style={styles.cardDesc}>See what stories kids are asking for</Text>
      </TouchableOpacity>

      <TouchableOpacity style={styles.card} onPress={() => onNavigate("household")}>
        <Text style={styles.cardTitle}>Household</Text>
        <Text style={styles.cardDesc}>Manage family members and devices</Text>
      </TouchableOpacity>

      <TouchableOpacity style={styles.signOutButton} onPress={signOut}>
        <Text style={styles.signOutText}>Sign Out</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 24,
    paddingTop: 60,
    backgroundColor: "#FBF8F3",
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    marginBottom: 24,
  },
  logo: {
    width: 60,
    height: 60,
    marginRight: 12,
  },
  greeting: {
    fontSize: 28,
    fontWeight: "bold",
    color: "#4E535B",
  },
  subtitle: {
    fontSize: 16,
    color: "#7A7E85",
  },
  card: {
    backgroundColor: "#fff",
    borderRadius: 12,
    padding: 20,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: "#E8E3DC",
  },
  cardTitle: {
    fontSize: 18,
    fontWeight: "600",
    color: "#3D4148",
    marginBottom: 4,
  },
  cardDesc: {
    fontSize: 14,
    color: "#7A7E85",
  },
  signOutButton: {
    marginTop: 24,
    alignItems: "center",
    padding: 14,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#D6D1CA",
  },
  signOutText: {
    color: "#7A7E85",
    fontSize: 16,
  },
});
