import React from "react";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import MainTabs from "./MainTabs";
import ChildProfileSelectScreen from "../screens/ChildProfileSelectScreen";
import ChildHomeScreen from "../screens/ChildHomeScreen";
import BookDetailScreen from "../screens/BookDetailScreen";
import StoryWizardInitScreen from "../screens/StoryWizardInitScreen";
import StoryWizardPageScreen from "../screens/StoryWizardPageScreen";

export type MainStackParamList = {
  MainTabs: undefined;
  ChildSelect: undefined;
  ChildHome: { childId: string; childName: string };
  BookDetail: { bookId: string; title: string };
  StoryWizardInit: undefined;
  StoryWizardPage: { storyInstanceId: string; pageOrder: string };
};

const Stack = createNativeStackNavigator<MainStackParamList>();

export default function MainStack() {
  return (
    <Stack.Navigator screenOptions={{ headerShown: false }}>
      <Stack.Screen name="MainTabs" component={MainTabs} />
      <Stack.Screen name="ChildSelect" component={ChildProfileSelectScreen} />
      <Stack.Screen name="ChildHome" component={ChildHomeScreen} />
      <Stack.Screen name="BookDetail" component={BookDetailScreen} />
      <Stack.Screen name="StoryWizardInit" component={StoryWizardInitScreen} />
      <Stack.Screen name="StoryWizardPage" component={StoryWizardPageScreen} />
    </Stack.Navigator>
  );
}
