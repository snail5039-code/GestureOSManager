import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./index.css";
import { applyTheme, getInitialTheme } from "./theme/applyTheme";

applyTheme(getInitialTheme());
createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>
);
