import React from "react"
import ReactDOM from "react-dom/client"
import { BrowserRouter } from "react-router-dom"

import App from "./App"
import "./index.css"

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter basename={(import.meta.env.BASE_URL || "/app/").replace(/\/$/, "")}>
      <App />
    </BrowserRouter>
  </React.StrictMode>
)

if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    const baseUrl = import.meta.env.BASE_URL

    navigator.serviceWorker.register(`${baseUrl}sw.js`, { scope: baseUrl }).catch((error) => {
      console.warn("Runforfan service worker registration failed", error)
    })
  })
}
