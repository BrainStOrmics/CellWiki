import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./App";
import { LanguageProvider } from "./i18n";
import { initializeRuntime } from "./runtime";
import { errorReporting } from "./lib/error-reporting";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 2_000,
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
});

async function bootstrap() {
  // Resolve the random sidecar origin and launch token before any Product request.
  await initializeRuntime();
  
  // Initialize global error handlers for error reporting
  errorReporting.initialize();
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <LanguageProvider><App /></LanguageProvider>
      </QueryClientProvider>
    </StrictMode>,
  );
}

void bootstrap();
