// main.tsx
//
// Standard Vite/React entry point: mounts `App` into `index.html`'s
// `#root`. Contains no application logic of its own -- see `App.tsx`.
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
