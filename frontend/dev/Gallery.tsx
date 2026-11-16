// Gallery of the UI primitives; rendered by dev/ui-gallery.tsx.
import { useEffect, useState, type ReactNode } from "react";
import {
  Badge, Button, Checkbox, DateTimeInput, Disclosure, EmptyState, Field, FileDrop, IconButton, InlineAlert, Input, Section,
  SegmentedControl, Select, Stat, Switch, TabPanel, Tabs, Textarea,
} from "../src/components/ui/index.js";

const PlusIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M7 2v10M2 7h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
);
const CloseIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
);

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="gallery-row">
      <span className="gallery-row-label">{label}</span>
      <div className="gallery-row-items">{children}</div>
    </div>
  );
}

export default function Gallery() {
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [segment, setSegment] = useState<"follow" | "own">("follow");
  const [interval, setInterval] = useState<"1m" | "5m" | "1h" | "1d">("1h");
  const [tab, setTab] = useState<"general" | "network" | "data">("general");
  const [sync, setSync] = useState(true);
  const [time, setTime] = useState<number | null>(Date.UTC(2026, 10, 12, 8, 30));
  const [files, setFiles] = useState<string[]>([]);
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);

  return (
    <main className="gallery">
      <header className="gallery-header">
        <div>
          <h1>UI primitives</h1>
          <p>src/components/ui · primitives layer · features add layout only</p>
        </div>
        <SegmentedControl label="Theme" value={theme} onChange={setTheme} options={[{ value: "dark", label: "Dark" }, { value: "light", label: "Light" }]} />
      </header>

      <Section title="Buttons" description="One primary action per view. Secondary is the default; ghost for low-emphasis actions; danger for destructive ones.">
        <Row label="md">
          <Button variant="primary">Create alert</Button>
          <Button>Cancel</Button>
          <Button variant="ghost">Learn more</Button>
          <Button variant="danger">Delete</Button>
          <Button variant="primary" disabled>Saving</Button>
          <Button icon={<PlusIcon />}>Add chart</Button>
        </Row>
        <Row label="sm">
          <Button size="sm" variant="primary">Apply</Button>
          <Button size="sm">Retry</Button>
          <Button size="sm" variant="ghost">Details</Button>
          <Button size="sm" variant="danger">Remove</Button>
          <Button size="sm" disabled>Disabled</Button>
        </Row>
        <Row label="icon">
          <IconButton label="Add" icon={<PlusIcon />} />
          <IconButton label="Close" icon={<CloseIcon />} variant="secondary" />
          <IconButton label="Pin" icon={<PlusIcon />} pressed />
          <IconButton label="Small" icon={<CloseIcon />} size="sm" />
          <button type="button" className="ui-control">Toolbar control</button>
          <button type="button" className="ui-control is-active">Active control</button>
        </Row>
      </Section>

      <Section title="Fields" description="Every control has a visible label. Hints explain; errors say what to do.">
        <div className="gallery-grid">
          <Field label="Symbol" hint="Exchange symbol, for example BTCUSDT"><Input placeholder="BTCUSDT" /></Field>
          <Field label="Price" error="Enter a number greater than 0" required><Input defaultValue="-3" inputMode="decimal" /></Field>
          <Field label="Interval"><Select defaultValue="1h"><option value="1m">1 minute</option><option value="1h">1 hour</option></Select></Field>
          <Field label="Start" hint="Times are shown in UTC"><DateTimeInput value={time} onChange={setTime} /></Field>
          <Field label="Notes"><Textarea placeholder="Why this setup?" /></Field>
          <Field label="Disabled"><Input disabled defaultValue="Read only" /></Field>
        </div>
        <Row label="choices">
          <Checkbox label="Play a sound" description="When an alert fires" defaultChecked />
          <Checkbox label="Disabled option" disabled />
          <Switch checked={sync} onChange={setSync} label="Sync linked charts" description="Symbol and interval follow the group" />
        </Row>
        <FileDrop label="Drop a CSV file or choose one" hint="OHLCV columns, up to 50 MB" accept=".csv" onFiles={(list) => setFiles(list.map((f) => f.name))} />
        {files.length ? <p className="gallery-note">Chosen: {files.join(", ")}</p> : null}
      </Section>

      <Section title="Choices" description="Segmented controls for two to five options; tabs for views.">
        <Row label="segmented">
          <SegmentedControl label="Chart appearance" value={segment} onChange={setSegment} options={[{ value: "follow", label: "Follow app theme" }, { value: "own", label: "Own appearance" }]} />
          <SegmentedControl label="Interval" size="sm" value={interval} onChange={setInterval}
            options={[{ value: "1m", label: "1m" }, { value: "5m", label: "5m" }, { value: "1h", label: "1h" }, { value: "1d", label: "1d", disabled: true }]} />
        </Row>
        <div>
          <Tabs id="gallery-tabs" label="Settings" value={tab} onChange={setTab}
            tabs={[{ value: "general", label: "General" }, { value: "network", label: "Network", badge: 2 }, { value: "data", label: "Data" }]} />
          <TabPanel tabsId="gallery-tabs" value={tab}><p className="gallery-note">Panel: {tab}</p></TabPanel>
        </div>
      </Section>

      <Section title="Status and figures">
        <Row label="badges">
          <Badge>Neutral</Badge><Badge tone="accent">Live</Badge><Badge tone="success">Connected</Badge>
          <Badge tone="warning">Stale</Badge><Badge tone="danger">Failed</Badge>
        </Row>
        <div className="gallery-stats">
          <Stat label="Net P&amp;L" value="+1,284.20" hint="+3.1% today" tone="success" />
          <Stat label="Max drawdown" value="-6.4%" tone="danger" />
          <Stat label="Trades" value="128" hint="Win rate 54%" />
        </div>
        <InlineAlert tone="info" title="Replay data is cached">Loading from the local library; no network needed.</InlineAlert>
        <InlineAlert tone="success" title="Settings saved" />
        <InlineAlert tone="warning" title="Feed delayed" action={<Button size="sm">Reconnect</Button>}>Order book updates are 4 s behind.</InlineAlert>
        <InlineAlert tone="danger" title="Backtest failed">The strategy raised an error on bar 214.</InlineAlert>
        <Disclosure summary="Technical details">Request id 7f3c · provider binance · retry after 2 s</Disclosure>
      </Section>

      <Section title="Empty states">
        <div className="gallery-grid">
          <div className="gallery-panel"><EmptyState title="No alerts yet" description="Create an alert from the chart or here." action={<Button size="sm" variant="primary">Create alert</Button>} /></div>
          <div className="gallery-panel"><EmptyState compact tone="warning" title="Feed paused" description="Reconnecting…" /></div>
        </div>
      </Section>
    </main>
  );
}
