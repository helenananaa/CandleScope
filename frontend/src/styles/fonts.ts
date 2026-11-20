// Web fonts shared by every entry page. Browsers download a face only when text uses it.
// Interface font (DESIGN.md): IBM Plex Sans. CJK text uses system fonts via --font-cjk.
// The per-weight files declare every subset (latin, latin-ext, cyrillic, cyrillic-ext, greek,
// vietnamese) with its unicode-range, so a page fetches only the subsets its text needs. The
// single-subset files have no unicode-range: with only latin and cyrillic loaded, letters such
// as Hungarian ő / ű fell through to the CJK font and drew with a detached accent.
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-sans/700.css";
// Inter remains registered for chart text drawings: their default face, and saved
// drawings, name it explicitly. Changing drawing text is a separate decision.
import "@fontsource/inter/cyrillic-400.css";
import "@fontsource/inter/cyrillic-700.css";
import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-700.css";
import "@fontsource/jetbrains-mono/latin-400.css";
import "@fontsource/jetbrains-mono/latin-500.css";
