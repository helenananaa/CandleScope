export type SettingsModalStylesProps = Record<string, never>;

export default function SettingsModalStyles(props: SettingsModalStylesProps) {
  void props;
  return (
    <style>{`

/* ═══════════════════════════════════════════════════════════
   Settings Panel — Full-page sidebar + content layout
   Inspired by VS Code / Discord settings
   ═══════════════════════════════════════════════════════════ */

.st-overlay {
  position: fixed;
  inset: 0;
  background: var(--backdrop);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: var(--z-modal);
  backdrop-filter: blur(6px);
  animation: st-fade-in 0.18s ease-out;
}

@keyframes st-fade-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}

@keyframes st-slide-up {
  from { opacity: 0; transform: translateY(12px) scale(0.98); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}

/* Appearance-only dialog (pages without the live runtime) */
.st-panel.st-panel-single {
  width: min(640px, 92vw);
}

.st-overlay[hidden] {
  display: none;
}

.st-panel:focus {
  outline: none;
}

.st-panel {
  display: flex;
  width: min(960px, 92vw);
  height: min(680px, 88vh);
  background: var(--bg-secondary);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow:
    var(--shadow-lg),
    0 0 0 1px color-mix(in srgb, var(--text-primary) 4%, transparent) inset;
  animation: st-slide-up 0.22s ease-out;
}

/* ── Sidebar ────────────────────────────────────────────── */
.st-sidebar {
  width: 200px;
  min-width: 200px;
  background: var(--bg-primary);
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  padding: 0;
}

.st-sidebar-title {
  padding: 24px 20px 16px;
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 0.02em;
}

.st-sidebar-nav {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 8px;
}

.st-nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13.5px;
  font-weight: 500;
  cursor: pointer;
  border-radius: var(--radius-md);
  transition: all 0.15s ease;
  text-align: left;
}

.st-nav-item:hover {
  background: color-mix(in srgb, var(--text-primary) 5%, transparent);
  color: var(--text-primary);
}

.st-nav-item.active {
  background: color-mix(in srgb, var(--accent-blue) 12%, transparent);
  color: var(--text-accent);
}

.st-nav-item:focus-visible {
  outline: 2px solid var(--accent-blue);
  outline-offset: -2px;
}

.st-nav-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  flex-shrink: 0;
  color: var(--text-muted);
}

.st-nav-item:hover .st-nav-icon,
.st-nav-item.active .st-nav-icon {
  color: inherit;
}

.st-content-title-icon {
  display: inline-flex;
  color: var(--text-secondary);
}

.st-sidebar-footer {
  padding: 12px;
  border-top: 1px solid var(--border-color);
}

.st-btn-close {
  width: 100%;
  justify-content: center;
}

/* ── Content area ───────────────────────────────────────── */
.st-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.st-content-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 28px 16px;
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.st-content-title {
  font-size: 17px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.st-close-x {
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 18px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: var(--radius-control);
  transition: all 0.15s;
}
.st-close-x:hover {
  background: color-mix(in srgb, var(--text-primary) 6%, transparent);
  color: var(--text-primary);
}

.st-content-body {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px 32px;
}

/* Custom scrollbar */
.st-content-body::-webkit-scrollbar {
  width: 6px;
}
.st-content-body::-webkit-scrollbar-track {
  background: transparent;
}
.st-content-body::-webkit-scrollbar-thumb {
  background: color-mix(in srgb, var(--text-primary) 10%, transparent);
  border-radius: var(--radius-xs);
}
.st-content-body::-webkit-scrollbar-thumb:hover {
  background: color-mix(in srgb, var(--text-primary) 18%, transparent);
}

/* ── Groups ─────────────────────────────────────────────── */
.st-group {
  margin-bottom: 28px;
  padding-bottom: 24px;
  border-bottom: 1px solid color-mix(in srgb, var(--text-primary) 5%, transparent);
}
.st-group:last-child {
  border-bottom: none;
  margin-bottom: 0;
}

.st-group-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.st-group-desc {
  font-size: var(--font-size-md);
  line-height: 1.6;
  color: var(--text-secondary);
  margin-bottom: 14px;
}

html[lang="ru"] .st-group-title,
html[lang="ru"] .st-group-desc,
html[lang="ru"] .st-theme-label,
html[lang="ru"] .st-select,
html[lang="ru"] .st-preset-btn {
  overflow-wrap: break-word;
}

/* ── Theme cards ────────────────────────────────────────── */
.st-theme-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}

.st-appearance-theme-grid {
  grid-template-columns: repeat(4, 1fr);
}

.st-theme-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 16px 12px;
  border: 1px solid var(--border-color);
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: all 0.18s ease;
}

.st-theme-card:hover {
  border-color: color-mix(in srgb, var(--text-primary) 15%, transparent);
  background: color-mix(in srgb, var(--text-primary) 4%, transparent);
  transform: translateY(-1px);
}

.st-theme-card.active {
  border-color: var(--accent-blue);
  background: color-mix(in srgb, var(--accent-blue) 10%, transparent);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent-blue) 30%, transparent);
}

.st-theme-icon {
  display: inline-flex;
  color: var(--text-secondary);
}

.st-theme-card.active .st-theme-icon {
  color: var(--text-accent);
}

.st-theme-label {
  font-size: var(--font-size-md);
  font-weight: 500;
}

/* ── Preset row ─────────────────────────────────────────── */
.st-preset-row {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
}

.st-preset-btn {
  flex: 1;
  padding: 10px 14px;
  border: 1px solid var(--border-color);
  background: var(--bg-tertiary);
  border-radius: var(--radius-md);
  cursor: pointer;
  display: flex;
  gap: 12px;
  justify-content: center;
  align-items: center;
  font-size: 13px;
  transition: all 0.15s;
}

.st-preset-btn.active {
  border-color: var(--accent-blue);
  background: color-mix(in srgb, var(--accent-blue) 10%, transparent);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent-blue) 30%, transparent);
}

.st-preset-btn:hover {
  border-color: color-mix(in srgb, var(--text-primary) 15%, transparent);
  background: color-mix(in srgb, var(--text-primary) 4%, transparent);
}

/* ── Colors ─────────────────────────────────────────────── */
.st-custom-colors {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.st-color-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  color: var(--text-secondary);
}

.st-color-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.st-color-code {
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: var(--font-size-sm);
  color: var(--text-muted);
  background: color-mix(in srgb, var(--text-primary) 4%, transparent);
  padding: 3px 8px;
  border-radius: var(--radius-sm);
}

input[type="color"] {
  border: none;
  width: 32px;
  height: 32px;
  cursor: pointer;
  background: none;
  border-radius: var(--radius-control);
}

.st-field {
  display: grid;
  gap: 6px;
  margin-top: 12px;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
}

/* ── Select ─────────────────────────────────────────────── */
.st-select {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid var(--border-color);
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border-radius: var(--radius-md);
  cursor: pointer;
  outline: none;
  font-size: 13px;
  transition: border-color 0.15s;
}
.st-select:focus {
  border-color: var(--accent-blue);
}

.st-select-inline {
  width: auto;
  min-width: 140px;
}

/* ── Input ──────────────────────────────────────────────── */
.st-input {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid var(--border-color);
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border-radius: var(--radius-md);
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 13px;
  outline: none;
  box-sizing: border-box;
  transition: border-color 0.15s;
}
.st-input:focus {
  border-color: var(--accent-blue);
}
.st-input::placeholder {
  color: var(--text-muted);
  font-family: inherit;
}

/* ── Info box ───────────────────────────────────────────── */
.st-info-box {
  margin-top: 10px;
  padding: 10px 14px;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--accent-blue) 6%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent-blue) 15%, transparent);
  font-size: var(--font-size-md);
  color: var(--text-secondary);
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  line-height: 1.5;
}

.st-info-warn {
  background: color-mix(in srgb, var(--color-warning) 6%, transparent);
  border-color: color-mix(in srgb, var(--color-warning) 20%, transparent);
  color: var(--text-warning);
}

.st-info-label {
  font-weight: 600;
}

.st-info-value {
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: var(--font-size-sm);
  background: color-mix(in srgb, var(--text-primary) 6%, transparent);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
}

/* ── Buttons ────────────────────────────────────────────── */
.st-actions-row {
  display: flex;
  gap: 10px;
  margin-top: 14px;
}

.st-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 9px 16px;
  border-radius: var(--radius-md);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.18s ease;
  flex: 1;
}

a.st-btn {
  text-decoration: none;
}

.st-content-body section > a.st-btn:first-child {
  margin-bottom: 16px;
}

.st-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.st-btn-primary {
  background: var(--accent-solid);
  color: white;
  border-color: var(--accent-blue);
}
.st-btn-primary:hover:not(:disabled) {
  opacity: 0.9;
  transform: translateY(-1px);
}

.st-btn-secondary {
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border-color: var(--border-color);
}
.st-btn-secondary:hover:not(:disabled) {
  border-color: var(--accent-blue);
  color: var(--text-accent);
}

.st-btn-warn {
  background: color-mix(in srgb, var(--color-warning) 10%, transparent);
  color: var(--text-warning);
  border-color: color-mix(in srgb, var(--color-warning) 30%, transparent);
}
.st-btn-warn:hover:not(:disabled) {
  background: color-mix(in srgb, var(--color-warning) 16%, transparent);
  border-color: color-mix(in srgb, var(--color-warning) 50%, transparent);
}

.st-btn-accent {
  background: color-mix(in srgb, var(--accent-blue) 10%, transparent);
  color: var(--text-accent);
  border-color: color-mix(in srgb, var(--accent-blue) 30%, transparent);
}
.st-btn-accent:hover:not(:disabled) {
  background: color-mix(in srgb, var(--accent-blue) 16%, transparent);
  border-color: color-mix(in srgb, var(--accent-blue) 50%, transparent);
}

/* ── Preset cards (storage strategy) ────────────────────── */
.st-preset-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}

.st-preset-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 14px 8px 12px;
  border: 1px solid var(--border-color);
  background: var(--bg-tertiary);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: all 0.18s ease;
}

.st-preset-card:hover {
  border-color: color-mix(in srgb, var(--text-primary) 15%, transparent);
  transform: translateY(-1px);
}

.st-preset-card.active {
  border-color: var(--accent-blue);
  background: color-mix(in srgb, var(--accent-blue) 8%, transparent);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent-blue) 25%, transparent);
}

.st-preset-level {
  display: inline-flex;
  align-items: flex-end;
  gap: 2px;
  height: 16px;
}

.st-preset-level > span {
  width: 4px;
  border-radius: var(--radius-xs);
  background: var(--border-color);
}

.st-preset-level > span:nth-child(1) { height: 25%; }
.st-preset-level > span:nth-child(2) { height: 50%; }
.st-preset-level > span:nth-child(3) { height: 75%; }
.st-preset-level > span:nth-child(4) { height: 100%; }

.st-preset-level > span.on {
  background: var(--text-secondary);
}

.st-preset-card.active .st-preset-level > span.on {
  background: var(--accent-blue);
}

.st-preset-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.st-preset-desc {
  font-size: var(--font-size-xs);
  color: var(--text-muted);
  text-align: center;
  line-height: 1.4;
}

/* ── Badges (memory / db indicators) ────────────────────── */
.st-badge {
  display: inline-block;
  font-size: var(--font-size-2xs);
  font-weight: 600;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  margin-left: 8px;
  letter-spacing: 0.03em;
  vertical-align: middle;
}

.st-badge-memory {
  background: color-mix(in srgb, var(--accent-purple) 15%, transparent);
  color: var(--text-purple);
  border: 1px solid color-mix(in srgb, var(--accent-purple) 30%, transparent);
}

.st-badge-db {
  background: color-mix(in srgb, var(--accent-blue) 12%, transparent);
  color: var(--text-accent);
  border: 1px solid color-mix(in srgb, var(--accent-blue) 25%, transparent);
}

[data-theme='light'] .st-btn-accent {
  background: var(--accent-solid);
  color: var(--text-on-accent);
  border-color: var(--accent-solid);
}

[data-theme='light'] .st-btn-accent:hover:not(:disabled) {
  background: var(--accent-solid-hover);
  border-color: var(--accent-solid-hover);
}

/* ── Ephemeral cache option cards ───────────────────────── */
.st-ephemeral-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}

.st-ephemeral-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 12px 8px 10px;
  border: 1px solid var(--border-color);
  background: var(--bg-tertiary);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.18s ease;
}

.st-ephemeral-card:hover {
  border-color: color-mix(in srgb, var(--accent-purple) 35%, transparent);
  transform: translateY(-1px);
}

.st-ephemeral-card.active {
  border-color: var(--accent-purple);
  background: color-mix(in srgb, var(--accent-purple) 8%, transparent);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent-purple) 20%, transparent);
}

.st-ephemeral-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.st-ephemeral-desc {
  font-size: var(--font-size-xs);
  color: var(--text-muted);
}

/* ── Ephemeral summary stats ────────────────────────────── */
.st-ephemeral-summary {
  display: flex;
  gap: 18px;
  padding: 10px 14px;
  margin-top: 10px;
  background: color-mix(in srgb, var(--accent-purple) 5%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent-purple) 12%, transparent);
  border-radius: var(--radius-md);
  flex-wrap: wrap;
}

.st-ephemeral-stat {
  font-size: 12px;
  color: var(--text-secondary);
}

.st-ephemeral-stat strong {
  color: var(--text-primary);
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
}

/* ── Cache diagnostics ─────────────────────────────────── */
.st-gc-scope-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin: 12px 0 4px;
}

.st-gc-scope-card {
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid color-mix(in srgb, var(--text-primary) 7%, transparent);
  background: color-mix(in srgb, var(--text-primary) 2%, transparent);
  border-radius: var(--radius-md);
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.st-gc-scope-title,
.st-gc-scope-detail {
  font-size: var(--font-size-xs);
  color: var(--text-muted);
}

.st-gc-scope-status {
  color: var(--text-primary);
  font-size: 13px;
}

.st-diagnostics-section {
  margin-top: 16px;
}

.st-diagnostics-heading-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.st-diagnostics-heading {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary);
  margin-bottom: 0;
}

.st-diagnostics-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.st-diagnostics-card {
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  background: var(--bg-tertiary);
  border-radius: var(--radius-md);
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.st-diagnostics-label,
.st-diagnostics-detail {
  font-size: var(--font-size-xs);
  color: var(--text-muted);
}

.st-diagnostics-value {
  color: var(--text-primary);
  font-size: 14px;
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  overflow-wrap: anywhere;
}

.st-diagnostics-list {
  margin-top: 8px;
  border: 1px solid color-mix(in srgb, var(--text-primary) 5%, transparent);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.st-diagnostics-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  padding: 7px 10px;
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
  background: color-mix(in srgb, var(--text-primary) 2%, transparent);
}

.st-diagnostics-row-wide {
  grid-template-columns: minmax(0, 1fr) auto auto;
}

.st-diagnostics-row-storage {
  grid-template-columns: minmax(0, 1fr) auto auto auto;
}

.st-diagnostics-row + .st-diagnostics-row {
  border-top: 1px solid color-mix(in srgb, var(--text-primary) 4%, transparent);
}

.st-diagnostics-row-key {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
}

.st-diagnostics-empty {
  margin-top: 8px;
  padding: 9px 10px;
  border: 1px dashed color-mix(in srgb, var(--text-primary) 8%, transparent);
  border-radius: var(--radius-md);
  font-size: 12px;
  color: var(--text-muted);
}

.st-diagnostics-plan {
  margin-top: 12px;
  padding: 12px;
  border: 1px solid color-mix(in srgb, var(--accent-blue) 14%, transparent);
  background: color-mix(in srgb, var(--accent-blue) 4%, transparent);
  border-radius: var(--radius-md);
}
.st-group-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.st-advanced-toggle {
  background: none;
  border: 1px solid var(--border-color);
  color: var(--text-muted);
  font-size: var(--font-size-sm);
  font-weight: 500;
  padding: 4px 12px;
  border-radius: var(--radius-control);
  cursor: pointer;
  transition: all 0.15s;
}

.st-advanced-toggle:hover {
  border-color: color-mix(in srgb, var(--text-primary) 15%, transparent);
  color: var(--text-secondary);
}

.st-advanced-toggle.active {
  border-color: var(--accent-blue);
  color: var(--text-accent);
  background: color-mix(in srgb, var(--accent-blue) 6%, transparent);
}

/* ── Tier table ─────────────────────────────────────────── */
.st-tier-table {
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.st-tier-header {
  display: grid;
  grid-template-columns: 2fr 1.5fr 1.2fr 1.2fr;
  gap: 8px;
  padding: 9px 14px;
  background: color-mix(in srgb, var(--text-primary) 2%, transparent);
  border-bottom: 1px solid var(--border-color);
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.st-tier-row {
  display: grid;
  grid-template-columns: 2fr 1.5fr 1.2fr 1.2fr;
  gap: 8px;
  padding: 10px 14px;
  align-items: center;
  background: var(--bg-tertiary);
  transition: background 0.12s;
}

.st-tier-row + .st-tier-row {
  border-top: 1px solid color-mix(in srgb, var(--text-primary) 4%, transparent);
}

.st-tier-row:hover {
  background: color-mix(in srgb, var(--text-primary) 2%, transparent);
}

.st-tier-col-name {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.st-tier-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.st-tier-desc {
  font-size: 11px;
  color: var(--text-muted);
}

.st-tier-col-limit {
  display: flex;
  align-items: center;
}

.st-tier-value {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
}

.st-tier-value.unlimited {
  color: var(--text-muted);
  font-size: 18px;
}

.st-tier-input {
  width: 100%;
  max-width: 110px;
  padding: 6px 10px;
  border: 1px solid var(--border-color);
  background: var(--bg-primary);
  color: var(--text-primary);
  border-radius: var(--radius-control);
  font-family: var(--font-mono, monospace);
  font-size: var(--font-size-md);
  outline: none;
  transition: border-color 0.15s;
}

.st-tier-input:focus {
  border-color: var(--accent-blue);
}

/* Hide number input arrows */
.st-tier-input::-webkit-outer-spin-button,
.st-tier-input::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
.st-tier-input[type=number] {
  -moz-appearance: textfield;
}

.st-tier-col-time,
.st-tier-col-size {
  font-size: 12px;
  color: var(--text-secondary);
}

.st-advanced-hint {
  margin-top: 12px;
  padding: 10px 14px;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--accent-blue) 5%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent-blue) 12%, transparent);
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
}

/* ── Inline setting ─────────────────────────────────────── */
.st-inline-setting {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.st-inline-setting label {
  font-size: 13px;
  color: var(--text-secondary);
  white-space: nowrap;
}

/* ── Exchange capability directory ─────────────────────── */
.st-exchange-directory {
  --ex-ink: var(--text-primary);
  --ex-label: color-mix(in srgb, var(--text-primary) 50%, var(--text-secondary));
  --ex-subtle: var(--text-secondary);
  --ex-card-bg: var(--surface-2);
  --ex-card-border: color-mix(in srgb, var(--border-subtle) 72%, var(--text-secondary));
  --ex-inset-bg: color-mix(in srgb, var(--surface-0) 70%, var(--surface-2));
  --ex-chip-bg: color-mix(in srgb, var(--accent-blue) 20%, transparent);
  --ex-chip-fg: var(--text-accent);
  --ex-ok: var(--text-success);
  --ex-ok-bg: color-mix(in srgb, var(--color-success) 14%, transparent);
  --ex-warn: var(--text-warning);
  --ex-warn-bg: color-mix(in srgb, var(--color-warning) 14%, transparent);
  --ex-pending: #fb923c; /* orange: distinct from warn, no global token */
  --ex-pending-bg: color-mix(in srgb, var(--ex-pending) 16%, transparent);
  --ex-fail: var(--text-danger);
  --ex-fail-bg: color-mix(in srgb, var(--color-danger) 14%, transparent);
  --ex-info: var(--text-accent);
  --ex-info-bg: color-mix(in srgb, var(--accent-blue) 16%, transparent);
  --ex-filter-active-bg: color-mix(in srgb, var(--accent-blue) 24%, transparent);
  --ex-filter-active-fg: var(--text-primary);
  --ex-refresh-bg: color-mix(in srgb, var(--accent-blue) 16%, transparent);
  --ex-refresh-fg: var(--text-accent);
}

/* Light theme uses opaque cards and solid accent buttons */
[data-theme='light'] .st-exchange-directory {
  --ex-card-bg: var(--surface-0);
  --ex-card-border: var(--border-subtle);
  --ex-inset-bg: var(--surface-1);
  --ex-chip-bg: color-mix(in srgb, var(--accent-blue) 8%, var(--surface-0));
  --ex-pending: #c2410c;
  --ex-filter-active-bg: var(--accent-solid);
  --ex-filter-active-fg: var(--text-on-accent);
  --ex-refresh-bg: var(--accent-solid);
  --ex-refresh-fg: var(--text-on-accent);
}

.st-exchange-directory .st-group-title-row {
  align-items: flex-start;
  gap: 12px;
}

.st-exchange-directory .st-group-title {
  margin-bottom: 4px;
  color: var(--ex-ink);
}

.st-exchange-directory .st-group-desc {
  margin-bottom: 0;
  max-width: 680px;
  color: var(--ex-subtle);
}

.st-exchange-refresh {
  flex-shrink: 0;
  padding: 7px 12px;
  border: 1px solid color-mix(in srgb, var(--accent-blue) 45%, var(--ex-card-border));
  border-radius: var(--radius-md);
  background: var(--ex-refresh-bg);
  color: var(--ex-refresh-fg);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: filter 0.15s ease, opacity 0.15s ease;
}

.st-exchange-refresh:hover:not(:disabled) {
  filter: brightness(1.08);
}

.st-exchange-refresh:disabled {
  opacity: 0.55;
  cursor: default;
}

.st-exchange-refresh:focus-visible,
.st-exchange-filter:focus-visible,
.st-exchange-card-head:focus-visible,
.st-exchange-test-button:focus-visible,
.st-exchange-search input:focus-visible {
  outline: 2px solid var(--accent-blue);
  outline-offset: 2px;
}

.st-exchange-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(118px, 1fr));
  gap: 10px;
  margin: 16px 0 14px;
}

.st-exchange-tech {
  grid-column: 1 / -1;
  color: var(--text-muted);
  font-size: var(--font-size-xs);
}

.st-exchange-tech summary {
  width: max-content;
  cursor: pointer;
}

.st-exchange-tech dl {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 4px 12px;
  margin: 8px 0 0;
}

.st-exchange-tech dd {
  margin: 0;
  color: var(--text-secondary);
  font-family: var(--font-mono);
}

.st-exchange-stat {
  min-width: 0;
  padding: 12px 14px;
  border: 1px solid var(--ex-card-border);
  border-radius: var(--radius-lg);
  background: var(--ex-card-bg);
  box-shadow: var(--shadow-sm);
}

.st-exchange-stat span,
.st-exchange-stat strong {
  display: block;
}

.st-exchange-stat span {
  margin-bottom: 6px;
  color: var(--ex-label);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  line-height: 1.35;
}

.st-exchange-stat strong {
  overflow: hidden;
  color: var(--ex-ink);
  font-family: var(--font-mono, monospace);
  font-size: 15px;
  font-weight: 700;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.st-exchange-toolbar {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 4px 0 14px;
}

.st-exchange-search {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: var(--ex-label);
  font-size: 12px;
  font-weight: 600;
}

.st-exchange-search input {
  min-width: 0;
  height: 38px;
  padding: 0 12px;
  border: 1px solid var(--ex-card-border);
  border-radius: var(--radius-md);
  outline: none;
  background: var(--ex-card-bg);
  color: var(--ex-ink);
  font-size: 13px;
}

.st-exchange-search input::placeholder {
  color: var(--ex-subtle);
}

.st-exchange-search input:focus {
  border-color: var(--accent-blue);
}

.st-exchange-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.st-exchange-filter {
  padding: 6px 11px;
  border: 1px solid var(--ex-card-border);
  border-radius: var(--radius-full);
  background: var(--ex-card-bg);
  color: var(--ex-label);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;
}

.st-exchange-filter:hover {
  border-color: color-mix(in srgb, var(--accent-blue) 55%, var(--ex-card-border));
  color: var(--ex-ink);
}

.st-exchange-filter.active {
  border-color: transparent;
  background: var(--ex-filter-active-bg);
  color: var(--ex-filter-active-fg);
}

.st-exchange-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.st-exchange-card {
  overflow: hidden;
  border: 1px solid var(--ex-card-border);
  border-radius: var(--radius-lg);
  background: var(--ex-card-bg);
  box-shadow: var(--shadow-sm);
}

.st-exchange-card.expanded {
  border-color: color-mix(in srgb, var(--accent-blue) 55%, var(--ex-card-border));
  box-shadow:
    0 0 0 1px color-mix(in srgb, var(--accent-blue) 28%, transparent),
    var(--shadow-md);
}

.st-exchange-card.current {
  box-shadow: inset 3px 0 0 var(--accent-blue);
}

.st-exchange-card.current.expanded {
  box-shadow:
    inset 3px 0 0 var(--accent-blue),
    0 0 0 1px color-mix(in srgb, var(--accent-blue) 28%, transparent),
    var(--shadow-md);
}

.st-exchange-card.unroutable {
  opacity: 0.92;
}

.st-exchange-card-head {
  display: grid;
  width: 100%;
  grid-template-columns: 28px minmax(0, 1fr) auto;
  grid-template-areas:
    "disc identity badges"
    "disc meta meta";
  align-items: start;
  column-gap: 12px;
  row-gap: 8px;
  padding: 14px 16px;
  border: 0;
  background: transparent;
  color: var(--ex-ink);
  text-align: left;
  cursor: pointer;
}

.st-exchange-card-head:hover {
  background: color-mix(in srgb, var(--accent-blue) 7%, transparent);
}

.st-exchange-disclosure {
  display: grid;
  grid-area: disc;
  place-items: center;
  width: 24px;
  height: 24px;
  margin-top: 1px;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--ex-ink) 8%, transparent);
  color: var(--ex-label);
}

.st-exchange-chevron {
  display: block;
  font-size: 13px;
  line-height: 1;
  transform-origin: 50% 55%;
  transition: transform 0.15s ease;
}

.st-exchange-card.expanded .st-exchange-disclosure {
  background: color-mix(in srgb, var(--accent-blue) 18%, transparent);
  color: var(--text-accent);
}

.st-exchange-card.expanded .st-exchange-chevron {
  transform: rotate(90deg);
}

.st-exchange-identity {
  grid-area: identity;
  min-width: 0;
  padding-top: 1px;
}

.st-exchange-identity strong,
.st-exchange-identity small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.st-exchange-identity strong {
  color: var(--ex-ink);
  font-size: 14px;
  font-weight: 700;
  line-height: 1.3;
}

.st-exchange-identity small {
  margin-top: 2px;
  color: var(--ex-subtle);
  font-family: var(--font-mono, monospace);
  font-size: 11px;
}

.st-exchange-row-badges {
  display: flex;
  grid-area: badges;
  min-width: 0;
  max-width: 340px;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 6px;
}

.st-exchange-directory .st-series-badge {
  padding: 3px 9px;
  border: 1px solid transparent;
  font-size: 11px;
  line-height: 1.3;
}

.st-exchange-directory .st-badge-ok {
  background: var(--ex-ok-bg);
  color: var(--ex-ok);
}

.st-exchange-directory .st-badge-fail {
  background: var(--ex-fail-bg);
  color: var(--ex-fail);
}

.st-exchange-directory .st-badge-info {
  background: var(--ex-info-bg);
  color: var(--ex-info);
}

.st-exchange-row-meta {
  display: flex;
  grid-area: meta;
  min-width: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
}

.st-exchange-row-markets {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  gap: 6px;
}

.st-exchange-chip {
  padding: 3px 8px;
  border-radius: var(--radius-full);
  background: var(--ex-chip-bg);
  color: var(--ex-chip-fg);
  font-size: 11px;
  font-weight: 700;
  line-height: 1.3;
}

.st-exchange-chip.muted {
  background: color-mix(in srgb, var(--ex-subtle) 16%, transparent);
  color: var(--ex-subtle);
}

.st-exchange-row-capabilities {
  min-width: 0;
  color: var(--ex-subtle);
  font-size: 12px;
  line-height: 1.45;
}

.st-exchange-card-detail {
  padding: 16px;
  border-top: 1px solid var(--ex-card-border);
  background: var(--ex-inset-bg);
}

.st-exchange-detail-section h4 {
  margin: 0 0 10px;
  color: var(--ex-label);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.st-exchange-surfaces {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(148px, 1fr));
  gap: 8px;
}

.st-exchange-surface {
  padding: 10px 12px;
  border: 1px solid var(--ex-card-border);
  border-radius: var(--radius-md);
  background: var(--ex-card-bg);
}

.st-exchange-surface span,
.st-exchange-surface strong {
  display: block;
}

.st-exchange-surface span {
  color: var(--ex-label);
  font-size: 11px;
  font-weight: 700;
}

.st-exchange-surface strong {
  margin-top: 5px;
  color: var(--ex-pending);
  font-size: 12px;
  font-weight: 700;
  line-height: 1.4;
}

.st-exchange-surface.supported {
  border-color: color-mix(in srgb, var(--ex-ok) 35%, var(--ex-card-border));
  background: var(--ex-ok-bg);
}

.st-exchange-surface.supported strong {
  color: var(--ex-ok);
}

.st-exchange-surface.pending {
  border-color: color-mix(in srgb, var(--ex-pending) 28%, var(--ex-card-border));
  background: var(--ex-pending-bg);
}

.st-exchange-qualification {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin-top: 12px;
  padding: 10px 12px;
  border: 1px solid color-mix(in srgb, var(--ex-ok) 32%, var(--ex-card-border));
  border-radius: var(--radius-md);
  background: var(--ex-ok-bg);
  color: var(--ex-label);
  font-size: 12px;
  line-height: 1.45;
}

.st-exchange-qualification strong {
  color: var(--ex-ok);
}

.st-exchange-market-detail {
  margin-top: 12px;
  border: 1px solid var(--ex-card-border);
  border-radius: var(--radius-lg);
  background: var(--ex-card-bg);
  overflow: hidden;
}

.st-exchange-market-detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--ex-card-border);
}

.st-exchange-market-detail-head strong,
.st-exchange-market-detail-head span {
  display: block;
}

.st-exchange-market-detail-head strong {
  color: var(--ex-ink);
  font-size: 13px;
}

.st-exchange-market-detail-head span {
  margin-top: 2px;
  color: var(--ex-subtle);
  font-family: var(--font-mono, monospace);
  font-size: 11px;
}

.st-exchange-test-button {
  flex-shrink: 0;
  padding: 7px 11px;
  border: 1px solid color-mix(in srgb, var(--accent-blue) 40%, var(--ex-card-border));
  border-radius: var(--radius-md);
  background: var(--ex-refresh-bg);
  color: var(--ex-refresh-fg);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.st-exchange-test-button:hover:not(:disabled) {
  filter: brightness(1.06);
}

.st-exchange-test-button:disabled {
  opacity: 0.5;
  cursor: default;
}

.st-exchange-check-result {
  padding: 9px 14px;
  border-bottom: 1px solid var(--ex-card-border);
  font-size: 12px;
}

.st-exchange-check-result.success {
  background: var(--ex-ok-bg);
  color: var(--ex-ok);
}

.st-exchange-check-result.error {
  background: var(--ex-fail-bg);
  color: var(--ex-fail);
}

.st-exchange-capability-header,
.st-exchange-capability-row {
  display: grid;
  grid-template-columns: minmax(120px, 1.05fr) minmax(105px, 0.8fr) minmax(100px, 0.75fr) minmax(230px, 2fr);
  gap: 10px;
  align-items: start;
}

.st-exchange-capability-header {
  padding: 9px 14px;
  background: color-mix(in srgb, var(--ex-ink) 5%, transparent);
  color: var(--ex-label);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.st-exchange-capability-row {
  padding: 11px 14px;
  border-top: 1px solid var(--ex-card-border);
  color: var(--ex-label);
  font-size: 12px;
  line-height: 1.5;
}

.st-exchange-capability-row > div > strong {
  color: var(--ex-ink);
  font-size: var(--font-size-md);
}

.st-exchange-inline-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}

.st-exchange-inline-chips span {
  padding: 2px 6px;
  border-radius: var(--radius-control);
  background: var(--ex-chip-bg);
  color: var(--ex-chip-fg);
  font-family: var(--font-mono, monospace);
  font-size: 11px;
}

.st-exchange-quality strong,
.st-exchange-quality span {
  display: block;
}

.st-exchange-quality strong {
  margin-bottom: 3px;
  color: var(--ex-ink);
}

.st-exchange-quality span {
  color: var(--ex-subtle);
}

.st-exchange-quality span + span {
  margin-top: 2px;
}

.st-exchange-limitations {
  margin-top: 12px;
  padding: 12px 14px;
  border: 1px solid color-mix(in srgb, var(--ex-warn) 35%, var(--ex-card-border));
  border-radius: var(--radius-md);
  background: var(--ex-warn-bg);
  color: var(--ex-label);
  font-size: 12px;
  line-height: 1.55;
}

.st-exchange-limitations strong {
  color: var(--ex-warn);
}

.st-exchange-limitations ul {
  margin: 6px 0 0;
  padding-left: 18px;
}

.st-exchange-empty {
  padding: 18px 14px;
  color: var(--ex-subtle);
  font-size: 13px;
  text-align: center;
}

/* ── Responsive ─────────────────────────────────────────── */
@media (max-width: 640px) {
  .st-panel {
    flex-direction: column;
    height: 92vh;
    width: 96vw;
  }

  .st-sidebar {
    width: 100%;
    min-width: unset;
    flex-direction: row;
    border-right: none;
    border-bottom: 1px solid var(--border-color);
    padding: 0;
    align-items: center;
  }

  .st-sidebar-title {
    padding: 12px 16px;
    font-size: 15px;
  }

  .st-sidebar-nav {
    flex-direction: row;
    gap: 2px;
    padding: 0 4px;
    overflow-x: auto;
  }

  .st-nav-item {
    padding: 8px 12px;
    white-space: nowrap;
    font-size: var(--font-size-md);
  }

  .st-nav-label {
    display: none;
  }

  .st-sidebar-footer {
    display: none;
  }

  .st-content-body {
    padding: 16px;
  }

  .st-theme-grid {
    grid-template-columns: repeat(3, 1fr);
  }

  .st-appearance-theme-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .st-preset-cards {
    grid-template-columns: repeat(2, 1fr);
  }

  .st-ephemeral-cards {
    grid-template-columns: repeat(2, 1fr);
  }

  .st-exchange-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .st-exchange-card-head {
    grid-template-columns: 28px minmax(0, 1fr);
    grid-template-areas:
      "disc identity"
      "disc badges"
      "disc meta";
  }

  .st-exchange-row-badges {
    max-width: none;
    justify-content: flex-start;
  }

  .st-exchange-surfaces {
    grid-template-columns: 1fr;
  }

  .st-exchange-capability-header {
    display: none;
  }

  .st-exchange-capability-row {
    grid-template-columns: 1fr;
  }

  .st-group-title-row {
    align-items: flex-start;
    gap: 10px;
  }

  .st-tier-header,
  .st-tier-row {
    grid-template-columns: 1.5fr 1fr 1fr;
  }

  .st-tier-col-size {
    display: none;
  }
}
.st-tool-card {
  padding: 16px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-color);
  background: var(--bg-tertiary);
}

[data-theme='light'] .st-tool-card {
  background: var(--surface-0);
  border-color: var(--border-subtle);
  box-shadow: var(--shadow-sm);
}

[data-theme='light'] .st-tool-desc {
  color: var(--text-secondary);
}

[data-theme='light'] .st-gc-scope-card,
[data-theme='light'] .st-diagnostics-card,
[data-theme='light'] .st-db-summary-card {
  background: var(--surface-0);
  border-color: var(--border-subtle);
}

[data-theme='light'] .st-gc-scope-title,
[data-theme='light'] .st-gc-scope-detail,
[data-theme='light'] .st-diagnostics-label,
[data-theme='light'] .st-diagnostics-detail,
[data-theme='light'] .st-db-summary-card span {
  color: var(--text-secondary);
}

.st-tool-header {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}

.st-tool-icon {
  display: inline-flex;
  flex-shrink: 0;
  margin-top: 1px;
  color: var(--text-secondary);
}

.st-result-message {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.st-tool-name {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.st-tool-desc {
  font-size: 12px;
  line-height: 1.55;
  color: var(--text-secondary);
}

/* ── Result box ─────────────────────────────────────────── */
.st-result {
  margin-top: 12px;
  padding: 14px;
  border-radius: var(--radius-lg);
  font-size: var(--font-size-md);
  line-height: 1.5;
}

.st-result-ok {
  background: color-mix(in srgb, var(--color-success) 6%, transparent);
  border: 1px solid color-mix(in srgb, var(--color-success) 20%, transparent);
  color: var(--text-success);
}

.st-result-warn {
  background: color-mix(in srgb, var(--color-warning) 6%, transparent);
  border: 1px solid color-mix(in srgb, var(--color-warning) 20%, transparent);
  color: var(--text-warning);
}

.st-result-fail {
  background: color-mix(in srgb, var(--color-danger) 6%, transparent);
  border: 1px solid color-mix(in srgb, var(--color-danger) 20%, transparent);
  color: var(--text-danger);
}

.st-result-head {
  font-weight: 600;
  margin-bottom: 6px;
}

.st-result-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  font-size: var(--font-size-sm);
}

.st-result-detail {
  margin-top: 4px;
  font-size: 11px;
  opacity: 0.8;
  font-family: var(--font-mono, monospace);
}

/* ── Series list (repair details) ───────────────────────── */
.st-series-list {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.st-series-item {
  padding-top: 8px;
  border-top: 1px solid color-mix(in srgb, var(--text-primary) 6%, transparent);
}

.st-series-line {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.st-series-name {
  font-family: var(--font-mono, monospace);
  font-size: var(--font-size-sm);
  color: var(--text-primary);
}

.st-series-meta {
  color: var(--text-muted);
  font-size: var(--font-size-xs);
  font-weight: 400;
}

.st-series-badge {
  padding: 2px 10px;
  border-radius: var(--radius-full);
  font-size: var(--font-size-2xs);
  font-weight: 600;
  white-space: nowrap;
}

.st-badge-ok {
  background: color-mix(in srgb, var(--color-success) 12%, transparent);
  color: var(--text-success);
}
.st-badge-fail {
  background: color-mix(in srgb, var(--color-danger) 12%, transparent);
  color: var(--text-danger);
}
.st-badge-info {
  background: color-mix(in srgb, var(--accent-blue) 12%, transparent);
  color: var(--text-accent);
}

.st-series-msg {
  margin-top: 4px;
  color: var(--text-secondary);
  font-size: 11px;
}

.st-series-more {
  margin-top: 4px;
  font-size: 11px;
  color: var(--text-muted);
}

/* ── Database tools ─────────────────────────────────────── */
.st-db-summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.st-db-summary-card {
  min-height: 64px;
  padding: 12px 14px;
  border: 1px solid var(--border-color);
  background: var(--bg-tertiary);
  border-radius: var(--radius-lg);
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 5px;
}

.st-db-summary-card span {
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 600;
}

.st-db-summary-card strong {
  color: var(--text-primary);
  font-size: 15px;
  font-family: var(--font-mono, monospace);
  font-weight: 700;
  line-height: 1.25;
}

.st-db-summary-wide {
  grid-column: span 2;
}

.st-db-filter-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
}

.st-db-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.st-db-field span {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
}

.st-db-scope-actions .st-btn {
  min-width: 0;
}

.st-db-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.st-db-empty {
  padding: 24px 16px;
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-lg);
  text-align: center;
  color: var(--text-muted);
  font-size: var(--font-size-md);
  background: color-mix(in srgb, var(--text-primary) 2%, transparent);
}

.st-db-symbol-card {
  border: 1px solid var(--border-color);
  background: var(--bg-tertiary);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.st-db-symbol-head {
  width: 100%;
  min-height: 52px;
  display: grid;
  grid-template-columns: 18px minmax(100px, 1fr) auto auto auto minmax(130px, auto);
  gap: 8px;
  align-items: center;
  padding: 12px 14px;
  border: none;
  background: transparent;
  color: var(--text-primary);
  cursor: pointer;
  text-align: left;
}

.st-db-symbol-head:hover {
  background: color-mix(in srgb, var(--text-primary) 3%, transparent);
}

.st-db-expand {
  color: var(--text-muted);
  font-size: 13px;
}

.st-db-symbol-name {
  min-width: 0;
  overflow-wrap: anywhere;
  font-family: var(--font-mono, monospace);
  font-size: 13.5px;
  font-weight: 700;
}

.st-db-chip {
  padding: 3px 8px;
  border-radius: var(--radius-control);
  background: color-mix(in srgb, var(--text-primary) 6%, transparent);
  color: var(--text-secondary);
  font-size: var(--font-size-xs);
  font-weight: 700;
  white-space: nowrap;
}

.st-db-symbol-meta {
  color: var(--text-muted);
  font-size: 11px;
  text-align: right;
  white-space: nowrap;
}

.st-db-symbol-body {
  border-top: 1px solid color-mix(in srgb, var(--text-primary) 5%, transparent);
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.st-db-symbol-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 2px 2px 8px;
  color: var(--text-muted);
  font-size: 11px;
}

.st-db-symbol-toolbar .st-btn {
  margin-left: auto;
}

.st-db-series-row {
  display: grid;
  grid-template-columns: 90px 82px minmax(180px, 1.6fr) 70px 100px 180px;
  gap: 10px;
  align-items: center;
  padding: 10px;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--surface-0) 42%, transparent);
}

.st-db-series-main {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 5px;
  min-width: 0;
}

.st-db-interval {
  color: var(--text-primary);
  font-family: var(--font-mono, monospace);
  font-size: 13px;
  font-weight: 700;
}

.st-db-series-stat {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.st-db-series-stat span {
  color: var(--text-muted);
  font-size: var(--font-size-xs);
  font-weight: 700;
}

.st-db-series-stat strong {
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.st-db-row-actions {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
}

.st-db-mini-btn {
  flex: none;
  min-height: 32px;
  padding: 6px 8px;
  font-size: var(--font-size-sm);
}

.st-db-dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: calc(var(--z-modal) + 2);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 18px;
  background: var(--backdrop);
}

.st-db-dialog {
  width: min(460px, 100%);
  padding: 18px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  box-shadow: var(--shadow-lg);
}

.st-db-dialog-title {
  color: var(--text-primary);
  font-size: 15px;
  font-weight: 700;
  margin-bottom: 6px;
}

.st-db-dialog-subtitle {
  color: var(--text-secondary);
  font-family: var(--font-mono, monospace);
  font-size: var(--font-size-sm);
  line-height: 1.5;
  margin-bottom: 14px;
  overflow-wrap: anywhere;
}

.st-db-dialog-grid {
  display: grid;
  gap: 12px;
}

.st-db-dialog-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 9px 12px;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--text-primary) 4%, transparent);
  font-size: 12px;
}

.st-db-dialog-row span {
  color: var(--text-muted);
}

.st-db-dialog-row strong {
  color: var(--text-primary);
  font-family: var(--font-mono, monospace);
  text-align: right;
}

.st-db-confirm-field {
  margin-top: 12px;
}

@media (max-width: 860px) {
  .st-db-summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .st-db-filter-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .st-db-series-row {
    grid-template-columns: 80px 82px minmax(160px, 1fr) 86px;
  }

  .st-db-series-row .st-db-series-stat:nth-of-type(4),
  .st-db-series-row .st-db-series-stat:nth-of-type(5) {
    display: none;
  }

  .st-db-row-actions {
    grid-column: 1 / -1;
  }
}

@media (max-width: 640px) {
  .st-db-summary-grid,
  .st-db-filter-grid {
    grid-template-columns: 1fr;
  }

  .st-db-summary-wide {
    grid-column: auto;
  }

  .st-db-symbol-head {
    grid-template-columns: 18px minmax(90px, 1fr) auto;
    align-items: start;
  }

  .st-db-symbol-head .st-series-badge,
  .st-db-symbol-meta {
    grid-column: 2 / -1;
  }

  .st-db-chip {
    justify-self: start;
  }

  .st-db-symbol-meta {
    text-align: left;
  }

  .st-db-series-row {
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .st-db-series-row .st-db-series-stat:nth-of-type(4),
  .st-db-series-row .st-db-series-stat:nth-of-type(5) {
    display: flex;
  }

  .st-db-series-main,
  .st-db-series-stat {
    flex-direction: row;
    justify-content: space-between;
    align-items: center;
  }

  .st-db-row-actions {
    grid-template-columns: 1fr;
  }

  .st-db-scope-actions {
    flex-direction: column;
  }
}

/* ── About section ──────────────────────────────────────── */
.st-support-card { border: 1px solid var(--border-color); border-radius: var(--radius-lg); padding: 20px; }
.st-support-description { color: var(--text-primary); font-size: 13px; line-height: 1.7; }
.st-support-hint { color: var(--text-secondary); font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; }
.st-support-actions, .st-support-links { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.st-support-actions a { text-decoration: none; }
.st-support-actions label { color: var(--text-secondary); font-size: 13px; }
.st-support-actions select { color: var(--text-primary); background: var(--bg-tertiary); border: 1px solid var(--border-color); border-radius: var(--radius-control); padding: 7px; }
.st-support-links a { color: var(--text-accent); font-size: 13px; text-underline-offset: 4px; }
.st-support-export { margin-top: 16px; }
.st-support-export summary { cursor: pointer; color: var(--text-primary); font-size: 13px; padding: 6px 0; }
.st-support-manual { width: 100%; min-height: 180px; box-sizing: border-box; color: var(--text-primary); background: var(--bg-tertiary); border: 1px solid var(--border-color); border-radius: var(--radius-control); padding: 10px; }
.st-support-card :focus-visible, .st-support-links a:focus-visible, .st-support-export summary:focus-visible { outline: 2px solid var(--accent-blue); outline-offset: 3px; }
.st-about-stack .st-stack-item { gap: 16px; }
.st-about-stack .st-stack-value { overflow-wrap: anywhere; text-align: right; min-width: 0; }
.st-about-header {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 20px 0 8px;
}

.st-about-logo {
  margin-bottom: 12px;
  filter: drop-shadow(0 4px 12px color-mix(in srgb, var(--accent-blue) 30%, transparent));
}

.st-about-name {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 0.01em;
}

.st-about-name-accent {
  color: #12bfae;
}

.st-about-version {
  margin-top: 4px;
  font-size: 13px;
  color: var(--text-accent);
  font-weight: 600;
  padding: 2px 12px;
  background: color-mix(in srgb, var(--accent-blue) 10%, transparent);
  border-radius: var(--radius-full);
}

.st-about-tagline {
  margin-top: 10px;
  font-size: 13px;
  color: var(--text-secondary);
}

.st-about-stack {
  display: flex;
  flex-direction: column;
  gap: 1px;
  border-radius: var(--radius-lg);
  overflow: hidden;
  border: 1px solid var(--border-color);
}

.st-stack-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 11px 16px;
  background: var(--bg-tertiary);
  font-size: 13px;
}

.st-stack-item + .st-stack-item {
  border-top: 1px solid color-mix(in srgb, var(--text-primary) 4%, transparent);
}

.st-stack-label {
  color: var(--text-muted);
  font-weight: 500;
}

.st-stack-value {
  color: var(--text-primary);
  font-weight: 500;
}

.st-shortcut-item {
  gap: 20px;
}

.st-shortcut-item kbd {
  flex-shrink: 0;
  font-family: inherit;
  white-space: nowrap;
}

.st-shortcut-item .st-stack-label {
  text-align: right;
}


/* ── Exchange connectivity test results ─────────────────── */
.st-exchange-results {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.st-exchange-result-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: var(--radius-md);
  font-size: 12px;
  transition: background 0.15s;
}

.st-exchange-result-item.ok {
  background: color-mix(in srgb, var(--color-success) 6%, transparent);
}

.st-exchange-result-item.fail {
  background: color-mix(in srgb, var(--color-danger) 6%, transparent);
}

.st-exchange-result-icon {
  display: inline-flex;
  flex-shrink: 0;
}

.st-exchange-result-item.ok .st-exchange-result-icon { color: var(--text-success); }
.st-exchange-result-item.fail .st-exchange-result-icon { color: var(--text-danger); }

.st-exchange-result-label {
  font-weight: 600;
  color: var(--text-primary);
  min-width: 110px;
}

.st-exchange-result-msg {
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
  flex: 1;
  text-align: right;
}
    `}</style>
  );
}
