import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./index.css";
import App from "./App.tsx";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Notice } from "@/components/ui/notice";
import { TooltipProvider } from "@/components/ui/tooltip";
import { connect } from "@/lib/host";
import { start } from "@/lib/store";

const root = createRoot(document.getElementById("root")!);

try {
  await connect();
  start();
  root.render(
    <StrictMode>
      <TooltipProvider>
        <ErrorBoundary what="The app" className="m-4">
          <App />
        </ErrorBoundary>
      </TooltipProvider>
    </StrictMode>,
  );
} catch (cause) {
  root.render(
    <Notice title="Could not connect to the host." className="m-4">
      {cause instanceof Error ? cause.message : String(cause)}
    </Notice>,
  );
}
