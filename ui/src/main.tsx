import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { useStore } from "./store";
import "./styles/tokens.css";
import "./styles/app.css";

document.documentElement.dataset.theme = useStore.getState().theme;

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
