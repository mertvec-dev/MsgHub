const KEY_ALIAS = 'msghub-e2e-p256-private-jwk-v1';
const ROOM_KEY_PREFIX = 'msghub-e2e-room-key-v1';

type JsonWebKeyWithKid = JsonWebKey & { kid?: string };

function arrayBufferToBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

function utf8ToBase64(text: string): string {
  return btoa(unescape(encodeURIComponent(text)));
}

function base64ToUtf8(encoded: string): string {
  return decodeURIComponent(escape(atob(encoded)));
}

function base64ToArrayBuffer(base64: string): ArrayBuffer {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

function randomNonce(length = 12): string {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  let out = '';
  for (let i = 0; i < bytes.length; i++) out += alphabet[bytes[i] % alphabet.length];
  return out;
}

async function importOwnPrivateKey(): Promise<CryptoKey | null> {
  const raw = localStorage.getItem(KEY_ALIAS);
  if (!raw) return null;
  const jwk = JSON.parse(raw) as JsonWebKeyWithKid;
  return crypto.subtle.importKey('jwk', jwk, { name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']);
}

async function createAndPersistOwnKeyPair(): Promise<{ publicKeyB64: string }> {
  const keyPair = await crypto.subtle.generateKey(
    { name: 'ECDH', namedCurve: 'P-256' },
    true,
    ['deriveBits']
  );
  const privateJwk = await crypto.subtle.exportKey('jwk', keyPair.privateKey);
  localStorage.setItem(KEY_ALIAS, JSON.stringify(privateJwk));

  const publicRaw = await crypto.subtle.exportKey('raw', keyPair.publicKey);
  return { publicKeyB64: arrayBufferToBase64(publicRaw) };
}

export async function ensureOwnPublicKey(): Promise<{ publicKeyB64: string }> {
  const existingPrivate = await importOwnPrivateKey();
  if (!existingPrivate) return createAndPersistOwnKeyPair();

  const jwk = JSON.parse(localStorage.getItem(KEY_ALIAS) || '{}') as JsonWebKeyWithKid;
  if (!jwk.x || !jwk.y) return createAndPersistOwnKeyPair();

  // uncompressed point: 0x04 || X(32) || Y(32)
  const x = base64ToArrayBuffer(jwk.x.replace(/-/g, '+').replace(/_/g, '/'));
  const y = base64ToArrayBuffer(jwk.y.replace(/-/g, '+').replace(/_/g, '/'));
  const raw = new Uint8Array(65);
  raw[0] = 0x04;
  raw.set(new Uint8Array(x), 1);
  raw.set(new Uint8Array(y), 33);
  return { publicKeyB64: arrayBufferToBase64(raw.buffer) };
}

export function hasLocalPrivateKey(): boolean {
  return Boolean(localStorage.getItem(KEY_ALIAS));
}

export function clearLocalPrivateKey(): void {
  localStorage.removeItem(KEY_ALIAS);
}

async function importPeerPublicKey(base64RawPublicKey: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    'raw',
    base64ToArrayBuffer(base64RawPublicKey),
    { name: 'ECDH', namedCurve: 'P-256' },
    true,
    []
  );
}

async function deriveAesKey(peerPublicKeyB64: string): Promise<CryptoKey> {
  const ownPrivate = await importOwnPrivateKey();
  if (!ownPrivate) throw new Error('Локальный E2E-ключ не найден');
  const peerPublic = await importPeerPublicKey(peerPublicKeyB64);
  const bits = await crypto.subtle.deriveBits(
    { name: 'ECDH', public: peerPublic },
    ownPrivate,
    256
  );
  return crypto.subtle.importKey('raw', bits, { name: 'AES-GCM' }, false, ['encrypt', 'decrypt']);
}

function roomKeyStorageKey(roomId: number, keyVersion: number): string {
  return `${ROOM_KEY_PREFIX}:${roomId}:${keyVersion}`;
}

export async function encryptForPeer(
  plaintext: string,
  peerPublicKeyB64: string
): Promise<{ content: string; nonce: string; key_version: number }> {
  const key = await deriveAesKey(peerPublicKeyB64);
  const nonce = randomNonce(12);
  const iv = new TextEncoder().encode(nonce);
  const ciphertext = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv },
    key,
    new TextEncoder().encode(plaintext)
  );
  return {
    content: arrayBufferToBase64(ciphertext),
    nonce,
    key_version: 1,
  };
}

