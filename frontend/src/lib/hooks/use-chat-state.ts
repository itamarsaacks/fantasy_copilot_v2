"use client";

/**
 * Cross-mount store for the Conversation component's local state.
 *
 * Problem this solves: `messages` and `draft` previously lived in
 * `useState` inside `Conversation`. When the user navigates from /chat
 * to /team and back, the component unmounts and that state is dropped.
 * Worse, any in-flight chat reply resolves AFTER unmount and calls
 * `setMessages` on a dead component — React silently drops the update,
 * so the reply is lost from the UI even though it's saved on the
 * server.
 *
 * Fix: lift `messages` + `draft` to a module-level singleton with a
 * subscribe API, consumed via `useSyncExternalStore`. Writes from the
 * mutation handler always land in the store regardless of mount
 * state, and the next mount reads the up-to-date snapshot
 * immediately — no blank flash, no lost replies.
 *
 * Matches the existing pattern in `use-chat-thread.ts`.
 */

import { useCallback, useSyncExternalStore } from "react";
import type { ChatMessage } from "@/components/chat/message";

type Snapshot = {
  messages: ChatMessage[];
  draft: string;
};

const _empty: Snapshot = Object.freeze({ messages: [], draft: "" });

let _state: Snapshot = _empty;

// Module-level "did we already hydrate this thread?" flag. Replaces the
// per-mount useRef so hydration doesn't re-fire just because the user
// returned to /chat.
let _lastHydratedThread: string | null = null;
// Mirrors the lastLeagueKey / lastNewChatRequestId refs that used to live
// inside the component — promoted here so a league switch (which only
// the topbar sees while the chat is unmounted) doesn't leave stale
// messages around for the next /chat visit.
let _lastSeenLeagueKey: string | null = null;
let _lastSeenNewChatRequestId: number | null = null;

type Listener = () => void;
const _listeners = new Set<Listener>();

function emit() {
  for (const l of _listeners) l();
}

function subscribe(cb: Listener): () => void {
  _listeners.add(cb);
  return () => {
    _listeners.delete(cb);
  };
}

function getSnapshot(): Snapshot {
  return _state;
}

// ---------------------------------------------------------------------------
// Mutators — call from anywhere (sendMessage handler, hydration effect, etc.)
// All writes go through here so the store stays the single source of truth.
// ---------------------------------------------------------------------------

export function setMessages(
  next: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[]),
) {
  const value =
    typeof next === "function"
      ? (next as (prev: ChatMessage[]) => ChatMessage[])(_state.messages)
      : next;
  if (value === _state.messages) return;
  _state = { messages: value, draft: _state.draft };
  emit();
}

export function setDraft(next: string) {
  if (next === _state.draft) return;
  _state = { messages: _state.messages, draft: next };
  emit();
}

export function resetChatState() {
  _state = _empty;
  _lastHydratedThread = null;
  emit();
}

// ---------------------------------------------------------------------------
// Hydration / wipe bookkeeping — module-level so it survives unmount.
// Returns true when the caller should perform the action; updates the
// guard atomically so the action only runs once per logical change.
// ---------------------------------------------------------------------------

export function shouldHydrateThread(threadId: string): boolean {
  if (_lastHydratedThread === threadId) return false;
  _lastHydratedThread = threadId;
  return true;
}

export function markThreadHydratedAs(threadId: string | null) {
  _lastHydratedThread = threadId;
}

export function checkLeagueChanged(leagueKey: string | null): boolean {
  // CRITICAL: ignore null transitions in either direction. useActiveLeague()
  // is a per-component hook with its own useState, so every remount of
  // Conversation goes through a brief leagueKey=null state before its
  // useEffect reads from localStorage. Without this guard we'd see
  // "real → null" on every remount and wipe the chat.
  if (leagueKey === null) return false;
  if (_lastSeenLeagueKey === null) {
    _lastSeenLeagueKey = leagueKey;
    return false;
  }
  if (_lastSeenLeagueKey !== leagueKey) {
    _lastSeenLeagueKey = leagueKey;
    return true;
  }
  return false;
}

export function checkNewChatRequested(id: number): boolean {
  if (_lastSeenNewChatRequestId === null) {
    _lastSeenNewChatRequestId = id;
    return false;
  }
  if (_lastSeenNewChatRequestId !== id) {
    _lastSeenNewChatRequestId = id;
    return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useChatState() {
  const snap = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  // Stable callback identities so consumers can pass these to props.
  const setMessagesCb = useCallback(setMessages, []);
  const setDraftCb = useCallback(setDraft, []);
  return {
    messages: snap.messages,
    draft: snap.draft,
    setMessages: setMessagesCb,
    setDraft: setDraftCb,
  };
}
