import React, { useEffect, useState } from "react";
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  Image,
  StyleSheet,
  ActivityIndicator,
  Alert,
} from "react-native";
import { useNavigation, useRoute } from "@react-navigation/native";
import type { RouteProp } from "@react-navigation/native";
import { apiGet } from "../services/api";
import type { MainStackParamList } from "../navigation/MainStack";

interface Book {
  bookId: string;
  title: string;
  author?: string;
  coverImageUrl?: string;
}

interface Segment {
  cfi: string;
  segmentOrder: string;
  segmentType: string;
  text?: string;
  narratable: boolean;
}

type Route = RouteProp<MainStackParamList, "BookDetail">;

export default function BookDetailScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<Route>();
  const { bookId, title } = route.params;

  const [book, setBook] = useState<Book | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const [bookData, segmentData] = await Promise.all([
          apiGet<Book>(`/books/${bookId}`),
          apiGet<Segment[]>(`/books/${bookId}/segments`),
        ]);
        setBook(bookData);
        setSegments(segmentData.filter((s) => s.narratable));
      } catch (err: any) {
        Alert.alert("Error", "Could not load this book.");
      } finally {
        setLoading(false);
      }
    })();
  }, [bookId]);

  function handleStartRecording(segment: Segment) {
    // Segment-by-segment recording capture (local-first capture,
    // background upload, forced alignment) is a separate, in-progress
    // build — this screen only covers browsing a book and its segments.
    Alert.alert("Coming Soon", "Recording capture for this segment isn't built yet.");
  }

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#5B9FB8" />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <TouchableOpacity style={styles.backButton} onPress={() => navigation.goBack()}>
        <Text style={styles.backButtonText}>‹ Back</Text>
      </TouchableOpacity>

      <View style={styles.header}>
        {book?.coverImageUrl ? (
          <Image source={{ uri: book.coverImageUrl }} style={styles.cover} />
        ) : (
          <View style={[styles.cover, styles.coverPlaceholder]}>
            <Text style={styles.coverPlaceholderIcon}>📖</Text>
          </View>
        )}
        <View style={styles.headerInfo}>
          <Text style={styles.title} numberOfLines={3}>{book?.title || title}</Text>
          {!!book?.author && <Text style={styles.author}>{book.author}</Text>}
          <Text style={styles.meta}>{segments.length} segments to record</Text>
        </View>
      </View>

      <FlatList
        data={segments}
        keyExtractor={(item) => item.cfi}
        contentContainerStyle={styles.list}
        renderItem={({ item, index }) => (
          <TouchableOpacity style={styles.segmentCard} onPress={() => handleStartRecording(item)}>
            <Text style={styles.segmentIndex}>{index + 1}</Text>
            <Text style={styles.segmentText} numberOfLines={2}>
              {item.text || `[${item.segmentType}]`}
            </Text>
          </TouchableOpacity>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#FBF8F3",
  },
  center: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "#FBF8F3",
  },
  backButton: {
    paddingHorizontal: 20,
    paddingTop: 16,
    paddingBottom: 8,
  },
  backButtonText: {
    fontSize: 15,
    color: "#5B9FB8",
    fontWeight: "600",
  },
  header: {
    flexDirection: "row",
    paddingHorizontal: 20,
    paddingBottom: 16,
    borderBottomWidth: 1,
    borderBottomColor: "#E8E3DC",
    marginBottom: 8,
  },
  cover: {
    width: 80,
    height: 106,
    borderRadius: 8,
    backgroundColor: "#F0ECE4",
  },
  coverPlaceholder: {
    alignItems: "center",
    justifyContent: "center",
  },
  coverPlaceholderIcon: {
    fontSize: 28,
  },
  headerInfo: {
    flex: 1,
    marginLeft: 16,
    justifyContent: "center",
  },
  title: {
    fontSize: 20,
    fontWeight: "700",
    color: "#3D4148",
    marginBottom: 4,
  },
  author: {
    fontSize: 14,
    color: "#7A7E85",
    marginBottom: 4,
  },
  meta: {
    fontSize: 13,
    color: "#9A9EA5",
  },
  list: {
    paddingHorizontal: 20,
    paddingBottom: 24,
  },
  segmentCard: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#fff",
    borderRadius: 10,
    padding: 14,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: "#E8E3DC",
  },
  segmentIndex: {
    width: 28,
    fontSize: 13,
    fontWeight: "700",
    color: "#9A9EA5",
  },
  segmentText: {
    flex: 1,
    fontSize: 14,
    color: "#3D4148",
    lineHeight: 20,
  },
});
