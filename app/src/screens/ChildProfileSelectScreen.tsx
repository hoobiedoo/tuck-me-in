import React, { useEffect, useState, useCallback } from "react";
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
} from "react-native";
import { useNavigation } from "@react-navigation/native";
import type { NativeStackNavigationProp } from "@react-navigation/native-stack";
import { useAuth } from "../contexts/AuthContext";
import { apiGet } from "../services/api";
import type { MainStackParamList } from "../navigation/MainStack";

interface Child {
  childId: string;
  name: string;
}

type Nav = NativeStackNavigationProp<MainStackParamList, "ChildSelect">;

const AVATAR_COLORS = ["#5B9FB8", "#E8A87C", "#8FBC8F", "#C48FB8", "#E8C468"];

export default function ChildProfileSelectScreen() {
  const navigation = useNavigation<Nav>();
  const { householdId } = useAuth();
  const [children, setChildren] = useState<Child[]>([]);
  const [loading, setLoading] = useState(true);

  const loadChildren = useCallback(async () => {
    if (!householdId) return;
    setLoading(true);
    try {
      const data = await apiGet<Child[]>(`/households/${householdId}/children`);
      setChildren(data);
    } finally {
      setLoading(false);
    }
  }, [householdId]);

  useEffect(() => {
    loadChildren();
  }, [loadChildren]);

  function renderChild({ item, index }: { item: Child; index: number }) {
    const color = AVATAR_COLORS[index % AVATAR_COLORS.length];
    return (
      <TouchableOpacity
        style={styles.tile}
        onPress={() => navigation.navigate("ChildHome", { childId: item.childId, childName: item.name })}
      >
        <View style={[styles.avatar, { backgroundColor: color }]}>
          <Text style={styles.avatarInitial}>{item.name.charAt(0).toUpperCase()}</Text>
        </View>
        <Text style={styles.tileName}>{item.name}</Text>
      </TouchableOpacity>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.topBar}>
        <TouchableOpacity onPress={() => navigation.navigate("MainTabs")}>
          <Text style={styles.exitButton}>Exit Kid Mode</Text>
        </TouchableOpacity>
      </View>

      <Text style={styles.heading}>Who's picking a story?</Text>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#5B9FB8" />
        </View>
      ) : children.length === 0 ? (
        <View style={styles.center}>
          <Text style={styles.emptyText}>
            No child profiles yet. Add one from the Household tab.
          </Text>
        </View>
      ) : (
        <FlatList
          data={children}
          keyExtractor={(item) => item.childId}
          renderItem={renderChild}
          numColumns={3}
          contentContainerStyle={styles.grid}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#FBF8F3",
  },
  topBar: {
    flexDirection: "row",
    justifyContent: "flex-end",
    paddingHorizontal: 24,
    paddingTop: 16,
  },
  exitButton: {
    fontSize: 14,
    color: "#9A9EA5",
    fontWeight: "600",
  },
  heading: {
    fontSize: 24,
    fontWeight: "700",
    color: "#3D4148",
    textAlign: "center",
    marginTop: 24,
    marginBottom: 32,
  },
  center: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    padding: 24,
  },
  emptyText: {
    fontSize: 15,
    color: "#9A9EA5",
    textAlign: "center",
  },
  grid: {
    paddingHorizontal: 16,
    alignItems: "center",
  },
  tile: {
    alignItems: "center",
    width: 110,
    marginHorizontal: 8,
    marginBottom: 28,
  },
  avatar: {
    width: 84,
    height: 84,
    borderRadius: 42,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 10,
  },
  avatarInitial: {
    fontSize: 36,
    fontWeight: "700",
    color: "#fff",
  },
  tileName: {
    fontSize: 16,
    fontWeight: "600",
    color: "#3D4148",
  },
});
