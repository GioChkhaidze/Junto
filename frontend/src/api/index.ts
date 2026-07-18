import { getSession } from "./http";
import * as rooms from "./rooms";

export { ApiError, apiRequest, getSession, invalidateSession } from "./http";
export * from "./rooms";

/** Single import surface for pages and hooks. */
export const api = {
  getSession,
  ...rooms,
};
