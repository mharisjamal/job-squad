import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./hooks/useAuth";
import { PageSpinner } from "./components/ui/Spinner";
import Auth from "./pages/Auth";
import AuthCallback from "./pages/AuthCallback";
import Groups from "./pages/Groups";
import Dashboard from "./pages/Dashboard";
import Companies from "./pages/Companies";
import CompanyDetail from "./pages/CompanyDetail";
import Board from "./pages/Board";
import Portals from "./pages/Portals";
import Activity from "./pages/Activity";
import { GroupShell } from "./components/layout/Shell";

export default function App() {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <PageSpinner label="Signing you in" />
      </div>
    );
  }

  if (status === "anon") {
    return (
      <Routes>
        <Route path="/auth" element={<Auth />} />
        <Route path="/auth/callback" element={<AuthCallback />} />
        <Route path="*" element={<Navigate to="/auth" replace state={{ from: location }} />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route path="/auth" element={<Navigate to="/" replace />} />
      {/* Stays mounted when adopting an OAuth token flips the app to authed. */}
      <Route path="/auth/callback" element={<AuthCallback />} />
      <Route path="/" element={<Groups />} />
      <Route path="/g/:gid" element={<GroupShell />}>
        <Route index element={<Dashboard />} />
        <Route path="companies" element={<Companies />} />
        <Route path="companies/:cid" element={<CompanyDetail />} />
        <Route path="board" element={<Board />} />
        <Route path="portals" element={<Portals />} />
        <Route path="activity" element={<Activity />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
