import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "@xyflow/react/dist/style.css";
import "./styles.css";
const client = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchInterval: 5000, refetchOnWindowFocus: true },
  },
});
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
