import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";

// Day 8, Step 1 -- the design-token layer. tokens (colour) before type
// (fonts + scale) before base (reset + focus + reduced motion).
import "./styles/tokens.css";
import "./styles/type.css";
import "./styles/base.css";
import "./styles/metrics.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
