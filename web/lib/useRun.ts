"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, isActive, type ReviewRequest, type RunEvent, type RunView } from "./api";

export type Transport = "sse" | "polling" | "idle";

const SSE_EVENTS: RunEvent["event"][] = ["status", "node", "review", "review_required"];
const POLL_MS = 2000;
const SSE_RETRY_MS = 1500;
const SSE_MAX_FAILURES = 2; // consecutive connections that never delivered an event before we poll instead

/**
 * Loads a run and keeps it fresh.
 * Primary: Server-Sent Events (/runs/{id}/events). Fallback: poll GET /runs/{id} every 2 s.
 * The SSE stream replays the whole history on connect, so events are de-duplicated by id.
 */
export function useRun(runId: string) {
  const [run, setRun] = useState<RunView | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [transport, setTransport] = useState<Transport>("idle");

  const seen = useRef(new Set<number>());
  const source = useRef<EventSource | null>(null);
  const timers = useRef<{ poll?: ReturnType<typeof setInterval>; retry?: ReturnType<typeof setTimeout>; refresh?: ReturnType<typeof setTimeout> }>({});
  const alive = useRef(true);
  const failures = useRef(0);

  const fetchRun = useCallback(async (): Promise<RunView | null> => {
    try {
      const view = await api.getRun(runId);
      if (!alive.current) return null;
      setRun(view);
      setError(null);
      return view;
    } catch (e) {
      if (alive.current) setError(e instanceof ApiError ? e : new ApiError(String(e), null));
      return null;
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [runId]);

  const stop = useCallback(() => {
    source.current?.close();
    source.current = null;
    clearInterval(timers.current.poll);
    clearTimeout(timers.current.retry);
    timers.current.poll = undefined;
  }, []);

  const startPolling = useCallback(() => {
    stop();
    setTransport("polling");
    timers.current.poll = setInterval(async () => {
      const view = await fetchRun();
      if (view && !isActive(view.status)) {
        stop();
        setTransport("idle");
      }
    }, POLL_MS);
  }, [fetchRun, stop]);

  const connect = useCallback(() => {
    stop();
    if (typeof EventSource === "undefined") return startPolling();

    const es = new EventSource(api.eventsUrl(runId));
    source.current = es;
    let received = false;
    setTransport("sse");

    const onEvent = (msg: MessageEvent) => {
      received = true;
      failures.current = 0;
      const id = Number(msg.lastEventId);
      if (seen.current.has(id)) return;
      seen.current.add(id);
      let data: RunEvent["data"];
      try {
        data = JSON.parse(msg.data);
      } catch {
        return;
      }
      setEvents((prev) => [...prev, { id, event: msg.type as RunEvent["event"], data }]);
      // The event log is a progress signal; the run view is the source of truth for posts and scores.
      clearTimeout(timers.current.refresh);
      timers.current.refresh = setTimeout(fetchRun, 150);
    };
    SSE_EVENTS.forEach((name) => es.addEventListener(name, onEvent as EventListener));

    // The server closes the stream when the run pauses or ends; EventSource would reconnect forever, so we take over.
    es.onerror = async () => {
      es.close();
      if (source.current === es) source.current = null;
      if (!received) failures.current += 1;
      const view = await fetchRun();
      if (!alive.current) return;
      if (view && !isActive(view.status)) return setTransport("idle");
      if (failures.current >= SSE_MAX_FAILURES) return startPolling();
      timers.current.retry = setTimeout(connect, SSE_RETRY_MS);
    };
  }, [fetchRun, runId, startPolling, stop]);

  useEffect(() => {
    alive.current = true;
    seen.current = new Set();
    failures.current = 0;
    setRun(null);
    setEvents([]);
    setLoading(true);
    const timer = timers.current;

    (async () => {
      const view = await fetchRun();
      if (!alive.current) return;
      if (view) connect(); // also replays history for finished runs, which fills the timeline
    })();

    return () => {
      alive.current = false;
      stop();
      clearTimeout(timer.refresh);
    };
  }, [runId, fetchRun, connect, stop]);

  /** Send the reviewer's decision. Throws ApiError (409 / 422 / network) for the UI to show. */
  const submitReview = useCallback(
    async (body: ReviewRequest) => {
      const view = await api.review(runId, body); // returns the final state once scheduling is done
      setRun(view);
      setError(null);
      connect(); // replay events so the timeline shows human review and schedule
      return view;
    },
    [runId, connect],
  );

  return { run, events, error, loading, transport, submitReview, refresh: fetchRun };
}
