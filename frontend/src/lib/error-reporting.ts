// =============================================================================
// 错误报告服务 —— 捕获和上报前端错误
// =============================================================================

import { runtimeConfig } from "../runtime";

export interface ErrorReport {
  timestamp: string;
  errorType: "uncaught" | "unhandledrejection" | "react" | "api" | "manual";
  message: string;
  stack?: string;
  context: {
    url: string;
    userAgent: string;
    threadId?: string;
    runId?: string;
    requestId?: string;
    appVersion?: string;
  };
  metadata?: Record<string, unknown>;
}

class ErrorReportingService {
  private context: {
    threadId?: string;
    runId?: string;
    requestId?: string;
  } = {};

  setContext(context: { threadId?: string; runId?: string; requestId?: string }) {
    this.context = { ...this.context, ...context };
  }

  clearContext() {
    this.context = {};
  }

  async report(error: ErrorReport): Promise<void> {
    try {
      const config = runtimeConfig();
      const url = config.productApiOrigin + "/api/errors";
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (config.bearerToken) {
        headers["Authorization"] = "Bearer " + config.bearerToken;
      }
      
      const response = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(error),
      });

      if (!response.ok) {
        console.error("Failed to report error:", response.statusText);
      }
    } catch (reportError) {
      console.error("Error reporting failed:", reportError);
    }
  }

  createReport(
    errorType: ErrorReport["errorType"],
    error: Error | string,
    metadata?: Record<string, unknown>
  ): ErrorReport {
    const config = runtimeConfig();
    const errorObj = typeof error === "string" ? new Error(error) : error;

    return {
      timestamp: new Date().toISOString(),
      errorType,
      message: errorObj.message,
      stack: errorObj.stack,
      context: {
        url: window.location.href,
        userAgent: navigator.userAgent,
        threadId: this.context.threadId,
        runId: this.context.runId,
        requestId: this.context.requestId,
        appVersion: config.mode,
      },
      metadata,
    };
  }

  initialize() {
    window.addEventListener("error", (event) => {
      const report = this.createReport("uncaught", event.error || event.message, {
        filename: event.filename,
        lineno: event.lineno,
        colno: event.colno,
      });
      void this.report(report);
    });

    window.addEventListener("unhandledrejection", (event) => {
      const report = this.createReport("unhandledrejection", event.reason, {
        promise: String(event.promise),
      });
      void this.report(report);
    });

    console.log("Error reporting service initialized");
  }
}

export const errorReporting = new ErrorReportingService();
