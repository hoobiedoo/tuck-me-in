import React, { useCallback, useEffect, useState } from "react";
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
import { useNavigation } from "@react-navigation/native";
import { apiGet } from "../services/api";

interface Book {
  bookId: string;
  title: string;
  author?: string;
  coverImageUrl?: string;
  segmentCount?: number;
}

export default function BookListScreen() {
  const navigation = useNavigation<any>();
  const [books, setBooks] = useState<Book[]>([]);
  const [loading, setLoading] = useState(true);

  const loadBooks = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet<Book[]>("/books");
      setBooks(data);
    } catch (err: any) {
      Alert.alert("Error", "Could not load the book catalogue.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBooks();
  }, [loadBooks]);

  function handleSelect(book: Book) {
    navigation.getParent()?.navigate("BookDetail", { bookId: book.bookId, title: book.title });
  }

  function renderBook({ item }: { item: Book }) {
    return (
      <TouchableOpacity style={styles.bookCard} onPress={() => handleSelect(item)}>
        <View style={styles.coverBox}>
          {item.coverImageUrl ? (
            <Image source={{ uri: item.coverImageUrl }} style={styles.cover} />
          ) : (
            <View style={styles.coverPlaceholder}>
              <Text style={styles.coverPlaceholderIcon}>📖</Text>
            </View>
          )}
        </View>
        <View style={styles.bookInfo}>
          <Text style={styles.bookTitle} numberOfLines={2}>{item.title}</Text>
          {!!item.author && (
            <Text style={styles.bookAuthor} numberOfLines={1}>{item.author}</Text>
          )}
          {typeof item.segmentCount === "number" && (
            <Text style={styles.bookMeta}>{item.segmentCount} segments</Text>
          )}
        </View>
      </TouchableOpacity>
    );
  }

  return (
    <View style={styles.container}>
      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#5B9FB8" />
        </View>
      ) : books.length === 0 ? (
        <View style={styles.center}>
          <Text style={styles.emptyTitle}>No books yet</Text>
          <Text style={styles.emptyDesc}>
            The book catalogue is empty right now — check back soon.
          </Text>
        </View>
      ) : (
        <FlatList
          data={books}
          keyExtractor={(item) => item.bookId}
          renderItem={renderBook}
          numColumns={2}
          columnWrapperStyle={styles.row}
          contentContainerStyle={styles.list}
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
    padding: 16,
  },
  row: {
    justifyContent: "space-between",
  },
  bookCard: {
    width: "48%",
    backgroundColor: "#fff",
    borderRadius: 12,
    padding: 12,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: "#E8E3DC",
  },
  coverBox: {
    width: "100%",
    aspectRatio: 3 / 4,
    borderRadius: 8,
    overflow: "hidden",
    backgroundColor: "#F0ECE4",
    marginBottom: 8,
  },
  cover: {
    width: "100%",
    height: "100%",
  },
  coverPlaceholder: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  coverPlaceholderIcon: {
    fontSize: 36,
  },
  bookInfo: {
    paddingHorizontal: 2,
  },
  bookTitle: {
    fontSize: 14,
    fontWeight: "600",
    color: "#3D4148",
    marginBottom: 2,
  },
  bookAuthor: {
    fontSize: 12,
    color: "#7A7E85",
    marginBottom: 2,
  },
  bookMeta: {
    fontSize: 11,
    color: "#9A9EA5",
  },
});
