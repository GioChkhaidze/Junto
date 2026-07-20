import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout";
import { AppErrorBoundary } from "./components/system/AppErrorBoundary";
import { LoadingSkeleton } from "./components/ui";

const HomePage = lazy(() => import("./features/home/HomePage").then((module) => ({ default: module.HomePage })));
const CreateRoomPage = lazy(() =>
  import("./features/host/create/CreateRoomPage").then((module) => ({ default: module.CreateRoomPage })),
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

function RouteLoading() {
  return (
    <AppShell>
      <LoadingSkeleton count={6} label="Loading page" />
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