export async function decryptFromPeer(
  encryptedContent: string,
  nonce: string,
  peerPublicKeyB64: string
): Promise<string> {
  const key = await deriveAesKey(peerPublicKeyB64);
  const ciphertext = base64ToArrayBuffer(encryptedContent);
  const iv = new TextEncoder().encode(nonce);
  const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, ciphertext);
  return new TextDecoder().decode(plain);
}

export function loadRoomKey(roomId: number, keyVersion: number): string | null {
  return localStorage.getItem(roomKeyStorageKey(roomId, keyVersion));
}

export function saveRoomKey(roomId: number, keyVersion: number, roomKeyB64: string): void {
  localStorage.setItem(roomKeyStorageKey(roomId, keyVersion), roomKeyB64);
}

export function generateRoomKey(): string {
  const raw = new Uint8Array(32);
  crypto.getRandomValues(raw);
  return arrayBufferToBase64(raw.buffer);
}

async function importRoomAesKey(roomKeyB64: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    'raw',
    base64ToArrayBuffer(roomKeyB64),
    { name: 'AES-GCM' },
    false,
    ['encrypt', 'decrypt']
  );
}

export async function encryptForRoom(
  plaintext: string,
  roomKeyB64: string,
  keyVersion: number
): Promise<{ content: string; nonce: string; key_version: number }> {
  const key = await importRoomAesKey(roomKeyB64);
  const nonce = randomNonce(12);
  const iv = new TextEncoder().encode(nonce);
  const ciphertext = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv },
    key,
    new TextEncoder().encode(plaintext)
  );
  return {
    content: arrayBufferToBase64(ciphertext),
    nonce,
    key_version: keyVersion,
  };
}

export async function decryptFromRoom(
  encryptedContent: string,
  nonce: string,
  roomKeyB64: string
): Promise<string> {
  const key = await importRoomAesKey(roomKeyB64);
  const ciphertext = base64ToArrayBuffer(encryptedContent);
  const iv = new TextEncoder().encode(nonce);
  const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, ciphertext);
  return new TextDecoder().decode(plain);
}

export async function encryptRoomKeyForMember(
  roomKeyB64: string,
  memberPublicKeyB64: string
): Promise<string> {
  const key = await deriveAesKey(memberPublicKeyB64);
  const nonce = randomNonce(12);
  const iv = new TextEncoder().encode(nonce);
  const ciphertext = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv },
    key,
    base64ToArrayBuffer(roomKeyB64)
  );
  const own = await ensureOwnPublicKey();
  const envelope = {
    sender_public_key: own.publicKeyB64,
    nonce,
    ciphertext: arrayBufferToBase64(ciphertext),
    v: 1,
  };
  return utf8ToBase64(JSON.stringify(envelope));
}

export async function decryptRoomKeyEnvelope(encryptedEnvelopeB64: string): Promise<string> {
  const rawEnvelope = base64ToUtf8(encryptedEnvelopeB64);
  const envelope = JSON.parse(rawEnvelope) as {
    sender_public_key: string;
    nonce: string;
    ciphertext: string;
  };
  const key = await deriveAesKey(envelope.sender_public_key);
  const iv = new TextEncoder().encode(envelope.nonce);
  const plain = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv },
    key,
    base64ToArrayBuffer(envelope.ciphertext)
  );
  return arrayBufferToBase64(plain);
}

