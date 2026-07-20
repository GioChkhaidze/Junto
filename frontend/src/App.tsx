import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AppShell, HeaderLink } from "./components/layout";
import { AppErrorBoundary } from "./components/system/AppErrorBoundary";
import { LoadingSkeleton } from "./components/ui";
import { HomePage } from "./features/home/HomePage";
import styles from "./App.module.css";

const CreateRoomPage = lazy(() =>
  import("./features/host/create/CreateRoomPage").then((module) => ({ default: module.CreateRoomPage })),
);
const ActivityHistoryPage = lazy(() =>
  import("./features/host/history/ActivityHistoryPage").then((module) => ({ default: module.ActivityHistoryPage })),
);
const HostRoomPage = lazy(() =>
  import("./features/host/room/HostRoomPage").then((module) => ({ default: module.HostRoomPage })),
);
const JoinRoomPage = lazy(() =>
  import("./features/participant/join/JoinRoomPage").then((module) => ({ default: module.JoinRoomPage })),
);
const ParticipantRoomPage = lazy(() =>
  import("./features/participant/room/ParticipantRoomPage").then((module) => ({ default: module.ParticipantRoomPage })),
);
const NotFoundPage = lazy(() =>
  import("./features/not-found/NotFoundPage").then((module) => ({ default: module.NotFoundPage })),
);

export function RouteLoading() {
  const { pathname } = useLocation();
  const hostRoom = pathname.startsWith("/host/");
  const variant =
    pathname === "/create"
      ? "authoring"
      : pathname === "/activities" || hostRoom
        ? "host"
        : pathname.startsWith("/room/")
          ? "default"
          : "public";
  const context =
    pathname === "/create"
      ? "Create an activity"
      : pathname === "/activities"
        ? "Activities"
        : pathname.startsWith("/join/")
          ? "Join activity"
          : undefined;
  const actions =
    pathname === "/create" ? (
      <HeaderLink to="/activities">Activities</HeaderLink>
    ) : pathname === "/activities" ? (
      <HeaderLink to="/create">Create activity</HeaderLink>
    ) : undefined;

  return (
    <AppShell variant={variant} context={context} actions={actions}>
      {hostRoom ? (
        <div className={styles.hostLoadingPanel}>
          <LoadingSkeleton count={8} label="Loading page" />
        </div>
      ) : (
        <LoadingSkeleton count={6} label="Loading page" />
      )}
    </AppShell>
  );
}

export function App() {
  return (
    <AppErrorBoundary>
      <Suspense fallback={<RouteLoading />}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/create" element={<CreateRoomPage />} />
          <Route path="/activities" element={<ActivityHistoryPage />} />
          <Route path="/host/:roomId" element={<HostRoomPage />} />
          <Route path="/join/:joinCode" element={<JoinRoomPage />} />
          <Route path="/join" element={<Navigate to="/" replace />} />
          <Route path="/room/:roomId" element={<ParticipantRoomPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </Suspense>
    </AppErrorBoundary>
  );
}
