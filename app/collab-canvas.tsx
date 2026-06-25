"use client";

import { type PointerEvent, useEffect, useMemo, useRef, useState } from "react";

type PresenceUser = {
  id: string;
  name: string;
  color: string;
  x: number;
  y: number;
  updatedAt: number;
};

type SocketMessage =
  | { type: "snapshot"; selfId: string; users: PresenceUser[] }
  | { type: "presence"; user: PresenceUser }
  | { type: "cursor"; user: PresenceUser }
  | { type: "leave"; id: string };

const colors = ["#2563eb", "#dc2626", "#16a34a", "#ca8a04", "#7c3aed", "#0891b2"];
const names = ["Mira", "Kai", "Rin", "Avery", "Noor", "Sol", "Ira", "Jules"];
const sessionUserKey = "collab-session-user";

export function CollabCanvas() {
  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectDelayRef = useRef(800);
  const lastSentAtRef = useRef(0);
  const boardRef = useRef<HTMLDivElement | null>(null);
  const [isReady, setIsReady] = useState(false);
  const [connectionState, setConnectionState] = useState<"connecting" | "open" | "closed">("connecting");
  const [users, setUsers] = useState<Record<string, PresenceUser>>({});
  const [self, setSelf] = useState<PresenceUser>(defaultUser);
  const selfId = self.id;
  const selfName = self.name;
  const selfColor = self.color;

  const otherUsers = useMemo(
    () =>
      Object.values(users)
        .filter((user) => user.id !== selfId)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [selfId, users],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSelf(createLocalUser());
      setIsReady(true);
    }, 0);

    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!isReady) {
      return;
    }

    sessionStorage.setItem(sessionUserKey, JSON.stringify({ id: self.id, name: self.name, color: self.color }));
  }, [isReady, self.id, self.name, self.color]);

  useEffect(() => {
    if (!isReady) {
      return;
    }

    let cancelled = false;

    const connect = () => {
      const ws = new WebSocket(createWebSocketUrl({ id: selfId, name: selfName, color: selfColor }));
      socketRef.current = ws;
      setConnectionState("connecting");

      ws.addEventListener("open", () => {
        reconnectDelayRef.current = 800;
        setConnectionState("open");
        ws.send(JSON.stringify({ type: "hello", name: selfName, color: selfColor }));
      });

      ws.addEventListener("message", (event) => {
        if (typeof event.data !== "string") {
          return;
        }

        const message = parseSocketMessage(event.data);
        if (!message) {
          return;
        }

        setUsers((currentUsers) => reducePresence(currentUsers, message, selfId));
      });

      ws.addEventListener("close", () => {
        setConnectionState("closed");

        if (cancelled) {
          return;
        }

        reconnectTimerRef.current = setTimeout(connect, reconnectDelayRef.current);
        reconnectDelayRef.current = Math.min(reconnectDelayRef.current * 1.6, 8000);
      });
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      socketRef.current?.close();
    };
  }, [isReady, selfId, selfName, selfColor]);

  const sendCursor = (event: PointerEvent<HTMLDivElement>) => {
    const board = boardRef.current;
    const socket = socketRef.current;

    if (!board || !socket || socket.readyState !== WebSocket.OPEN) {
      return;
    }

    const now = Date.now();
    if (now - lastSentAtRef.current < 24) {
      return;
    }
    lastSentAtRef.current = now;

    const rect = board.getBoundingClientRect();
    const x = clamp((event.clientX - rect.left) / rect.width);
    const y = clamp((event.clientY - rect.top) / rect.height);
    const nextSelf = { ...self, x, y, updatedAt: Date.now() / 1000 };

    setSelf(nextSelf);
    setUsers((currentUsers) => ({ ...currentUsers, [selfId]: nextSelf }));
    socket.send(JSON.stringify({ type: "cursor", x, y }));
  };

  const updateName = (name: string) => {
    setSelf((currentSelf) => ({ ...currentSelf, name: name.slice(0, 28) || currentSelf.name }));
  };

  const updateColor = (color: string) => {
    setSelf((currentSelf) => ({ ...currentSelf, color }));
  };

  return (
    <main className="min-h-screen overflow-hidden bg-[#f3f0e8] text-[#1d1c18]">
      <div className="grid min-h-screen grid-rows-[auto_1fr]">
        <header className="z-20 flex flex-col gap-4 border-b border-[#d8d0c0] bg-[#fbf8ef]/95 px-4 py-3 shadow-[0_1px_0_rgba(20,20,20,0.04)] backdrop-blur md:flex-row md:items-center md:justify-between md:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <div className="grid size-9 shrink-0 place-items-center border border-[#1d1c18] bg-[#f6c744] font-mono text-sm font-bold">
              RC
            </div>
            <div className="min-w-0">
              <h1 className="truncate text-base font-semibold tracking-normal">Realtime Collab Board</h1>
              <p className="truncate text-sm text-[#6c665b]">Move across the workspace to broadcast your cursor.</p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <span className={statusClassName(connectionState)}>{statusLabel(connectionState)}</span>
            <label className="flex items-center gap-2 text-sm text-[#4d473c]">
              Name
              <input
                className="h-9 w-32 border border-[#c8bda8] bg-white px-3 text-sm outline-none transition focus:border-[#1d1c18]"
                value={self.name}
                onChange={(event) => updateName(event.target.value)}
              />
            </label>
            <div className="flex items-center gap-1" aria-label="Cursor color">
              {colors.map((color) => (
                <button
                  key={color}
                  className="size-7 border border-[#1d1c18]/20 outline-none ring-offset-2 ring-offset-[#fbf8ef] transition hover:scale-105 focus:ring-2"
                  style={{
                    backgroundColor: color,
                    boxShadow: self.color === color ? "inset 0 0 0 3px white" : undefined,
                  }}
                  type="button"
                  aria-label={`Use ${color}`}
                  onClick={() => updateColor(color)}
                />
              ))}
            </div>
          </div>
        </header>

        <section className="grid min-h-0 grid-cols-1 lg:grid-cols-[1fr_280px]">
          <div
            ref={boardRef}
            className="relative min-h-[calc(100vh-160px)] overflow-hidden border-r border-[#d8d0c0] bg-[#ece7dc]"
            onPointerMove={sendCursor}
          >
            <div className="absolute inset-0 bg-[linear-gradient(#d7d0c3_1px,transparent_1px),linear-gradient(90deg,#d7d0c3_1px,transparent_1px)] bg-[size:32px_32px]" />
            <div className="absolute left-[8%] top-[10%] h-[38%] w-[38%] border border-[#2a2721] bg-[#fffaf0] shadow-[8px_8px_0_#2a2721]">
              <div className="border-b border-[#2a2721] px-4 py-3 font-mono text-xs uppercase text-[#61594b]">Frame 01</div>
              <div className="grid h-[calc(100%-43px)] grid-cols-2 gap-4 p-5">
                <div className="bg-[#f6c744] p-4 text-sm font-medium shadow-[4px_4px_0_rgba(29,28,24,0.25)]">
                  Sketch shared cursor presence
                </div>
                <div className="border border-[#b6aa95] bg-white p-4 text-sm text-[#6c665b]">Flask holds memory first. Redis later.</div>
                <div className="col-span-2 border border-dashed border-[#9c927f] bg-[#f8f4ea] p-4 text-sm text-[#6c665b]">
                  A lightweight protocol keeps the realtime path easy to swap.
                </div>
              </div>
            </div>
            <div className="absolute bottom-[12%] right-[8%] h-[34%] w-[34%] border border-[#2a2721] bg-[#fbf8ef] shadow-[8px_8px_0_#8fb8a8]">
              <div className="flex h-full flex-col justify-between p-5">
                <div>
                  <p className="font-mono text-xs uppercase text-[#61594b]">Prototype</p>
                  <h2 className="mt-2 max-w-xs text-3xl font-semibold leading-tight">Everyone sees everyone.</h2>
                </div>
                <div className="h-16 border border-[#b6aa95] bg-[repeating-linear-gradient(135deg,#fffaf0_0,#fffaf0_10px,#e1dacd_10px,#e1dacd_11px)]" />
              </div>
            </div>
            <div className="absolute left-[52%] top-[18%] h-28 w-44 rotate-[-3deg] border border-[#2a2721] bg-[#8fb8a8] p-4 text-sm font-semibold shadow-[5px_5px_0_rgba(29,28,24,0.22)]">
              Try another browser tab.
            </div>

            {otherUsers.map((user) => (
              <RemoteCursor key={user.id} user={user} />
            ))}
          </div>

          <aside className="border-t border-[#d8d0c0] bg-[#fbf8ef] p-4 lg:border-t-0">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-sm font-semibold uppercase tracking-normal text-[#4d473c]">Visitors</h2>
              <span className="font-mono text-sm text-[#6c665b]">{otherUsers.length + 1}</span>
            </div>

            <div className="space-y-2">
              <PresenceRow user={self} label="You" />
              {otherUsers.map((user) => (
                <PresenceRow key={user.id} user={user} />
              ))}
            </div>
          </aside>
        </section>
      </div>
    </main>
  );
}

function RemoteCursor({ user }: { user: PresenceUser }) {
  return (
    <div
      className="pointer-events-none absolute z-10 -translate-x-[5px] -translate-y-[4px] transition-[left,top] duration-100 ease-linear"
      style={{ left: `${user.x * 100}%`, top: `${user.y * 100}%` }}
    >
      <svg
        aria-hidden="true"
        className="h-9 w-9 drop-shadow-[0_7px_14px_rgba(29,28,24,0.18)]"
        viewBox="0 0 36 36"
      >
        <path
          d="M6 3.5 6.8 30 15.1 21.6 21 34 27.2 31 21.2 18.8 33 18.7 6 3.5Z"
          fill={user.color}
          stroke="rgba(255,255,255,0.82)"
          strokeLinejoin="round"
          strokeWidth="1.4"
        />
      </svg>
      <div
        className="ml-8 -mt-1 w-max min-w-16 rounded-full px-4 py-2 text-lg font-semibold leading-none text-white shadow-[0_12px_24px_rgba(29,28,24,0.16)]"
        style={{ backgroundColor: user.color }}
      >
        {user.name}
      </div>
    </div>
  );
}

function PresenceRow({ user, label }: { user: PresenceUser; label?: string }) {
  return (
    <div className="flex items-center gap-3 border border-[#d8d0c0] bg-white px-3 py-2">
      <span className="size-3 shrink-0" style={{ backgroundColor: user.color }} />
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{user.name}</p>
        <p className="font-mono text-xs text-[#756d60]">
          {label ?? `${Math.round(user.x * 100)}, ${Math.round(user.y * 100)}`}
        </p>
      </div>
    </div>
  );
}

function createLocalUser(): PresenceUser {
  const savedUser = sessionStorage.getItem(sessionUserKey);
  if (savedUser) {
    try {
      const parsedUser = JSON.parse(savedUser) as Partial<PresenceUser>;
      if (parsedUser.id && parsedUser.name && parsedUser.color) {
        return {
          id: parsedUser.id,
          name: parsedUser.name,
          color: parsedUser.color,
          x: 0.5,
          y: 0.5,
          updatedAt: Date.now() / 1000,
        };
      }
    } catch {
      sessionStorage.removeItem(sessionUserKey);
    }
  }

  const randomIndex = Math.floor(Math.random() * names.length);
  return {
    id: crypto.randomUUID(),
    name: names[randomIndex],
    color: colors[randomIndex % colors.length],
    x: 0.5,
    y: 0.5,
    updatedAt: Date.now() / 1000,
  };
}

function defaultUser(): PresenceUser {
  return {
    id: "pending",
    name: "Visitor",
    color: colors[0],
    x: 0.5,
    y: 0.5,
    updatedAt: 0,
  };
}

function createWebSocketUrl(user: Pick<PresenceUser, "id" | "name" | "color">) {
  const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "/server";
  const url = new URL(`${baseUrl.replace(/\/$/, "")}/ws`, window.location.origin);

  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.searchParams.set("id", user.id);
  url.searchParams.set("name", user.name);
  url.searchParams.set("color", user.color);

  return url.toString();
}

function parseSocketMessage(data: string): SocketMessage | null {
  try {
    const message = JSON.parse(data) as SocketMessage;
    return typeof message === "object" && message !== null ? message : null;
  } catch {
    return null;
  }
}

function reducePresence(currentUsers: Record<string, PresenceUser>, message: SocketMessage, selfId: string) {
  if (message.type === "snapshot") {
    return Object.fromEntries(message.users.map((user) => [user.id, user]));
  }

  if (message.type === "presence" || message.type === "cursor") {
    return { ...currentUsers, [message.user.id]: message.user };
  }

  if (message.type === "leave" && message.id !== selfId) {
    const nextUsers = { ...currentUsers };
    delete nextUsers[message.id];
    return nextUsers;
  }

  return currentUsers;
}

function statusLabel(connectionState: "connecting" | "open" | "closed") {
  if (connectionState === "open") {
    return "Live";
  }

  if (connectionState === "connecting") {
    return "Connecting";
  }

  return "Reconnecting";
}

function statusClassName(connectionState: "connecting" | "open" | "closed") {
  const baseClassName = "h-9 border px-3 text-sm font-medium leading-9";

  if (connectionState === "open") {
    return `${baseClassName} border-[#6c9d7f] bg-[#e7f2e9] text-[#25553a]`;
  }

  if (connectionState === "connecting") {
    return `${baseClassName} border-[#c8b35f] bg-[#fbf0bf] text-[#725f16]`;
  }

  return `${baseClassName} border-[#c98c82] bg-[#f6ddd7] text-[#7a2e25]`;
}

function clamp(value: number) {
  return Math.min(Math.max(value, 0), 1);
}
