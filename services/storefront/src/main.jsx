import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";

// Day 8, Step 1 -- storefront light tokens. Its own sheet, no Plex (UIUX v2 SS1).
import "./styles/tokens.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
