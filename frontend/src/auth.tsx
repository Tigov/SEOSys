// Who is signed in. Loaded once from /api/auth/me and refreshed after anything that changes it.
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { ApiError, SIGNED_OUT, api, post, setCsrf, type Me } from "./api";

interface Auth {
  me: Me | null;
  ready: boolean;
  refresh: () => Promise<Me | null>;
  logout: () => Promise<void>;
}

const AuthCtx = createContext<Auth>({ me: null, ready: false, refresh: async () => null, logout: async () => {} });
export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const next = await api<Me>("/api/auth/me");
      setCsrf(next.csrf_token);
      setMe(next);
      return next;
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 401) throw e;
      setCsrf("");
      setMe(null);
      return null;
    } finally {
      setReady(true);
    }
  }, []);

  const logout = useCallback(async () => {
    await post("/api/auth/logout");
    setCsrf("");
    setMe(null);
    window.location.hash = "#/";
  }, []);

  useEffect(() => {
    refresh().catch(() => setReady(true));
    const onSignedOut = () => { setCsrf(""); setMe(null); };
    window.addEventListener(SIGNED_OUT, onSignedOut);
    return () => window.removeEventListener(SIGNED_OUT, onSignedOut);
  }, [refresh]);

  return <AuthCtx.Provider value={{ me, ready, refresh, logout }}>{children}</AuthCtx.Provider>;
}

// Where someone lands after signing in: the agency console, their client, or the packages page.
export function homeFor(me: Me): string {
  if (me.user.is_admin) return "#/admin";
  if (me.memberships.length) return `#/clients/${me.memberships[0].client_id}/overview`;
  return "#/packages";
}
