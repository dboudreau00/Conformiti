function encode(buffer) {
  const bytes = new Uint8Array(buffer);
  let text = "";
  for (let i = 0; i < bytes.length; i += 1) text += String.fromCharCode(bytes[i]);
  return btoa(text).replace(/\+/g, "-").replace(/[/]/g, "_").replace(/=+$/, "");
}

function decode(text) {
  const normalised = String(text).replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalised + "=".repeat((4 - (normalised.length % 4)) % 4);
  const binary = atob(padded);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i);
  return out.buffer;
}

export function passkeysSupported() {
  return typeof window !== "undefined" && !!window.PublicKeyCredential
    && !!navigator.credentials && typeof navigator.credentials.create === "function";
}

export async function createPasskey(options) {
  const publicKey = {
    ...options,
    challenge: decode(options.challenge),
    user: { ...options.user, id: decode(options.user.id) },
    excludeCredentials: (options.excludeCredentials || []).map((c) => ({ ...c, id: decode(c.id) })),
  };
  const credential = await navigator.credentials.create({ publicKey });
  const response = credential.response;
  return {
    id: credential.id,
    rawId: encode(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: encode(response.clientDataJSON),
      attestationObject: encode(response.attestationObject),
      transports: typeof response.getTransports === "function" ? response.getTransports() : [],
    },
  };
}

export async function getAssertion(options) {
  const publicKey = {
    ...options,
    challenge: decode(options.challenge),
    allowCredentials: (options.allowCredentials || []).map((c) => ({ ...c, id: decode(c.id) })),
  };
  const credential = await navigator.credentials.get({ publicKey });
  const response = credential.response;
  return {
    id: credential.id,
    rawId: encode(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: encode(response.clientDataJSON),
      authenticatorData: encode(response.authenticatorData),
      signature: encode(response.signature),
      userHandle: response.userHandle ? encode(response.userHandle) : null,
    },
  };
}

export function passkeyErrorText(err) {
  const name = err?.name || "";
  if (name === "NotAllowedError") return "The passkey prompt was cancelled or timed out. Try again.";
  if (name === "InvalidStateError") return "That authenticator is already enrolled on this account.";
  if (name === "SecurityError") {
    return "Passkeys need a secure (https) address that matches the server's relying-party id.";
  }
  if (name === "NotSupportedError") return "This authenticator does not support the requested key type.";
  return err?.response?.data?.detail || err?.message || "The passkey could not be used.";
}
