import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./index.css";
import { applyTheme, getInitialTheme } from "./theme/applyTheme";
import AuthProvider from "./auth/AuthProvider.jsx";

applyTheme(getInitialTheme());
createRoot(document.getElementById("root")).render(
  <StrictMode>
    <AuthProvider>
      <App />
    </AuthProvider>
  </StrictMode>
);
