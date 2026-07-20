import { Component, type ErrorInfo, type ReactNode } from "react";
import { AppShell, ContentActions, ContentStack } from "../layout";
import { Button, InlineNotice } from "../ui";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    if (import.meta.env.DEV) console.error(error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <AppShell>
        <ContentStack>
          <h1>Junto couldn’t open this page</h1>
          <InlineNotice tone="error" title="Something went wrong">
            Refresh the page and try again. Your saved room and responses are kept on the server.
          </InlineNotice>
          <ContentActions>
            <Button onClick={() => window.location.reload()}>Refresh page</Button>
            <Button variant="secondary" onClick={() => window.location.assign("/")}>
              Return home
            </Button>
          </ContentActions>
        </ContentStack>
      </AppShell>
    );
  }
}
