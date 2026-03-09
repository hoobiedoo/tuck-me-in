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
  needsHousehold: boolean;
  user: UserInfo | null;
  session: CognitoUserSession | null;
  householdId: string | null;
  userId: string | null;
  userRole: string | null;
  signUp: (params: SignUpParams) => Promise<void>;
  confirmSignUp: (email: string, code: string) => Promise<void>;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => void;
  createHousehold: (name: string) => Promise<void>;
  joinHousehold: (inviteCode: string) => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [isLoading, setIsLoading] = useState(true);
  const [session, setSession] = useState<CognitoUserSession | null>(null);
  const [user, setUser] = useState<UserInfo | null>(null);
  const [householdId, setHouseholdId] = useState<string | null>(null);
  const [needsHousehold, setNeedsHousehold] = useState(false);
  const [userRole, setUserRole] = useState<string | null>(null);

  useEffect(() => {
    loadSession();
  }, []);

  async function loadSession() {
    try {
      const existingSession = await getCurrentSession();
      if (existingSession) {
        setSession(existingSession);
        const userInfo = await loadUserInfo();
        if (userInfo) await findHousehold(userInfo);
      }
    } finally {
      setIsLoading(false);
    }
  }

  async function loadUserInfo(): Promise<UserInfo | null> {
    const cognitoUser = getCurrentUser();
    if (!cognitoUser) return null;

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

  async function findHousehold(userInfo: UserInfo) {
    // Check if user already belongs to a household
    try {
      const households = await apiGet<any[]>("/households");
      if (households.length > 0) {
        const hid = households[0].householdId;
        setHouseholdId(hid);
        setNeedsHousehold(false);
        await ensureMemberRecord(userInfo, hid);
        return;
      }
    } catch {
      // Fall through
    }

    // No household found — user needs to create or join one
    setNeedsHousehold(true);
  }

  async function ensureMemberRecord(userInfo: UserInfo, hid: string) {
    try {
      const member = await apiPost(`/households/${hid}/members`, {
        userId: userInfo.userId,
        firstName: userInfo.firstName,
        lastName: userInfo.lastName,
        displayName: userInfo.firstName,
      });
      setUserRole(member.role || null);
    } catch {
      // Already exists or non-critical — try to get role
      try {
        const members = await apiGet<any[]>(`/households/${hid}/members`);
        const me = members.find((m: any) => m.userId === userInfo.userId);
        if (me) setUserRole(me.role || null);
      } catch {
        // Non-critical
      }
    }
  }

  async function handleCreateHousehold(name: string) {
    if (!user) return;
    const household = await apiPost("/households", { name }, false);
    const hid = household.householdId;
    setHouseholdId(hid);
    setNeedsHousehold(false);
    await ensureMemberRecord(user, hid);
  }

  async function handleJoinHousehold(inviteCode: string) {
    if (!user) return;
    const household = await apiPost("/households/join", {
      inviteCode,
      userId: user.userId,
      firstName: user.firstName,
      lastName: user.lastName,
      displayName: user.firstName,
    });
    const hid = household.householdId;
    setHouseholdId(hid);
    setNeedsHousehold(false);
    setUserRole("member");
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
    if (userInfo) await findHousehold(userInfo);
  }

  function handleSignOut() {
    cognitoSignOut();
    setSession(null);
    setUser(null);
    setHouseholdId(null);
    setNeedsHousehold(false);
    setUserRole(null);
  }

  return (
    <AuthContext.Provider
      value={{
        isLoading,
        isAuthenticated: !!session,
        needsHousehold,
        user,
        session,
        householdId,
        userId: user?.userId || null,
        userRole,
        signUp: handleSignUp,
        confirmSignUp: handleConfirm,
        signIn: handleSignIn,
        signOut: handleSignOut,
        createHousehold: handleCreateHousehold,
        joinHousehold: handleJoinHousehold,
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
