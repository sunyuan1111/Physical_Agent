import { createContext, useContext } from "react";
import type { ReactNode } from "react";
import { en } from "./en";
import type { Messages } from "./index";

const MessagesContext = createContext<Messages>(en);

export function MessagesProvider({
  children,
  value
}: {
  children: ReactNode;
  value: Messages;
}) {
  return (
    <MessagesContext.Provider value={value}>{children}</MessagesContext.Provider>
  );
}

export function useMessages(): Messages {
  return useContext(MessagesContext);
}
