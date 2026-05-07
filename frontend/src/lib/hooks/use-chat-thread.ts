"use client";

/**
 * Cross-component state for the active chat thread.
 *
 * The `Conversation` component (the chat itself) and the `RecentChats`
 * sidebar both need to know:
 *  - which thread the user is in (so RecentChats can highlight it)
 *  - how to switch to a different thread (clicked in sidebar)
 *  - how to start a brand-new thread (Plus button)
 *
 * We use a tiny zustand-style store via React context. Keeps the dependency
 * footprint zero — just useState + a custom event bus.
 */

import { useEffect, useState } from "react";

type Listener = () => void;

let _activeThreadId: string | null = null;
let _newChatRequestId = 0;
const _listeners = new Set<Listener>();

function emit() {
  for (const l of _listeners) l();
}

export function useChatThread() {
  const [activeThreadId, setActiveThreadId] = useState<string | null>(_activeThreadId);
  const [newChatRequestId, setNewChatRequestId] = useState<number>(_newChatRequestId);

  useEffect(() => {
    const listener = () => {
      setActiveThreadId(_activeThreadId);
      setNewChatRequestId(_newChatRequestId);
    };
    _listeners.add(listener);
    return () => {
      _listeners.delete(listener);
    };
  }, []);

  return {
    activeThreadId,
    /** Increments every time someone clicks "New chat". The chat component
     *  watches this and resets its local message list + thread_id. */
    newChatRequestId,
    setActiveThreadId(id: string | null) {
      _activeThreadId = id;
      emit();
    },
    openThread(id: string) {
      _activeThreadId = id;
      emit();
    },
    startNewChat() {
      _activeThreadId = null;
      _newChatRequestId += 1;
      emit();
    },
  };
}
