import { Component, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";

/**
 * Catches a failure rendering `children`, so the rest of the app stays up and says what broke rather than going blank.
 * Try again renders them afresh.
 */
export class ErrorBoundary extends Component<
  { what: string; className?: string; children: ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: unknown) {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  render() {
    if (!this.state.error) {
      return this.props.children;
    }
    return (
      <div className={this.props.className}>
        <Notice title={`${this.props.what} hit a problem.`}>
          {this.state.error.message}
          <Button
            variant="secondary"
            size="sm"
            onClick={() => this.setState({ error: null })}
            className="mt-2 flex"
          >
            Try again
          </Button>
        </Notice>
      </div>
    );
  }
}
