import React, { useEffect, useState, useCallback } from "react";
import {
  View,
  Text,
  TextInput,
  FlatList,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Modal,
} from "react-native";
import { useAuth } from "../contexts/AuthContext";
import { apiGet, apiPut, apiPost, apiDelete } from "../services/api";

interface Household {
  householdId: string;
  name: string;
  plan: string;
  inviteCode?: string;
}

interface Child {
  childId: string;
  householdId: string;
  name: string;
  approvedReaders: string[];
}

interface LinkedDevice {
  deviceId: string;
  householdId: string;
  platform: string;
  linkedAt: string;
}

interface Props {
  onBack: () => void;
}

interface Member {
  userId: string;
  householdId: string;
  displayName: string;
  firstName: string;
  lastName: string;
}

export default function HouseholdScreen({ onBack }: Props) {
  const { householdId, userId, userRole } = useAuth();
  const [household, setHousehold] = useState<Household | null>(null);
  const [children, setChildren] = useState<Child[]>([]);
  const [devices, setDevices] = useState<LinkedDevice[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(true);

  // Edit household name
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [savingName, setSavingName] = useState(false);

  // Edit display name
  const [editingDisplayName, setEditingDisplayName] = useState(false);
  const [displayNameDraft, setDisplayNameDraft] = useState("");
  const [savingDisplayName, setSavingDisplayName] = useState(false);

  // Add child modal
  const [showAddChild, setShowAddChild] = useState(false);
  const [newChildName, setNewChildName] = useState("");
  const [addingChild, setAddingChild] = useState(false);

  const loadData = useCallback(async () => {
    if (!householdId) return;
    setLoading(true);
    try {
      const [hh, ch, dev, mem] = await Promise.all([
        apiGet<Household>(`/households/${householdId}`),
        apiGet<Child[]>(`/households/${householdId}/children`),
        apiGet<LinkedDevice[]>(`/devices?householdId=${householdId}`),
        apiGet<Member[]>(`/households/${householdId}/members`),
      ]);
      setHousehold(hh);
      setChildren(ch);
      setDevices(dev);
      setMembers(mem);
    } catch (err: any) {
      window.alert("Could not load household data.");
    } finally {
      setLoading(false);
    }
  }, [householdId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  async function handleSaveName() {
    if (!householdId || !nameDraft.trim()) return;
    setSavingName(true);
    try {
      const updated = await apiPut<Household>(`/households/${householdId}`, {
        name: nameDraft.trim(),
      });
      setHousehold(updated);
      setEditingName(false);
    } catch (err: any) {
      window.alert("Could not update household name.");
    } finally {
      setSavingName(false);
    }
  }

  async function handleSaveDisplayName() {
    if (!householdId || !userId || !displayNameDraft.trim()) return;
    setSavingDisplayName(true);
    try {
      const updated = await apiPut<Member>(
        `/households/${householdId}/members/${userId}`,
        { displayName: displayNameDraft.trim() }
      );
      setMembers((prev) =>
        prev.map((m) => (m.userId === userId ? { ...m, ...updated } : m))
      );
      setEditingDisplayName(false);
    } catch (err: any) {
      window.alert("Could not update display name.");
    } finally {
      setSavingDisplayName(false);
    }
  }

  async function handleAddChild() {
    if (!householdId || !newChildName.trim()) {
      window.alert("Please enter a name.");
      return;
    }
    setAddingChild(true);
    try {
      const child = await apiPost<Child>(
        `/households/${householdId}/children`,
        { name: newChildName.trim(), approvedReaders: [] }
      );
      setChildren((prev) => [...prev, child]);
      setNewChildName("");
      setShowAddChild(false);
    } catch (err: any) {
      window.alert("Could not add child.");
    } finally {
      setAddingChild(false);
    }
  }

  async function handleUnlinkDevice(deviceId: string) {
    const confirmed = window.confirm("Are you sure you want to unlink this device?");
    if (!confirmed) return;
    try {
      await apiDelete(`/devices/${deviceId}`);
      setDevices((prev) => prev.filter((d) => d.deviceId !== deviceId));
    } catch (err: any) {
      window.alert("Could not unlink device.");
    }
  }

  function platformLabel(platform: string): string {
    switch (platform) {
      case "alexa": return "Amazon Alexa";
      case "google": return "Google Assistant";
      case "siri": return "Siri / HomePod";
      case "bixby": return "Samsung Bixby";
      default: return platform;
    }
  }

  if (loading) {
    return (
      <View style={styles.container}>
        <View style={styles.header}>
          <TouchableOpacity onPress={onBack}>
            <Text style={styles.backButton}>Back</Text>
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Household</Text>
          <View style={{ width: 40 }} />
        </View>
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#7c3aed" />
        </View>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={onBack}>
          <Text style={styles.backButton}>Back</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Household</Text>
        <View style={{ width: 40 }} />
      </View>

      <FlatList
        data={[]}
        renderItem={() => null}
        contentContainerStyle={styles.scrollContent}
        ListHeaderComponent={
          <>
            {/* Household Name */}
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Household Name</Text>
              {editingName ? (
                <View style={styles.editRow}>
                  <TextInput
                    style={[styles.input, { flex: 1 }]}
                    value={nameDraft}
                    onChangeText={setNameDraft}
                    autoFocus
                  />
                  <TouchableOpacity
                    style={styles.saveButton}
                    onPress={handleSaveName}
                    disabled={savingName}
                  >
                    {savingName ? (
                      <ActivityIndicator color="#fff" size="small" />
                    ) : (
                      <Text style={styles.saveButtonText}>Save</Text>
                    )}
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={styles.cancelEditButton}
                    onPress={() => setEditingName(false)}
                  >
                    <Text style={styles.cancelEditText}>Cancel</Text>
                  </TouchableOpacity>
                </View>
              ) : (
                <TouchableOpacity
                  style={styles.nameCard}
                  onPress={() => {
                    setNameDraft(household?.name || "");
                    setEditingName(true);
                  }}
                >
                  <Text style={styles.nameText}>{household?.name}</Text>
                  <Text style={styles.editHint}>Tap to edit</Text>
                </TouchableOpacity>
              )}
              <View style={styles.planRow}>
                <Text style={styles.planLabel}>Plan:</Text>
                <View style={styles.planBadge}>
                  <Text style={styles.planText}>{household?.plan || "free"}</Text>
                </View>
              </View>
            </View>

            {/* Your Display Name */}
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Your Display Name</Text>
              <Text style={styles.displayNameHint}>
                This is how kids will ask for you on Alexa (e.g. "Daddy", "Grandma").
              </Text>
              {(() => {
                const me = members.find((m) => m.userId === userId);
                const currentName = me?.displayName || "";
                if (editingDisplayName) {
                  return (
                    <View style={styles.editRow}>
                      <TextInput
                        style={[styles.input, { flex: 1 }]}
                        value={displayNameDraft}
                        onChangeText={setDisplayNameDraft}
                        placeholder="e.g. Daddy, Grandma, Uncle Bob"
                        autoFocus
                      />
                      <TouchableOpacity
                        style={styles.saveButton}
                        onPress={handleSaveDisplayName}
                        disabled={savingDisplayName}
                      >
                        {savingDisplayName ? (
                          <ActivityIndicator color="#fff" size="small" />
                        ) : (
                          <Text style={styles.saveButtonText}>Save</Text>
                        )}
                      </TouchableOpacity>
                      <TouchableOpacity
                        style={styles.cancelEditButton}
                        onPress={() => setEditingDisplayName(false)}
                      >
                        <Text style={styles.cancelEditText}>Cancel</Text>
                      </TouchableOpacity>
                    </View>
                  );
                }
                return (
                  <TouchableOpacity
                    style={styles.nameCard}
                    onPress={() => {
                      setDisplayNameDraft(currentName);
                      setEditingDisplayName(true);
                    }}
                  >
                    <Text style={styles.nameText}>
                      {currentName || "Not set"}
                    </Text>
                    <Text style={styles.editHint}>Tap to edit</Text>
                  </TouchableOpacity>
                );
              })()}
            </View>

            {/* Invite Code (admin only) */}
            {userRole === "admin" && household?.inviteCode && (
              <View style={styles.section}>
                <Text style={styles.sectionTitle}>Invite Code</Text>
                <Text style={styles.displayNameHint}>
                  Share this code with family members so they can join your household.
                </Text>
                <View style={styles.inviteCodeCard}>
                  <Text style={styles.inviteCodeText}>{household.inviteCode}</Text>
                </View>
              </View>
            )}

            {/* Family Members */}
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Family Members</Text>
              {members.length === 0 ? (
                <Text style={styles.emptyText}>No members yet.</Text>
              ) : (
                members.map((member) => (
                  <View key={member.userId} style={styles.listCard}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.listCardTitle}>
                        {member.displayName || `${member.firstName} ${member.lastName}`.trim() || "Unknown"}
                      </Text>
                      <Text style={styles.listCardMeta}>
                        {member.role === "admin" ? "Admin" : "Member"}
                        {member.userId === userId ? " (you)" : ""}
                      </Text>
                    </View>
                  </View>
                ))
              )}
            </View>

            {/* Children */}
            <View style={styles.section}>
              <View style={styles.sectionHeader}>
                <Text style={styles.sectionTitle}>Children</Text>
                <TouchableOpacity onPress={() => setShowAddChild(true)}>
                  <Text style={styles.addButton}>+ Add</Text>
                </TouchableOpacity>
              </View>
              {children.length === 0 ? (
                <Text style={styles.emptyText}>
                  No children added yet. Tap "+ Add" to add a child profile.
                </Text>
              ) : (
                children.map((child) => (
                  <View key={child.childId} style={styles.listCard}>
                    <Text style={styles.listCardTitle}>{child.name}</Text>
                    <Text style={styles.listCardMeta}>
                      {child.approvedReaders.length} approved reader{child.approvedReaders.length !== 1 ? "s" : ""}
                    </Text>
                  </View>
                ))
              )}
            </View>

            {/* Linked Devices */}
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Linked Devices</Text>
              {devices.length === 0 ? (
                <Text style={styles.emptyText}>
                  No devices linked. Link a voice assistant by saying "Alexa, open Tuck Me In" on your device.
                </Text>
              ) : (
                devices.map((device) => (
                  <View key={device.deviceId} style={styles.listCard}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.listCardTitle}>
                        {platformLabel(device.platform)}
                      </Text>
                      <Text style={styles.listCardMeta}>
                        Linked {new Date(device.linkedAt).toLocaleDateString()}
                      </Text>
                    </View>
                    <TouchableOpacity onPress={() => handleUnlinkDevice(device.deviceId)}>
                      <Text style={styles.unlinkText}>Unlink</Text>
                    </TouchableOpacity>
                  </View>
                ))
              )}
            </View>
          </>
        }
      />

      {/* Add Child Modal */}
      <Modal visible={showAddChild} animationType="slide" transparent>
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <Text style={styles.modalTitle}>Add a Child</Text>

            <Text style={styles.label}>Child's Name</Text>
            <TextInput
              style={styles.input}
              placeholder="e.g. Emma"
              value={newChildName}
              onChangeText={setNewChildName}
              autoFocus
            />

            <View style={styles.modalActions}>
              <TouchableOpacity
                style={styles.modalCancelButton}
                onPress={() => {
                  setShowAddChild(false);
                  setNewChildName("");
                }}
              >
                <Text style={styles.modalCancelText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.modalSubmitButton}
                onPress={handleAddChild}
                disabled={addingChild}
              >
                {addingChild ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <Text style={styles.modalSubmitText}>Add Child</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#f8f4ff",
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 24,
    paddingTop: 60,
    paddingBottom: 16,
  },
  backButton: {
    fontSize: 16,
    color: "#7c3aed",
    fontWeight: "600",
  },
  headerTitle: {
    fontSize: 20,
    fontWeight: "bold",
    color: "#5b21b6",
  },
  center: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
  },
  scrollContent: {
    padding: 24,
    paddingTop: 8,
  },
  section: {
    marginBottom: 28,
  },
  sectionHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 12,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: "700",
    color: "#1f2937",
    marginBottom: 12,
  },
  nameCard: {
    backgroundColor: "#fff",
    borderRadius: 10,
    padding: 16,
    borderWidth: 1,
    borderColor: "#e5e7eb",
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  nameText: {
    fontSize: 18,
    fontWeight: "600",
    color: "#1f2937",
  },
  editHint: {
    fontSize: 13,
    color: "#9ca3af",
  },
  editRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  input: {
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: "#d1d5db",
    borderRadius: 8,
    padding: 12,
    fontSize: 16,
  },
  saveButton: {
    backgroundColor: "#7c3aed",
    borderRadius: 8,
    paddingVertical: 12,
    paddingHorizontal: 16,
  },
  saveButtonText: {
    color: "#fff",
    fontSize: 15,
    fontWeight: "600",
  },
  cancelEditButton: {
    paddingVertical: 12,
    paddingHorizontal: 8,
  },
  cancelEditText: {
    color: "#6b7280",
    fontSize: 15,
  },
  planRow: {
    flexDirection: "row",
    alignItems: "center",
    marginTop: 10,
    gap: 8,
  },
  planLabel: {
    fontSize: 14,
    color: "#6b7280",
  },
  planBadge: {
    backgroundColor: "#dbeafe",
    borderRadius: 12,
    paddingHorizontal: 10,
    paddingVertical: 3,
  },
  planText: {
    fontSize: 13,
    fontWeight: "600",
    color: "#2563eb",
    textTransform: "capitalize",
  },
  addButton: {
    fontSize: 16,
    color: "#7c3aed",
    fontWeight: "600",
    marginBottom: 12,
  },
  inviteCodeCard: {
    backgroundColor: "#fff",
    borderRadius: 10,
    padding: 20,
    borderWidth: 2,
    borderColor: "#7c3aed",
    borderStyle: "dashed",
    alignItems: "center",
  },
  inviteCodeText: {
    fontSize: 32,
    fontWeight: "bold",
    color: "#7c3aed",
    letterSpacing: 6,
  },
  displayNameHint: {
    fontSize: 13,
    color: "#9ca3af",
    marginBottom: 10,
    marginTop: -6,
  },
  emptyText: {
    fontSize: 14,
    color: "#9ca3af",
    lineHeight: 20,
  },
  listCard: {
    backgroundColor: "#fff",
    borderRadius: 10,
    padding: 14,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: "#e5e7eb",
    flexDirection: "row",
    alignItems: "center",
  },
  listCardTitle: {
    fontSize: 16,
    fontWeight: "600",
    color: "#1f2937",
  },
  listCardMeta: {
    fontSize: 13,
    color: "#6b7280",
    marginTop: 2,
  },
  unlinkText: {
    fontSize: 14,
    color: "#ef4444",
    fontWeight: "600",
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.4)",
    justifyContent: "center",
    padding: 24,
  },
  modalContent: {
    backgroundColor: "#fff",
    borderRadius: 16,
    padding: 24,
  },
  modalTitle: {
    fontSize: 22,
    fontWeight: "bold",
    color: "#5b21b6",
    marginBottom: 20,
  },
  label: {
    fontSize: 14,
    fontWeight: "600",
    color: "#374151",
    marginBottom: 6,
  },
  modalActions: {
    flexDirection: "row",
    justifyContent: "flex-end",
    gap: 12,
    marginTop: 16,
  },
  modalCancelButton: {
    borderWidth: 1,
    borderColor: "#d1d5db",
    borderRadius: 8,
    paddingVertical: 12,
    paddingHorizontal: 20,
  },
  modalCancelText: {
    color: "#6b7280",
    fontSize: 16,
  },
  modalSubmitButton: {
    backgroundColor: "#7c3aed",
    borderRadius: 8,
    paddingVertical: 12,
    paddingHorizontal: 20,
  },
  modalSubmitText: {
    color: "#fff",
    fontSize: 16,
    fontWeight: "600",
  },
});
