import { useEffect, useState } from "react";

export interface ReplayVenue {
  id: string;
  name: string;
  markets: string[];
  trades: string[];
}
export type Market = { exchange: string; marketType: string; symbol: string };
export function useReplayVenues(enabled: boolean) {
  const [venues, setVenues] = useState<ReplayVenue[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!enabled) return;
    const abort = new AbortController();
    fetch("/api/v1/local/downloads/markets", { signal: abort.signal })
      .then(async (response) => {
        if (!response.ok) throw Error(String(response.status));
        setVenues((await response.json()) as ReplayVenue[]);
        setError("");
      })
      .catch((error) => {
        if (!abort.signal.aborted) setError(String(error));
      });
    return () => abort.abort();
  }, [enabled]);
  return { venues, error };
}
