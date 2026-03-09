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
import { apiGet, apiPost, apiPut } from "../services/api";

interface StoryRequest {
  requestId: string;
  householdId: string;
  childId: string;
  requestedReaderId: string;
  bookTitle: string;
  status: string;
  createdAt: string;
  updatedAt: string;
}

interface Child {
  childId: string;
  name: string;
  householdId: string;
}

interface Member {
  userId: string;
  displayName: string;
  firstName?: string;
  lastName?: string;
  role?: string;
}

interface Props {
  onBack: () => void;
  onRecord: (title: string, requestId: string) => void;
}

export default function StoryRequestsScreen({ onBack, onRecord }: Props) {
  const { householdId, userId, user } = useAuth();
  const [requests, setRequests] = useState<StoryRequest[]>([]);
  const [children, setChildren] = useState<Child[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [bookTitle, setBookTitle] = useState("");
  const [childName, setChildName] = useState("");
  const [selectedChildId, setSelectedChildId] = useState<string | null>(null);
  const [selectedReaderId, setSelectedReaderId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const loadData = useCallback(async () => {
    if (!householdId) return;
    setLoading(true);
    try {
      const [reqData, childData, memberData] = await Promise.all([
        apiGet<StoryRequest[]>(`/requests?householdId=${householdId}`),
        apiGet<Child[]>(`/households/${householdId}/children`),
        apiGet<Member[]>(`/households/${householdId}/members`),
      ]);
      setRequests(reqData.sort((a, b) => b.createdAt.localeCompare(a.createdAt)));
      setChildren(childData);
      setMembers(memberData);
    } catch (err: any) {
      window.alert("Could not load requests.");
    } finally {
      setLoading(false);
    }
  }, [householdId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  async function handleCreateRequest() {
    if (!bookTitle.trim()) {
      window.alert("Please enter a book title.");
      return;
    }
    if (!selectedReaderId) {
      window.alert("Please select who should read this story.");
      return;
    }
    if (!selectedChildId && !childName.trim()) {
      window.alert("Please select a child or enter a new child's name.");
      return;
    }
    if (!householdId || !userId) return;

    setSubmitting(true);
    try {
      let childId = selectedChildId;

      // Create child if new name entered
      if (!childId && childName.trim()) {
        const newChild = await apiPost(`/households/${householdId}/children`, {
          name: childName.trim(),
          approvedReaders: [userId],
        });
        childId = newChild.childId;
        setChildren((prev) => [...prev, newChild]);
      }

      await apiPost("/requests", {
        householdId,
        childId,
        requestedReaderId: selectedReaderId,
        bookTitle: bookTitle.trim(),
      });

      setShowModal(false);
      setBookTitle("");
      setChildName("");
      setSelectedChildId(null);
      setSelectedReaderId(null);
      await loadData();
    } catch (err: any) {
      window.alert(err.message || "Could not create request.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleUpdateStatus(requestId: string, status: string) {
    try {
      await apiPut(`/requests/${requestId}`, { status });
      await loadData();
    } catch (err: any) {
      window.alert("Could not update request.");
    }
  }

  function statusColor(status: string): string {
    switch (status) {
      case "pending": return "#f59e0b";
      case "in-progress": return "#3b82f6";
      case "completed": return "#16a34a";
      case "declined": return "#ef4444";
      default: return "#7A7E85";
    }
  }

  function getReaderName(readerId: string): string {
    const member = members.find((m) => m.userId === readerId);
    if (member) return member.displayName || member.firstName || "Unknown";
    return "Unknown";
  }

  function renderRequest({ item }: { item: StoryRequest }) {
    const child = children.find((c) => c.childId === item.childId);
    const readerName = getReaderName(item.requestedReaderId);
    const isMyRequest = item.requestedReaderId === userId;
    return (
      <View style={styles.requestCard}>
        <View style={styles.requestHeader}>
          <Text style={styles.requestTitle}>{item.bookTitle}</Text>
          <View style={[styles.statusBadge, { backgroundColor: statusColor(item.status) + "20" }]}>
            <Text style={[styles.statusText, { color: statusColor(item.status) }]}>
              {item.status}
            </Text>
          </View>
        </View>
        <Text style={styles.requestMeta}>
          For {child?.name || "Unknown"} · Reader: {readerName} · {new Date(item.createdAt).toLocaleDateString()}
        </Text>
        {item.status === "pending" && isMyRequest && (
          <View style={styles.actionRow}>
            <TouchableOpacity
              style={styles.actionButton}
              onPress={async () => {
                await handleUpdateStatus(item.requestId, "in-progress");
                onRecord(item.bookTitle, item.requestId);
              }}
            >
              <Text style={styles.actionButtonText}>Start Recording</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.declineButton}
              onPress={() => handleUpdateStatus(item.requestId, "declined")}
            >
              <Text style={styles.declineButtonText}>Decline</Text>
            </TouchableOpacity>
          </View>
        )}
        {item.status === "pending" && !isMyRequest && (
          <Text style={styles.waitingText}>Waiting for {readerName} to record</Text>
        )}
        {item.status === "in-progress" && isMyRequest && (
          <View style={styles.actionRow}>
            <TouchableOpacity
              style={styles.actionButton}
              onPress={() => onRecord(item.bookTitle, item.requestId)}
            >
              <Text style={styles.actionButtonText}>Continue Recording</Text>
            </TouchableOpacity>
          </View>
        )}
        {item.status === "in-progress" && !isMyRequest && (
          <Text style={styles.waitingText}>{readerName} is working on it</Text>
        )}
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={onBack}>
          <Text style={styles.backButton}>Back</Text>
        </TouchableOpacity>
        <Text style={styles.title}>Story Requests</Text>
        <TouchableOpacity onPress={() => setShowModal(true)}>
          <Text style={styles.addButton}>+ New</Text>
        </TouchableOpacity>
      </View>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#5B9FB8" />
        </View>
      ) : requests.length === 0 ? (
        <View style={styles.center}>
          <Text style={styles.emptyTitle}>No requests yet</Text>
          <Text style={styles.emptyDesc}>
            Tap "+ New" to request a bedtime story.
          </Text>
        </View>
      ) : (
        <FlatList
          data={requests}
          keyExtractor={(item) => item.requestId}
          renderItem={renderRequest}
          contentContainerStyle={styles.list}
        />
      )}

      <Modal visible={showModal} animationType="slide" transparent>
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <Text style={styles.modalTitle}>Request a Story</Text>

            <Text style={styles.label}>Book Title</Text>
            <TextInput
              style={styles.input}
              placeholder="e.g. The Very Hungry Caterpillar"
              value={bookTitle}
              onChangeText={setBookTitle}
            />

            <Text style={styles.label}>Who should read it?</Text>
            {members.map((member) => (
              <TouchableOpacity
                key={member.userId}
                style={[
                  styles.childOption,
                  selectedReaderId === member.userId && styles.childOptionSelected,
                ]}
                onPress={() => setSelectedReaderId(member.userId)}
              >
                <Text style={[
                  styles.childOptionText,
                  selectedReaderId === member.userId && styles.childOptionTextSelected,
                ]}>
                  {member.displayName || member.firstName || "Unknown"}
                </Text>
              </TouchableOpacity>
            ))}

            <Text style={[styles.label, { marginTop: 8 }]}>For Which Child?</Text>
            {children.map((child) => (
              <TouchableOpacity
                key={child.childId}
                style={[
                  styles.childOption,
                  selectedChildId === child.childId && styles.childOptionSelected,
                ]}
                onPress={() => {
                  setSelectedChildId(child.childId);
                  setChildName("");
                }}
              >
                <Text style={[
                  styles.childOptionText,
                  selectedChildId === child.childId && styles.childOptionTextSelected,
                ]}>
                  {child.name}
                </Text>
              </TouchableOpacity>
            ))}

            <TextInput
              style={styles.input}
              placeholder="Or enter a new child's name"
              value={childName}
              onChangeText={(text) => {
                setChildName(text);
                setSelectedChildId(null);
              }}
            />

            <View style={styles.modalActions}>
              <TouchableOpacity
                style={styles.cancelButton}
                onPress={() => {
                  setShowModal(false);
                  setBookTitle("");
                  setChildName("");
                  setSelectedChildId(null);
                  setSelectedReaderId(null);
                }}
              >
                <Text style={styles.cancelButtonText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.submitButton}
                onPress={handleCreateRequest}
                disabled={submitting}
              >
                {submitting ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <Text style={styles.submitButtonText}>Submit Request</Text>
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
    backgroundColor: "#FBF8F3",
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
    color: "#5B9FB8",
    fontWeight: "600",
  },
  title: {
    fontSize: 20,
    fontWeight: "bold",
    color: "#4E535B",
  },
  addButton: {
    fontSize: 16,
    color: "#5B9FB8",
    fontWeight: "600",
  },
  center: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    padding: 24,
  },
  emptyTitle: {
    fontSize: 20,
    fontWeight: "600",
    color: "#3D4148",
    marginBottom: 8,
  },
  emptyDesc: {
    fontSize: 14,
    color: "#7A7E85",
    textAlign: "center",
  },
  list: {
    padding: 24,
  },
  requestCard: {
    backgroundColor: "#fff",
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: "#E8E3DC",
  },
  requestHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 4,
  },
  requestTitle: {
    fontSize: 16,
    fontWeight: "600",
    color: "#3D4148",
    flex: 1,
  },
  statusBadge: {
    borderRadius: 12,
    paddingHorizontal: 10,
    paddingVertical: 3,
    marginLeft: 8,
  },
  statusText: {
    fontSize: 12,
    fontWeight: "600",
  },
  requestMeta: {
    fontSize: 13,
    color: "#7A7E85",
    marginBottom: 8,
  },
  actionRow: {
    flexDirection: "row",
    gap: 8,
    marginTop: 4,
  },
  actionButton: {
    backgroundColor: "#5B9FB8",
    borderRadius: 6,
    paddingVertical: 8,
    paddingHorizontal: 14,
  },
  actionButtonText: {
    color: "#fff",
    fontSize: 13,
    fontWeight: "600",
  },
  declineButton: {
    borderWidth: 1,
    borderColor: "#D6D1CA",
    borderRadius: 6,
    paddingVertical: 8,
    paddingHorizontal: 14,
  },
  declineButtonText: {
    color: "#7A7E85",
    fontSize: 13,
  },
  waitingText: {
    fontSize: 13,
    color: "#9A9EA5",
    fontStyle: "italic",
    marginTop: 4,
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
    maxHeight: "80%",
  },
  modalTitle: {
    fontSize: 22,
    fontWeight: "bold",
    color: "#4E535B",
    marginBottom: 20,
  },
  label: {
    fontSize: 14,
    fontWeight: "600",
    color: "#4E535B",
    marginBottom: 6,
  },
  input: {
    backgroundColor: "#F7F5F1",
    borderWidth: 1,
    borderColor: "#D6D1CA",
    borderRadius: 8,
    padding: 12,
    fontSize: 16,
    marginBottom: 16,
  },
  childOption: {
    borderWidth: 1,
    borderColor: "#D6D1CA",
    borderRadius: 8,
    padding: 12,
    marginBottom: 8,
  },
  childOptionSelected: {
    borderColor: "#5B9FB8",
    backgroundColor: "#EBF3F7",
  },
  childOptionText: {
    fontSize: 16,
    color: "#4E535B",
  },
  childOptionTextSelected: {
    color: "#5B9FB8",
    fontWeight: "600",
  },
  modalActions: {
    flexDirection: "row",
    justifyContent: "flex-end",
    gap: 12,
    marginTop: 8,
  },
  cancelButton: {
    borderWidth: 1,
    borderColor: "#D6D1CA",
    borderRadius: 8,
    paddingVertical: 12,
    paddingHorizontal: 20,
  },
  cancelButtonText: {
    color: "#7A7E85",
    fontSize: 16,
  },
  submitButton: {
    backgroundColor: "#5B9FB8",
    borderRadius: 8,
    paddingVertical: 12,
    paddingHorizontal: 20,
  },
  submitButtonText: {
    color: "#fff",
    fontSize: 16,
    fontWeight: "600",
  },
});
