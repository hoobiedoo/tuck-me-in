import React, { createContext, useContext, useEffect, useState } from "react";
import { CognitoUserSession } from "amazon-cognito-identity-js";
import {
  signIn as cognitoSignIn,
  signOut as cognitoSignOut,
  signUp as cognitoSignUp,
  confirmSignUp as cognitoConfirm,
  getCurrentSession,
  getCurrentUser,
  getUserAttributes,
  SignUpParams,
} from "../services/auth";
import { apiGet, apiPost } from "../services/api";

export interface UserInfo {
  userId: string;
  email: string;
  firstName: string;
  lastName: string;
  householdId?: string;
}

interface AuthContextType {
  isLoading: boolean;
  isAuthenticated: boolean;
  user: UserInfo | null;
  session: CognitoUserSession | null;
  householdId: string | null;
  userId: string | null;
  signUp: (params: SignUpParams) => Promise<void>;
  confirmSignUp: (email: string, code: string) => Promise<void>;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [isLoading, setIsLoading] = useState(true);
  const [session, setSession] = useState<CognitoUserSession | null>(null);
  const [user, setUser] = useState<UserInfo | null>(null);
  const [householdId, setHouseholdId] = useState<string | null>(null);

  useEffect(() => {
    loadSession();
  }, []);

  async function loadSession() {
    try {
      const existingSession = await getCurrentSession();
      if (existingSession) {
        setSession(existingSession);
        const userInfo = await loadUserInfo();
        if (userInfo) await ensureHousehold(userInfo);
      }
    } finally {
      setIsLoading(false);
    }
  }

  async function loadUserInfo(): Promise<UserInfo | null> {
    const cognitoUser = getCurrentUser();
    if (!cognitoUser) return null;

    // Need an active session to get attributes
    await new Promise<void>((resolve) => {
      cognitoUser.getSession((err: Error | null) => {
        resolve();
      });
    });

    const attrs = await getUserAttributes(cognitoUser);
    const info: UserInfo = {
      userId: attrs["sub"] || "",
      email: attrs["email"] || "",
      firstName: attrs["given_name"] || "",
      lastName: attrs["family_name"] || "",
      householdId: attrs["custom:householdId"] || undefined,
    };
    setUser(info);
    return info;
  }

  async function ensureHousehold(userInfo: UserInfo) {
    if (userInfo.householdId) {
      setHouseholdId(userInfo.householdId);
      return;
    }
    // Check if user already has a household
    try {
      const households = await apiGet<any[]>("/households");
      if (households.length > 0) {
        setHouseholdId(households[0].householdId);
        return;
      }
    } catch {
      // Fall through to create
    }
    // Auto-create household for new users
    try {
      const household = await apiPost("/households", {
        name: `${userInfo.firstName}'s Family`,
      }, false);
      setHouseholdId(household.householdId);
    } catch {
      // Will retry on next load
    }
  }

  async function handleSignUp(params: SignUpParams) {
    await cognitoSignUp(params);
  }

  async function handleConfirm(email: string, code: string) {
    await cognitoConfirm(email, code);
  }

  async function handleSignIn(email: string, password: string) {
    const newSession = await cognitoSignIn(email, password);
    setSession(newSession);
    const userInfo = await loadUserInfo();
    if (userInfo) await ensureHousehold(userInfo);
  }

  function handleSignOut() {
    cognitoSignOut();
    setSession(null);
    setUser(null);
    setHouseholdId(null);
  }

  return (
    <AuthContext.Provider
      value={{
        isLoading,
        isAuthenticated: !!session,
        user,
        session,
        householdId,
        userId: user?.userId || null,
        signUp: handleSignUp,
        confirmSignUp: handleConfirm,
        signIn: handleSignIn,
        signOut: handleSignOut,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
