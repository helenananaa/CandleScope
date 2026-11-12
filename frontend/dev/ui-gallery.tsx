// Dev-only gallery of the UI primitives in both themes: http://127.0.0.1:15173/ui-gallery.html
// English only on purpose; it is a reference for building surfaces, not a product page.
import "../src/styles/layers.css";
import "../src/styles/fonts.js";
import "../src/index.css";
import "./ui-gallery.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import Gallery from "./Gallery.js";

const root = document.getElementById("root");
if (root) createRoot(root).render(<StrictMode><Gallery /></StrictMode>);
