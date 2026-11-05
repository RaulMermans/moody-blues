import "server-only";

export type PublicOrigin =
  | { state: "unset" }
  | { state: "invalid" }
  | { state: "set"; origin: string };

// The site's own address, from deployment configuration. Only an exact https origin counts: a
// value with a path, or plain http, is a configuration error, and sign-in then refuses.
export function publicOrigin(): PublicOrigin {
  const value = process.env.MOODY_PUBLIC_ORIGIN;
  if (!value) return { state: "unset" };
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.origin !== value) return { state: "invalid" };
    return { state: "set", origin: url.origin };
  } catch {
    return { state: "invalid" };
  }
}
