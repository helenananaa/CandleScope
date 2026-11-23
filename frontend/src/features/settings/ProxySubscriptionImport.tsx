import { useState } from "react";
import { t } from "../../i18n/index.js";
import { mergeSubscriptionRoutes, type ProxyRouteConfig } from "./proxySettingsRuntime.js";
import { previewProxySubscription, prepareSubscriptionRoutes, type ProxySubscriptionPreview } from "../../services/api.js";
import { Button } from "../../components/ui/Button.js";
import { Checkbox, Field, Input } from "../../components/ui/Field.js";
import { Disclosure, InlineAlert } from "../../components/ui/Display.js";

export default function ProxySubscriptionImport({ routes, saved, onChange, disabled, onBusy }: {
    routes: ProxyRouteConfig[];
    saved: ProxyRouteConfig[];
    onChange(routes: ProxyRouteConfig[]): void;
    disabled: boolean;
    onBusy(busy: boolean): void;
}) {
    const [url, setUrl] = useState("");
    const [preview, setPreview] = useState<ProxySubscriptionPreview | null>(null);
    const [selected, setSelected] = useState<string[]>([]);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const sources = new Map<string, ProxyRouteConfig>();
    for (const route of saved) {
        if (route.url.startsWith("mihomo://")) sources.set(route.id.slice(4, 20), route);
    }
    async function load(savedRoute?: string) {
        onBusy(true);
        setBusy(true);
        setError("");
        setPreview(null);
        try {
            const data = await previewProxySubscription(savedRoute ? { saved_route_id: savedRoute } : { url });
            setUrl("");
            setPreview(data);
            setSelected(data.nodes.filter(node => routes.some(route => route.id === "sub_" + node.id)).map(node => node.id));
        } catch (err) {
            setError(String(err instanceof Error ? err.message : err));
        } finally {
            onBusy(false);
            setBusy(false);
        }
    }
    async function add() {
        if (!preview) return;
        onBusy(true);
        setBusy(true);
        setError("");
        try {
            const rows = await prepareSubscriptionRoutes(preview.preview, selected);
            onChange(mergeSubscriptionRoutes(routes, rows, preview.source));
            setPreview(null);
        } catch (err) {
            setError(String(err instanceof Error ? err.message : err));
        } finally {
            onBusy(false);
            setBusy(false);
        }
    }
    const otherCount = routes.filter(r => !r.url.startsWith("mihomo://") || !r.id.startsWith("sub_" + preview?.source)).length;
    return <Disclosure summary={t("settings.proxy.subscription")}>
        <fieldset disabled={busy || disabled} className="st-proxy-route">
            <Field label={t("settings.proxy.subscriptionUrl")}>
                <Input type="password" autoComplete="off" value={url} onChange={e => setUrl(e.target.value)} />
            </Field>
            <Button disabled={!url.trim()} onClick={() => void load()}>{t("settings.proxy.previewNodes")}</Button>
            {[...sources.values()].map(route => <Button key={route.id} onClick={() => void load(route.id)}>
                {t("settings.diag.refresh")} · {route.name}
            </Button>)}
            {preview && <>
                {preview.skipped > 0 && <InlineAlert tone="warning">{t("settings.proxy.skippedNodes", { count: preview.skipped })}</InlineAlert>}
                {preview.nodes.map(node => <Checkbox key={node.id} label={node.name} description={node.protocol}
                    checked={selected.includes(node.id)}
                    disabled={!selected.includes(node.id) && otherCount + selected.length >= 16}
                    onChange={event => setSelected(event.target.checked ? [...selected, node.id] : selected.filter(id => id !== node.id))} />)}
                <Button disabled={!selected.length || selected.length + otherCount > 16} onClick={() => void add()}>
                    {t("settings.proxy.useNodes")}
                </Button>
            </>}
            {error && <InlineAlert tone="danger">{error}</InlineAlert>}
        </fieldset>
    </Disclosure>;
}
