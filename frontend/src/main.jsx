import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { MotionConfig } from "framer-motion";
import App from "./App.jsx";
import { initTheme } from "./theme.js";
import "./styles/index.css";

initTheme();

// reducedMotion "user": with the system's reduce-motion setting on, framer-motion drops movement and keeps fades, as
// the stylesheet does for CSS animation.
ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <MotionConfig reducedMotion="user">
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </MotionConfig>
  </React.StrictMode>
);
