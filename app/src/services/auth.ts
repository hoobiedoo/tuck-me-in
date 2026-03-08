import {
  CognitoUserPool,
  CognitoUser,
  AuthenticationDetails,
  CognitoUserAttribute,
  CognitoUserSession,
} from "amazon-cognito-identity-js";
import { AWS_CONFIG } from "../config/aws";

const userPool = new CognitoUserPool({
  UserPoolId: AWS_CONFIG.cognito.userPoolId,
  ClientId: AWS_CONFIG.cognito.userPoolClientId,
});

export interface SignUpParams {
  email: string;
  password: string;
  firstName: string;
  lastName: string;
}

export function signUp({ email, password, firstName, lastName }: SignUpParams): Promise<CognitoUser> {
  const attributes = [
    new CognitoUserAttribute({ Name: "email", Value: email }),
    new CognitoUserAttribute({ Name: "given_name", Value: firstName }),
    new CognitoUserAttribute({ Name: "family_name", Value: lastName }),
  ];

  return new Promise((resolve, reject) => {
    userPool.signUp(email, password, attributes, [], (err, result) => {
      if (err) return reject(err);
      resolve(result!.user);
    });
  });
}

export function confirmSignUp(email: string, code: string): Promise<string> {
  const user = new CognitoUser({ Username: email, Pool: userPool });
  return new Promise((resolve, reject) => {
    user.confirmRegistration(code, true, (err, result) => {
      if (err) return reject(err);
      resolve(result);
    });
  });
}

export function signIn(email: string, password: string): Promise<CognitoUserSession> {
  const user = new CognitoUser({ Username: email, Pool: userPool });
  const authDetails = new AuthenticationDetails({ Username: email, Password: password });

  return new Promise((resolve, reject) => {
    user.authenticateUser(authDetails, {
      onSuccess: (session) => resolve(session),
      onFailure: (err) => reject(err),
    });
  });
}

export function signOut(): void {
  const user = userPool.getCurrentUser();
  if (user) user.signOut();
}

export function getCurrentSession(): Promise<CognitoUserSession | null> {
  return new Promise((resolve) => {
    const user = userPool.getCurrentUser();
    if (!user) return resolve(null);

    user.getSession((err: Error | null, session: CognitoUserSession | null) => {
      if (err || !session || !session.isValid()) return resolve(null);
      resolve(session);
    });
  });
}

export function getCurrentUser(): CognitoUser | null {
  return userPool.getCurrentUser();
}

export function getIdToken(session: CognitoUserSession): string {
  return session.getIdToken().getJwtToken();
}

export function getUserAttributes(user: CognitoUser): Promise<Record<string, string>> {
  return new Promise((resolve, reject) => {
    user.getUserAttributes((err, attrs) => {
      if (err) return reject(err);
      const map: Record<string, string> = {};
      for (const attr of attrs || []) {
        map[attr.getName()] = attr.getValue();
      }
      resolve(map);
    });
  });
}
