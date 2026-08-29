import React from "react";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { useAuth } from "../contexts/AuthContext";
import HouseholdScreen from "../screens/HouseholdScreen";
import RecordStoryScreen from "../screens/RecordStoryScreen";
import ReviewQueueScreen from "../screens/ReviewQueueScreen";
import StoryLibraryScreen from "../screens/StoryLibraryScreen";
import StoryRequestsScreen from "../screens/StoryRequestsScreen";
import BookListScreen from "../screens/BookListScreen";
import StoryWizardHomeScreen from "../screens/StoryWizardHomeScreen";
import StoryStudioScreen from "../screens/StoryStudioScreen";

export type MainTabsParamList = {
  Home: undefined;
  Requests: undefined;
  Record: { initialTitle?: string; requestId?: string } | undefined;
  Create: undefined;
  Books: undefined;
  Review: undefined;
  Studio: undefined;
  Household: undefined;
};

const Tabs = createBottomTabNavigator<MainTabsParamList>();

export default function MainTabs() {
  const { userRole, isContentProducer } = useAuth();

  return (
    <Tabs.Navigator>
      <Tabs.Screen name="Home" component={StoryLibraryScreen} options={{ title: "Library" }} />
      <Tabs.Screen name="Requests" component={StoryRequestsScreen} />
      <Tabs.Screen name="Record" component={RecordStoryScreen} />
      <Tabs.Screen name="Create" component={StoryWizardHomeScreen} options={{ title: "Create" }} />
      <Tabs.Screen name="Books" component={BookListScreen} options={{ title: "Narrate" }} />
      {userRole === "admin" && (
        <Tabs.Screen name="Review" component={ReviewQueueScreen} options={{ title: "Review" }} />
      )}
      {isContentProducer && (
        <Tabs.Screen name="Studio" component={StoryStudioScreen} options={{ title: "Story Studio" }} />
      )}
      <Tabs.Screen name="Household" component={HouseholdScreen} />
    </Tabs.Navigator>
  );
}
